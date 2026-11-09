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
 def test_nginx_aliases(self):
  obj=self.item('other','existing.other.internal');obj['metadata']['annotations']={'nginx.ingress.kubernetes.io/server-alias':'reserved.example.internal, second.example.internal'}
  result=reader.summarize([obj],'example.internal','llm','dsh-environment-gateway','dsh-user-app-wildcard');self.assertEqual(result['reservedNames'],['reserved','second'])
  obj['metadata']['annotations']['nginx.ingress.kubernetes.io/server-alias']='*.example.internal';self.assertTrue(reader.summarize([obj],'example.internal','llm','dsh-environment-gateway','dsh-user-app-wildcard')['wildcardConflict'])
 def test_competing_wildcard(self):
  r=reader.summarize([self.item('other','*.example.internal')],'example.internal','llm','dsh-environment-gateway','dsh-user-app-wildcard');self.assertTrue(r['wildcardConflict']);self.assertFalse(r['wildcardReady'])
 def test_wrong_backend(self):
  r=reader.summarize([self.item('dsh-user-app-wildcard','*.example.internal','direct-user-worker')],'example.internal','llm','dsh-environment-gateway','dsh-user-app-wildcard');self.assertFalse(r['wildcardReady'])
 def test_rbac_and_routing(self):
  s={'namespace':'llm','domain':'apps.example.internal','gatewayService':'dsh-environment-gateway','tlsSecret':'dsh-apps-tls','runtimeImage':'registry.example.internal/runtime@sha256:'+'a'*64,'apiCIDRs':['192.0.2.10/32'],'tlsMode':'dedicated'};docs=renderer.render(s)
  cluster=next(x for x in docs if x['kind']=='ClusterRole');self.assertEqual(cluster['rules'],[{'apiGroups':['networking.k8s.io'],'resources':['ingresses'],'verbs':['get','list']}])
  role=next(x for x in docs if x['kind']=='Role');self.assertEqual(role['rules'][0]['resourceNames'],['dsh-app-host-inventory']);self.assertEqual(role['rules'][0]['verbs'],['get','update'])
  deploy=next(x for x in docs if x['kind']=='Deployment');self.assertEqual(len(deploy['spec']['template']['spec']['volumes']),1);self.assertTrue(deploy['spec']['template']['spec']['containers'][0]['securityContext']['readOnlyRootFilesystem'])
  self.assertEqual(docs[-1]['kind'],'Ingress');self.assertEqual(docs[-1]['spec']['rules'][0]['host'],'*.apps.example.internal')
 def test_shared_controller_mode_has_no_global_wildcard_certificate_registration(self):
  s={'namespace':'llm','domain':'example.internal','gatewayService':'dsh-environment-gateway','tlsSecret':'dsh-apps-tls','runtimeImage':'registry.example.internal/runtime@sha256:'+'a'*64,'apiCIDRs':['192.0.2.10/32'],'tlsMode':'controller-default','controllerDefaultTls':{'namespace':'kube-system','secretName':'default-tls','certificateSha256':'b'*64}}
  route=renderer.render(s)[-1]
  self.assertNotIn('tls',route['spec'])
  self.assertEqual(route['spec']['rules'][0]['host'],'*.example.internal')
  self.assertEqual(route['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name'],'dsh-environment-gateway')
  self.assertEqual(route['metadata']['annotations']['nginx.ingress.kubernetes.io/force-ssl-redirect'],'true')
  del s['controllerDefaultTls']
  with self.assertRaises(ValueError):renderer.render(s)
 def test_dedicated_controller_mode_preserves_explicit_tls(self):
  s={'namespace':'llm','domain':'apps.example.internal','gatewayService':'dsh-environment-gateway','tlsSecret':'dsh-apps-tls','runtimeImage':'registry.example.internal/runtime@sha256:'+'a'*64,'apiCIDRs':['192.0.2.10/32'],'tlsMode':'dedicated'}
  route=renderer.render(s)[-1]
  self.assertEqual(route['spec']['tls'],[{'hosts':['*.apps.example.internal'],'secretName':'dsh-apps-tls'}])
 def test_unknown_tls_mode_fails_closed(self):
  s={'namespace':'llm','domain':'apps.example.internal','gatewayService':'dsh-environment-gateway','tlsSecret':'dsh-apps-tls','runtimeImage':'registry.example.internal/runtime@sha256:'+'a'*64,'apiCIDRs':['192.0.2.10/32'],'tlsMode':'guess'}
  with self.assertRaises(ValueError):renderer.render(s)
 def test_public_api_rejected(self):
  s={'namespace':'llm','domain':'apps.example.internal','gatewayService':'dsh-environment-gateway','tlsSecret':'dsh-apps-tls','runtimeImage':'registry.example.internal/runtime@sha256:'+'a'*64,'apiCIDRs':['8.8.8.8/32'],'tlsMode':'dedicated'}
  with self.assertRaises(ValueError):renderer.render(s)
if __name__=='__main__':unittest.main()
