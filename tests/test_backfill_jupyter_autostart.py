import unittest,tempfile,json,hashlib,os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from backfill_jupyter_autostart import apply_plan
class BackfillSafety(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.root=self.base/'control';self.root.mkdir();self.key='a'*24;self.folder=self.root/self.key;self.folder.mkdir();self.file=self.folder/'config.json';self.before={'allowed':False,'services':{}};self.file.write_text(json.dumps(self.before));os.chmod(self.file,0o600);self.audit=self.base/'events.jsonl';self.backup=self.base/'backup';self.plan=[{'key':self.key,'sha256':hashlib.sha256(self.file.read_bytes()).hexdigest()}]
 def runplan(self,apply=True):return apply_plan(self.root,self.plan,self.backup,self.audit,apply)
 def test_dry_run_writes_nothing(self):
  old=self.file.read_bytes();r=self.runplan(False);self.assertEqual(r['eligible'],[self.key]);self.assertEqual(self.file.read_bytes(),old);self.assertFalse(self.backup.exists());self.assertFalse(self.audit.exists())
 def test_enable_preserves_entitlement_and_original_backup(self):
  old=self.file.read_bytes();r=self.runplan();v=json.loads(self.file.read_text());self.assertFalse(v['allowed']);self.assertTrue(v['services']['jupyter']['enabled']);self.assertEqual((self.backup/(self.key+'.json')).read_bytes(),old);self.assertEqual(len(r['applied']),1);self.assertEqual([json.loads(x)['application']['outcome']for x in self.audit.read_text().splitlines()],['requested','applied'])
 def test_second_run_does_not_rewrite_policy(self):
  self.runplan();b=self.file.read_bytes();s=self.file.stat();r=self.runplan();self.assertEqual(r['applied'],[]);self.assertEqual(self.file.read_bytes(),b);self.assertEqual((self.file.stat().st_ino,self.file.stat().st_mtime_ns),(s.st_ino,s.st_mtime_ns))
 def test_existing_admin_stop_is_not_reset(self):
  v={'allowed':True,'services':{'jupyter':{'enabled':False,'generation':9}}};self.file.write_text(json.dumps(v));b=self.file.read_bytes();r=self.runplan();self.assertEqual(r['preservedExistingJupyter'],[self.key]);self.assertEqual(self.file.read_bytes(),b)
 def test_changed_policy_is_refused(self):
  self.file.write_text(json.dumps({'allowed':True,'services':{}}));b=self.file.read_bytes()
  with self.assertRaisesRegex(ValueError,'changed'):self.runplan()
  self.assertEqual(self.file.read_bytes(),b);self.assertFalse(self.backup.exists())
 def test_unavailable_audit_prevents_changes(self):
  self.audit.mkdir();b=self.file.read_bytes()
  with self.assertRaises(OSError):self.runplan()
  self.assertEqual(self.file.read_bytes(),b)
 def test_full_service_limit_is_preserved(self):
  self.file.write_text(json.dumps({'allowed':True,'services':{str(i):{}for i in range(4)}}));self.plan[0]['sha256']=hashlib.sha256(self.file.read_bytes()).hexdigest()
  with self.assertRaisesRegex(ValueError,'limit'):self.runplan()
 def test_traversal_key_refused(self):
  self.plan[0]['key']='../outside'
  with self.assertRaises(ValueError):self.runplan()
if __name__=='__main__':unittest.main()
