"""Digest-bound public builder-path exception; all synthetic values stay local."""
import hashlib, importlib.util, unittest
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_scanner',ROOT/'scripts/scan_public.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
class BuilderHomeTests(unittest.TestCase):
 def test_exact_admitted_scripts_have_no_personal_path_findings(self):
  for name in s.PUBLIC_BUILD_HOME_SHA256:
   b=(ROOT/name).read_bytes()
   self.assertEqual(hashlib.sha256(b).hexdigest(),s.PUBLIC_BUILD_HOME_SHA256[name])
   self.assertFalse([x for x in s.scan_bytes(name,b) if x[1]=='personal-path'])
 def test_modified_scripts_require_review_again(self):
  for name in s.PUBLIC_BUILD_HOME_SHA256:
   self.assertTrue([x for x in s.scan_bytes(name,(ROOT/name).read_bytes()+b'\n# modified\n') if x[1]=='personal-path'])
 def test_other_paths_are_not_exempt(self):
  name=next(iter(s.PUBLIC_BUILD_HOME_SHA256));self.assertTrue(s.scan_bytes('other.sh',(ROOT/name).read_bytes()))
 def test_archive_members_are_not_exempt(self):
  name=next(iter(s.PUBLIC_BUILD_HOME_SHA256));self.assertTrue(s.scan_bytes('archive.zip!'+name,(ROOT/name).read_bytes()))
 def test_root_personal_path_is_not_generic_build_home(self):
  name=next(iter(s.PUBLIC_BUILD_HOME_SHA256));b=('/home/'+'alice/project/').encode()
  with mock.patch.dict(s.PUBLIC_BUILD_HOME_SHA256,{name:hashlib.sha256(b).hexdigest()}):
   self.assertTrue([x for x in s.scan_bytes(name,b) if x[1]=='personal-path'])
 def test_windows_personal_path_is_not_exempt(self):
  name=next(iter(s.PUBLIC_BUILD_HOME_SHA256));b=('C:'+'/'+'Users/'+'alice/project').encode()
  with mock.patch.dict(s.PUBLIC_BUILD_HOME_SHA256,{name:hashlib.sha256(b).hexdigest()}):
   self.assertTrue([x for x in s.scan_bytes(name,b) if x[1]=='personal-path'])
 def test_other_disclosure_kinds_are_still_scanned(self):
  name=next(iter(s.PUBLIC_BUILD_HOME_SHA256));b=('/work/'+'home/.cache/\n'+'-----BEGIN '+'PRIVATE KEY-----').encode()
  with mock.patch.dict(s.PUBLIC_BUILD_HOME_SHA256,{name:hashlib.sha256(b).hexdigest()}):
   findings=s.scan_bytes(name,b)
   self.assertTrue([x for x in findings if x[1]=='private-key'])
   self.assertFalse([x for x in findings if x[1]=='personal-path'])
 def test_only_two_exact_paths_are_reviewed(self):
  self.assertEqual(set(s.PUBLIC_BUILD_HOME_SHA256),{'scripts/official-sdk-build/prepare.sh','scripts/official-sdk-build/compile.sh'})
if __name__=='__main__':unittest.main()
