import copy,importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('bootstrap',Path(__file__).parents[1]/'scripts/render_managed_signin_bootstrap.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Bootstrap(unittest.TestCase):
 def template(self):return {'templates':{mode:{'spec':{'template':{'spec':{'containers':[{'name':'dsh','command':['original-start'],'args':['--keep'],'env':[{'name':'KEEP','value':'yes'}],'volumeMounts':[{'name':'state','mountPath':'/state'}]}],'volumes':[{'name':'state','emptyDir':{}}]}}}}for mode in ['secure','internet']},'claims':{'retained':True}}
 def test_only_future_startup_changes(self):
  before=self.template();next=m.configure(before,'managed-signin-source');self.assertEqual(before,self.template());self.assertEqual(next['claims'],before['claims'])
  for mode in before['templates']:
   old=before['templates'][mode]['spec']['template']['spec'];new=next['templates'][mode]['spec']['template']['spec'];c=new['containers'][0]
   self.assertEqual(c['env'],old['containers'][0]['env']);self.assertEqual(c['command'][-2:],['original-start','--keep']);self.assertNotIn('args',c);self.assertTrue(c['volumeMounts'][-1]['readOnly']);self.assertEqual(new['volumes'][:-1],old['volumes'])
 def test_refuse_ambiguous_bootstrap(self):
  p=m.configure(self.template(),'managed-signin-source')
  with self.assertRaises(ValueError):m.configure(p,'other')
  with self.assertRaises(ValueError):m.configure(self.template(),'../../bad')
if __name__=='__main__':unittest.main()
