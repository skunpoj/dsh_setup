import hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import install_live_client_autostart as a
import install_live_client_layer as old

@unittest.skipUnless(os.name=='posix','Native installer safety checks require Linux file descriptors')
class AutostartTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.profile=self.root/'profile.yml';self.profile.write_text('- id: original\n  config: {enabled: true}\n');self.base=self.root/'managed';self.base.mkdir(mode=0o700);self.original=self.profile.read_bytes();self.pkg={'identity':'0123456789abcdef','files':{'startup.mjs':'export default function(){}'}}
  self.addCleanup(patch.stopall);patch.object(a,'PROFILE',self.profile).start();patch.object(a,'BASE',self.base).start()
 def request(self):return {'package':self.pkg,'expected_profile_sha256':hashlib.sha256(self.profile.read_bytes()).hexdigest()}
 def test_exact_original_entries_idempotency_and_rollback(self):
  r=a.install(self.request());self.assertTrue(self.profile.read_bytes().startswith(self.original));self.assertEqual(r['preserved_native_entries'],1);after=self.profile.read_bytes();again=a.install(self.request());self.assertTrue(again['already_registered']);self.assertEqual(self.profile.read_bytes(),after);self.assertTrue(a.rollback({'recovery':r['recovery']})['native_profile_restored_exactly']);self.assertEqual(self.profile.read_bytes(),self.original)
 def test_owner_edit_refuses_rollback(self):
  r=a.install(self.request());self.profile.write_bytes(self.profile.read_bytes()+b'# owner edit\n');before=self.profile.read_bytes()
  with self.assertRaises(ValueError):a.rollback({'recovery':r['recovery']})
  self.assertEqual(before,self.profile.read_bytes())
 def test_profile_symlink_hardlink_fifo_and_size_refused(self):
  request=self.request();target=self.root/'original';self.profile.rename(target);self.profile.symlink_to(target)
  with self.assertRaises(OSError):a.install(request)
  self.profile.unlink();os.link(target,self.profile)
  with self.assertRaises(ValueError):a.install(request)
  self.profile.unlink();os.mkfifo(self.profile)
  with self.assertRaises(ValueError):a.install(request)
  self.profile.unlink();self.profile.write_bytes(b'x'*(old.MAX_PRIVATE_FILE+1))
  with self.assertRaises(ValueError):a.install(request)
 def test_corrupted_or_linked_boot_member_refused(self):
  a.install(self.request());asset=self.base/'boot'/self.pkg['identity']/'startup.mjs';asset.write_text('different');before=self.profile.read_bytes()
  with self.assertRaises(ValueError):a.install(self.request())
  self.assertEqual(before,self.profile.read_bytes());asset.unlink();asset.symlink_to(self.profile)
  with self.assertRaises(OSError):a.install(self.request())
 def test_concurrent_profile_edit_preserved(self):
  run=a.subprocess.run
  def changed(*args,**kwargs):
   result=run(*args,**kwargs);self.profile.write_bytes(self.profile.read_bytes()+b'# owner concurrent edit\n');return result
  with patch.object(a.subprocess,'run',side_effect=changed):
   with self.assertRaisesRegex(ValueError,'Concurrent profile edit'):a.install(self.request())
  self.assertEqual(self.profile.read_bytes(),self.original+b'# owner concurrent edit\n')
 def test_root_selector_collision_and_prototype_ids_refused(self):
  for text in ['- id: \"\"\n  config: {}\n','- id: __proto__\n','- id: constructor\n','- id: prototype\n']:
   self.profile.write_text(text);before=self.profile.read_bytes()
   with self.assertRaises(ValueError):a.install(self.request())
   self.assertEqual(self.profile.read_bytes(),before)
 def test_wrong_profile_hash_invalid_yaml_and_collision_refused(self):
  r=self.request();r['expected_profile_sha256']='0'*64
  with self.assertRaises(ValueError):a.install(r)
  self.profile.write_text('key: value\n')
  with self.assertRaises(ValueError):a.install(self.request())
  self.profile.write_text('- id: dsh-managed-client-autostart\n')
  with self.assertRaises(ValueError):a.install(self.request())

if __name__=='__main__':unittest.main()
