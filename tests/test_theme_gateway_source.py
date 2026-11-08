import importlib.util,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('theme',root/'scripts/theme_gateway_source.py')
theme=importlib.util.module_from_spec(spec);spec.loader.exec_module(theme)
class OverlayTests(unittest.TestCase):
 def setUp(self):
  self.old=(root/'scripts/auth_proxy.js').read_text(encoding='utf8')
 LEGACY='applyLegacyPlatformTheme'
 def v1(self,marker=None):
  body=self.old.replace('function renderAuthPage(','function unskinned_renderAuthPage(',1).replace('function injectLogoutControl(','function unskinned_injectLogoutControl(',1)
  return (marker or theme.LEGACY_MARKERS[0])+"\nconst {platformTheme:"+self.LEGACY+"}=require('./platform_ui');\n"+theme.auth_wrapper(self.LEGACY)+'\n'+theme.app_wrapper(self.LEGACY)+'\n'+body
 def migrated(self,old):
  return (old.replace(theme.app_wrapper(self.LEGACY),theme.NATIVE_APP_WRAPPER,1).replace(theme.LEGACY_MARKERS[0],theme.MARKER,1).replace(theme.LEGACY_MARKERS[1],theme.MARKER,1)
          .replace("platformTheme:"+self.LEGACY+"}","platformTheme:"+theme.ALIAS+"}",1).replace(theme.auth_wrapper(self.LEGACY),theme.AUTH_WRAPPER,1))
 def test_pristine_gateway_body_and_native_app_are_preserved(self):
  new=theme.integrate(self.old)
  restored=new.split('\n',3)[3].replace('function unskinned_renderAuthPage(','function renderAuthPage(',1)
  self.assertEqual(self.old,restored)
  self.assertNotIn('PlatformTheme(unskinned_injectLogoutControl(',new)
  self.assertNotIn('function unskinned_injectLogoutControl(',new)
 def test_login_styling_retained_and_second_application_is_identical(self):
  new=theme.integrate(self.old)
  self.assertIn(theme.AUTH_WRAPPER,new)
  self.assertEqual(new,theme.integrate(new))
 def test_existing_v1_changes_only_marker_and_application_wrapper(self):
  old=self.v1();new=theme.integrate(old)
  self.assertEqual(self.migrated(old),new);self.assertEqual(old.split('\n',4)[4],new.split('\n',4)[4])
  self.assertNotIn(self.LEGACY,new)
  self.assertEqual(new,theme.integrate(new))
 def test_already_prepared_native_v1_is_adopted_idempotently(self):
  for marker in theme.LEGACY_MARKERS:
   old=self.v1(marker).replace(theme.app_wrapper(self.LEGACY),theme.NATIVE_APP_WRAPPER)
   new=theme.integrate(old);self.assertEqual(new,self.migrated(old));self.assertEqual(new,theme.integrate(new))
 def test_other_modules_and_input_mapping_are_preserved(self):
  data={'auth_proxy.js':self.old,'other':'unchanged'};before=dict(data)
  new=theme.overlay(data);self.assertEqual(data,before);self.assertEqual(new['other'],'unchanged')
  self.assertEqual(new['platform_ui.js'],(root/'scripts/platform_ui.js').read_text(encoding='utf8'))
 def test_pristine_drift_refuses(self):
  with self.assertRaises(ValueError):theme.integrate('function renderAuthPage(){}')
 def test_v1_unknown_or_duplicate_wrappers_refuse(self):
  for source in [self.v1().replace(theme.app_wrapper(self.LEGACY),'function changed(){}'),self.v1()+'\n'+theme.app_wrapper(self.LEGACY)]:
   with self.assertRaises(ValueError):theme.integrate(source)
 def test_malformed_v2_refuses_instead_of_trusting_marker(self):
  valid=theme.integrate(self.old)
  for source in [valid+'\n'+theme.app_wrapper(),valid.replace(theme.AUTH_WRAPPER,'function changed(){}')]:
   with self.assertRaises(ValueError):theme.integrate(source)
if __name__=='__main__':unittest.main()
