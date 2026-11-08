import importlib.util,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('theme',root/'scripts/theme_gateway_source.py')
theme=importlib.util.module_from_spec(spec);spec.loader.exec_module(theme)
def pristine(source):
 # The repository records the live gateway, which already carries an overlay header. Rebuild the
 # upstream body the fixtures expect: drop the four header lines and undo the two renames.
 if not source.startswith((theme.OLD_MARKER,theme.MARKER)):return source
 lines=source.split('\n',4)
 assert lines[2]==theme.AUTH_WRAPPER and lines[3] in (theme.OLD_APP_WRAPPER,theme.NATIVE_APP_WRAPPER),'Unknown overlay header'
 body=lines[4].replace('function unskinned_renderAuthPage(','function renderAuthPage(',1)
 return body.replace('function unskinned_injectLogoutControl(','function injectLogoutControl(',1)
class OverlayTests(unittest.TestCase):
 def setUp(self):
  self.old=pristine((root/'scripts/auth_proxy.js').read_text(encoding='utf8'))
 def v1(self):
  body=self.old.replace('function renderAuthPage(','function unskinned_renderAuthPage(',1).replace('function injectLogoutControl(','function unskinned_injectLogoutControl(',1)
  return theme.OLD_MARKER+"\nconst {platformTheme:applyBOTPlatformTheme}=require('./platform_ui');\n"+theme.AUTH_WRAPPER+'\n'+theme.OLD_APP_WRAPPER+'\n'+body
 def test_pristine_gateway_body_and_native_app_are_preserved(self):
  new=theme.integrate(self.old)
  restored=new.split('\n',3)[3].replace('function unskinned_renderAuthPage(','function renderAuthPage(',1)
  self.assertEqual(self.old,restored)
  self.assertNotIn(theme.OLD_APP_WRAPPER,new)
  self.assertNotIn('function unskinned_injectLogoutControl(',new)
 def test_login_styling_retained_and_second_application_is_identical(self):
  new=theme.integrate(self.old)
  self.assertIn(theme.AUTH_WRAPPER,new)
  self.assertEqual(new,theme.integrate(new))
 def test_existing_v1_changes_only_marker_and_application_wrapper(self):
  old=self.v1();new=theme.integrate(old)
  expected=old.replace(theme.OLD_APP_WRAPPER,theme.NATIVE_APP_WRAPPER,1).replace(theme.OLD_MARKER,theme.MARKER,1)
  self.assertEqual(expected,new);self.assertEqual(old.split('\n',4)[4],new.split('\n',4)[4])
  self.assertEqual(new,theme.integrate(new))
 def test_already_prepared_native_v1_is_adopted_idempotently(self):
  old=self.v1().replace(theme.OLD_APP_WRAPPER,theme.NATIVE_APP_WRAPPER)
  new=theme.integrate(old);self.assertEqual(new,old.replace(theme.OLD_MARKER,theme.MARKER,1))
 def test_other_modules_and_input_mapping_are_preserved(self):
  data={'auth_proxy.js':self.old,'other':'unchanged'};before=dict(data)
  new=theme.overlay(data);self.assertEqual(data,before);self.assertEqual(new['other'],'unchanged')
  self.assertEqual(new['platform_ui.js'],(root/'scripts/platform_ui.js').read_text(encoding='utf8'))
 def test_pristine_drift_refuses(self):
  with self.assertRaises(ValueError):theme.integrate('function renderAuthPage(){}')
 def test_v1_unknown_or_duplicate_wrappers_refuse(self):
  for source in [self.v1().replace(theme.OLD_APP_WRAPPER,'function changed(){}'),self.v1()+'\n'+theme.OLD_APP_WRAPPER]:
   with self.assertRaises(ValueError):theme.integrate(source)
 def test_malformed_v2_refuses_instead_of_trusting_marker(self):
  valid=theme.integrate(self.old)
  for source in [valid+'\n'+theme.OLD_APP_WRAPPER,valid.replace(theme.AUTH_WRAPPER,'function changed(){}')]:
   with self.assertRaises(ValueError):theme.integrate(source)
if __name__=='__main__':unittest.main()
