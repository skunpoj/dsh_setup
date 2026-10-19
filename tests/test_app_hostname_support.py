import importlib.util,unittest
from pathlib import Path
R=Path(__file__).parents[1]
def module(name,file):
 s=importlib.util.spec_from_file_location(name,R/'scripts'/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
reader=module('inventory','app_host_inventory.py');renderer=module('host_render','render_app_hostname_support.py')
class HostSupport(unittest.TestCase):
 def item(self,name,host,service='dsh-environment-gateway'):
  return {'metadata':{'namespace':'llm','name':name},'spec':{'rules':[{'host':host,'http':{'paths':[{'backend':{'service':{'name':service,'port':{'number':3080}}}}]}}]}}
 def test_reservations(self):
  r=reader.summarize([self.item('existing','llm.example.internal'),self.item('dsh-user-app-wildcard','*.example.internal')],'example.internal','llm','dsh-environment-gateway','dsh-user-app-wildcard');self.assertEqual(r['reservedNames'],['llm']);self.assertTrue(r['wildcardReady'])
 def test_competing_wildcard(self):
  r=reader.summarize([self.item('other','*.example.internal')],'example.internal','llm','dsh-environment-gateway','dsh-user-app-wildcard');self.assertTrue(r['wildcardConflict']);self.assertFalse(r['wildcardReady'])
 def test_wrong_backend(self):
  r=reader.summarize([self.item('dsh-user-app-wildcard','*.example.internal','direct-user-worker')],'example.internal','llm','dsh-environment-gateway','dsh-user-app-wildcard');self.assertFalse(r['wildcardReady'])
 def test_rbac_and_routing(self):
  s={'namespace':'llm','domain':'apps.example.internal','gatewayService':'dsh-environment-gateway','tlsSecret':'dsh-apps-tls','runtimeImage':'registry.example.internal/runtime@sha256:'+'a'*64,'apiCIDRs':['192.0.2.10/32']};docs=renderer.render(s)
  cluster=next(x for x in docs if x['kind']=='ClusterRole');self.assertEqual(cluster['rules'],[{'apiGroups':['networking.k8s.io'],'resources':['ingresses'],'verbs':['get','list']}])
  role=next(x for x in docs if x['kind']=='Role');self.assertEqual(role['rules'][0]['resourceNames'],['dsh-app-host-inventory']);self.assertEqual(role['rules'][0]['verbs'],['get','update'])
  deploy=next(x for x in docs if x['kind']=='Deployment');self.assertEqual(len(deploy['spec']['template']['spec']['volumes']),1);self.assertTrue(deploy['spec']['template']['spec']['containers'][0]['securityContext']['readOnlyRootFilesystem'])
  self.assertEqual(docs[-1]['kind'],'Ingress');self.assertEqual(docs[-1]['spec']['rules'][0]['host'],'*.apps.example.internal')
 def test_public_api_rejected(self):
  s={'namespace':'llm','domain':'apps.example.internal','gatewayService':'dsh-environment-gateway','tlsSecret':'dsh-apps-tls','runtimeImage':'registry.example.internal/runtime@sha256:'+'a'*64,'apiCIDRs':['8.8.8.8/32']}
  with self.assertRaises(ValueError):renderer.render(s)
if __name__=='__main__':unittest.main()
