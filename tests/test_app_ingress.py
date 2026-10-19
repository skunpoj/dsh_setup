import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('planner',Path(__file__).parents[1]/'scripts/plan_app_ingress.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class IngressNames(unittest.TestCase):
 def check(self,items,name=None):return m.plan('alice',name,'apps.example.internal','llm','dsh-environment-gateway','app-tls',{'items':items})
 def entry(self,host):return {'metadata':{'namespace':'other','name':'occupied'},'spec':{'rules':[{'host':host}]}}
 def test_default(self):
  r,d=self.check([]);self.assertEqual(r['hostname'],'alice-jupyter.apps.example.internal');self.assertTrue(r['availableInObservedIngressInventory']);self.assertEqual(d['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name'],'dsh-environment-gateway')
 def test_collision(self):self.assertFalse(self.check([self.entry('alice-jupyter.apps.example.internal')])[0]['availableInObservedIngressInventory'])
 def test_wildcard(self):self.assertFalse(self.check([self.entry('*.apps.example.internal')])[0]['availableInObservedIngressInventory'])
 def test_unrelated(self):self.assertTrue(self.check([self.entry('*.example.internal')])[0]['availableInObservedIngressInventory'])
 def test_invalid(self):
  with self.assertRaises(ValueError):self.check([],name='http://evil')
if __name__=='__main__':unittest.main()
