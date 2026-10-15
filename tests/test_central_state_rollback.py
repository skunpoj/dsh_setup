import importlib.util,json,sys,tempfile,unittest,ast
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('state_restore',Path(__file__).resolve().parents[1]/'scripts/restore_central_state.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RollbackTest(unittest.TestCase):
 def test_worker_failure_restores_exact_original_and_retains_volumes(self):
  original={'spec':{'replicas':1,'template':{'spec':{'containers':[{'image':'registry/image@sha256:'+'a'*64,'volumeMounts':[{'name':'state','mountPath':'/state'}]}],'volumes':[{'name':'state','persistentVolumeClaim':{'claimName':'state'}},{'name':'protected-workspace','persistentVolumeClaim':{'claimName':'central'}}]}}}}
  calls=[];payloads=[]
  def kube(*args,**kwargs):
   calls.append(args)
   if kwargs.get("data"):payloads.append(json.loads(kwargs["data"]))
   if args[:2]==('get','deploy'):return json.dumps(original)
   if args[:2]==('get','pods'):return '{"items":[]}'
   if args[:2]==('get','job'):return '{"status":{"failed":1}}'
   return ''
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d)/'fresh'
   with patch.object(sys,'argv',['restore','--rollback-dir',str(folder),'--probe','/auth/test.js']),patch.object(m,'k',kube),patch.object(m,'ready'):
    with self.assertRaisesRegex(RuntimeError,'preparation failed'):m.main()
   self.assertEqual(json.loads((folder/'before.json').read_text()),original)
  config=next(p for p in payloads if p['kind']=='ConfigMap');self.assertIn('reconcile_workspace.py',config['data'])
  job=next(p for p in payloads if p['kind']=='Job');code=job['spec']['template']['spec']['containers'][0]['command'][-1];ast.parse(code)
  self.assertLess(code.index('workspace_result=reconcile'),code.index('os.rename(old,'))
  patches=[c for c in calls if c[0]=='patch'];self.assertEqual(len(patches),1);self.assertEqual(json.loads(patches[0][-1]),original)
  self.assertFalse(any(c[:2]==('delete','pvc') for c in calls))
if __name__=='__main__':unittest.main()
