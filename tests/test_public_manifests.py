import copy
import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('renderer',ROOT/'scripts/render_k8s.py');renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(renderer)

def config():
 c=yaml.safe_load((ROOT/'config.example.yaml').read_text())
 c.update(namespace='ai-test',storage_class='test-rwo',shared_storage_class='test-rwx',public_hostname='workspace.example.com',dsh_image='registry.example.com/runtime@sha256:'+'a'*64,cluster_dns_ip='192.0.2.53',filtered_dns_ip='192.0.2.54')
 return c

class PublicDeploymentTests(unittest.TestCase):
 def test_placeholder_config_refused(self):
  with self.assertRaises(ValueError):renderer.build(yaml.safe_load((ROOT/'config.example.yaml').read_text()))
 def test_full_stack_and_secret_boundaries(self):
  docs=renderer.build(config());self.assertFalse(any(x['kind']=='Secret' for x in docs))
  deps={x['metadata']['name']:x for x in docs if x['kind']=='Deployment'}
  self.assertTrue({'model','litellm','database','gateway','filtered-dns'}.issubset(deps));self.assertEqual(len(deps),9)
  model=deps['model']['spec']['template']['spec']['containers'][0];args=model['args']
  for name,value in [('--context-length','1048576'),('--chunked-prefill-size','1024'),('--max-running-requests','16')]:self.assertEqual(args[args.index(name)+1],value)
  self.assertEqual(model['resources']['limits']['nvidia.com/gpu'],4)
  self.assertNotIn('hostPath',str(docs));self.assertNotIn('NodePort',str(docs))
  for d in deps.values():self.assertFalse(d['spec']['template']['spec']['automountServiceAccountToken'])
  forward=next(c for c in deps['litellm']['spec']['template']['spec']['containers'] if c['name']=='context-forwarder')
  self.assertEqual(forward['command'][forward['command'].index('--host')+1],'127.0.0.1')
  clients=[d for n,d in deps.items() if n.startswith('user-')]
  claims=[]
  for d in clients:
   pod=d['spec']['template']['spec'];worker=pod['containers'][0];self.assertEqual(worker['securityContext']['runAsUser'],10001)
   self.assertFalse(any(v['name']=='auth' for v in pod['volumes']))
   claims.extend(v['persistentVolumeClaim']['claimName'] for v in pod['volumes'] if v['name'] in ['state','workspace'])
  self.assertEqual(len(claims),len(set(claims)))
  services={x['metadata']['name']:x['spec'] for x in docs if x['kind']=='Service'}
  for name in deps:
   if name.startswith('user-'):self.assertEqual({v['port'] for v in services[name]['ports']},{3081,7681,3000})
 def test_no_internet_and_backend_isolation(self):
  policies={x['metadata']['name']:x['spec'] for x in renderer.build(config()) if x['kind']=='NetworkPolicy'}
  self.assertEqual(policies['model']['egress'],[])
  self.assertEqual(policies['gateway']['ingress'][0]['ports'],[{'protocol':'TCP','port':3080}])
  self.assertNotIn('0.0.0.0/0',str(policies['runtime-secure']))
  self.assertIn('0.0.0.0/0',str(policies['runtime-internet']))
  self.assertEqual(policies['filtered-dns']['egress'][0]['ports'][0]['port'],53)

if __name__=='__main__':unittest.main()
