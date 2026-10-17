import unittest,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rollout_harness_context_policy import policy_spec
class PolicyRolloutTests(unittest.TestCase):
 def setUp(self):
  self.old={'metadata':{'name':'dsh-u-8c6976e5b5410415-secure'},'spec':{'replicas':1,'strategy':{'type':'Recreate'},'template':{'spec':{'containers':[{'image':'pinned@sha256:abc','securityContext':{'runAsUser':10001},'volumeMounts':[{'name':'private','mountPath':'/workspace','subPath':'owner'}]}],'volumes':[{'name':'private','persistentVolumeClaim':{'claimName':'central'}}],'automountServiceAccountToken':False}}}}
 def test_adds_only_readonly_policy_without_mutating_original(self):
  before=copy.deepcopy(self.old);new=policy_spec(self.old,'policy');self.assertEqual(self.old,before)
  self.assertEqual(new['template']['spec']['volumes'][:-1],before['spec']['template']['spec']['volumes'])
  c=new['template']['spec']['containers'][0];self.assertEqual(c['volumeMounts'][:-2],before['spec']['template']['spec']['containers'][0]['volumeMounts']);self.assertTrue(all(m['readOnly'] for m in c['volumeMounts'][-2:]));self.assertEqual(c['image'],'pinned@sha256:abc');self.assertFalse(new['template']['spec']['automountServiceAccountToken'])
 def test_rejects_shared_writer_or_privileged_runtime(self):
  for k,v in [('replicas',2),('strategy',{'type':'RollingUpdate'})]:
   obj=copy.deepcopy(self.old);obj['spec'][k]=v
   with self.assertRaises(ValueError):policy_spec(obj,'p')
  self.old['spec']['template']['spec']['containers'][0]['securityContext']['runAsUser']=0
  with self.assertRaises(ValueError):policy_spec(self.old,'p')
 def test_rejects_legacy_and_conflicting_mount(self):
  old=copy.deepcopy(self.old);old['metadata']['name']='dsh3'
  with self.assertRaises(ValueError):policy_spec(old,'p')
  self.old['spec']['template']['spec']['containers'][0]['volumeMounts'].append({'name':'x','mountPath':'/etc/claude-code/managed-settings.json'})
  with self.assertRaises(ValueError):policy_spec(self.old,'p')
if __name__=='__main__':unittest.main()
