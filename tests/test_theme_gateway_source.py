import importlib.util,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('theme',root/'scripts/theme_gateway_source.py');theme=importlib.util.module_from_spec(spec);spec.loader.exec_module(theme)
class OverlayTests(unittest.TestCase):
 def test_body_and_other_modules_are_preserved(self):
  old=(root/'scripts/auth_proxy.js').read_text(encoding='utf8');new=theme.integrate(old)
  restored=new.split('\n',4)[4].replace('function unskinned_renderAuthPage(','function renderAuthPage(',1).replace('function unskinned_injectLogoutControl(','function injectLogoutControl(',1)
  self.assertEqual(old,restored);self.assertEqual(new,theme.integrate(new))
  data={'auth_proxy.js':old,'other':'unchanged'};self.assertEqual(theme.overlay(data)['other'],'unchanged')
 def test_drift_refuses_before_overlay(self):
  with self.assertRaises(ValueError):theme.integrate('function renderAuthPage(){}')
if __name__=='__main__':unittest.main()
