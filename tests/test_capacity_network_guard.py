from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from capacity_network_guard import guard,matches


class SharedIngressTests(unittest.TestCase):
    def policy(self,app,types):return {'spec':{'podSelector':{'matchLabels':{'app':app}},'policyTypes':types}}
    def workload(self,app):return {'metadata':{'name':app},'spec':{'template':{'metadata':{'labels':{'app':app}}}}}
    def test_cannot_add_first_ingress_policy_to_shared_proxy(self):
        with self.assertRaises(ValueError):guard([self.policy('proxy',['Ingress'])],[self.policy('proxy',['Egress'])],[self.workload('proxy')],set())
    def test_approved_rule_for_already_isolated_dns_preserves_existing_allow_union(self):
        self.assertTrue(guard([self.policy('dns',['Ingress'])],[self.policy('dns',['Ingress','Egress'])],[self.workload('dns')],set())['passed'])
    def test_only_exact_installer_owned_target_may_gain_new_boundary(self):
        self.assertTrue(guard([self.policy('qa',['Ingress'])],[],[self.workload('qa')],{'qa'})['passed'])
        with self.assertRaises(ValueError):guard([self.policy('proxy',['Ingress'])],[],[self.workload('proxy')],{'qa'})
    def test_egress_only_does_not_change_ingress(self):
        self.assertTrue(guard([self.policy('proxy',['Egress'])],[],[self.workload('proxy')],set())['passed'])
    def test_label_expression_selectors_are_evaluated(self):
        self.assertTrue(matches({'matchExpressions':[{'key':'app','operator':'In','values':['proxy']}]},{'app':'proxy'}))
        self.assertFalse(matches({'matchExpressions':[{'key':'app','operator':'NotIn','values':['proxy']}]},{'app':'proxy'}))
        self.assertTrue(matches({'matchExpressions':[{'key':'owner','operator':'Exists'}]},{'owner':'private'}))

if __name__=='__main__':unittest.main()
