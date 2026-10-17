import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rollout_shared_inference_boundary import policies,normalized_policy_spec,validate_shared_singleton,validate_authoritative_cluster_zone
class SharedBoundaryTests(unittest.TestCase):
 def test_private_dns_zone_cannot_fall_through_to_public_dns(self):
  validate_authoritative_cluster_zone('kubernetes cluster.local {\n fallthrough in-addr.arpa ip6.arpa\n}')
  for c in ['forward . 1.1.1.1','kubernetes cluster.local {\n fallthrough\n}','kubernetes cluster.local {\n fallthrough cluster.local\n}','rewrite name cluster.local example.com\nkubernetes cluster.local {}']:
   with self.assertRaises(ValueError):validate_authoritative_cluster_zone(c)
 def test_local_admission_lock_cannot_silently_be_scaled_out(self):
  validate_shared_singleton({'replicas':1,'strategy':{'type':'Recreate'}})
  for x in [{'replicas':2,'strategy':{'type':'Recreate'}},{'replicas':1,'strategy':{'type':'RollingUpdate'}}]:
   with self.assertRaises(ValueError):validate_shared_singleton(x)
 def test_omitted_empty_rules_normalize_but_changed_egress_does_not(self):
  a={'podSelector':{},'policyTypes':['Egress']};b={**a,'egress':[]};self.assertEqual(normalized_policy_spec(a),normalized_policy_spec(b));self.assertNotEqual(normalized_policy_spec(a),normalized_policy_spec({**a,'egress':[{}]}))
 def test_model_providers_have_no_egress_and_inference_is_bounded(self):
  p=policies('10.43.10.10');self.assertEqual(len(p),5);self.assertEqual(p[2]['spec']['egress'],[]);self.assertEqual(p[3]['spec']['egress'],[]);self.assertEqual(p[4]['spec']['egress'],[])
  self.assertEqual(p[3]['metadata']['namespace'],'ollama');self.assertEqual(p[1]['spec']['podSelector'],{'matchLabels':{'app':'litellm'}})
  ports={x['port']for r in p[1]['spec']['egress']for x in r['ports']};self.assertEqual(ports,{53,5353,5432,8000,11434})
 def test_dns_does_not_allow_a_public_resolver_or_core_dns_directly(self):
  for value in ['8.8.8.8','1.1.1.1','127.0.0.1','invalid']:
   with self.assertRaises(ValueError):policies(value)
  r=policies('10.43.10.10')[1]['spec']['egress'][0];self.assertEqual(r['to'][0]['podSelector']['matchLabels']['app'],'dsh-internal-dns');self.assertEqual(r['to'][1]['ipBlock']['cidr'],'10.43.10.10/32')
 def test_gateway_targets_runtime_scopes_not_all_internal_addresses(self):
  p=policies('10.43.10.10')[0]['spec'];self.assertEqual(p['podSelector']['matchLabels']['app'],'dsh-environment-gateway');r=p['egress'][1]
  self.assertTrue(all('podSelector'in peer for peer in r['to']));self.assertFalse(any('ipBlock'in peer for peer in r['to']))
if __name__=='__main__':unittest.main()
