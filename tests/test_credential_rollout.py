import ast,unittest
from pathlib import Path
class RoutingRegression(unittest.TestCase):
 def test_policy_retains_browser_and_worker_boundaries(self):
  tree=ast.parse(Path('scripts/rollout_credential_gateway.py').read_text())
  calls=[n for n in ast.walk(tree)if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)and n.func.id=='apply']
  policies=[]
  for call in calls:
   try:policies.append(eval(compile(ast.Expression(call.args[0]),'<policy>','eval'),{}, {'name':'gateway','workers':{'matchLabels':{'worker':'true'}}}))
   except (NameError,TypeError,ValueError):pass
  p=next(p for p in policies if p['metadata']['name']=='dsh-credential-tools-ingress')
  rules=p['spec']['ingress'];self.assertEqual(len(rules),2)
  self.assertEqual(rules[0]['ports'],[{'port':3443,'protocol':'TCP'}])
  web=rules[1];self.assertEqual(web['ports'],[{'port':3080,'protocol':'TCP'}]);self.assertEqual(len(web['from']),1)
  peer=web['from'][0];self.assertEqual(peer['namespaceSelector']['matchLabels']['kubernetes.io/metadata.name'],'kube-system');self.assertEqual(peer['podSelector']['matchLabels'],{'app.kubernetes.io/name':'rke2-ingress-nginx','app.kubernetes.io/component':'controller'})
 def test_external_route_checked_on_success_and_rollback(self):
  s=Path('scripts/rollout_credential_gateway.py').read_text();self.assertGreaterEqual(s.count('external_login(trusted)'),3);self.assertIn("https://'+host+'/login",s)
if __name__=='__main__':unittest.main()
