import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('capacity_planner',Path(__file__).parents[1]/'scripts/capacity_planner.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from datetime import datetime, timezone, timedelta


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.policy={'version':1,'enabled':True,'maxAccounts':16,'warmSpareSlots':2}
        self.assignments={'observedAt':self.now.isoformat(),'registeredAccounts':9,'assignedSlots':['owned']}
        self.inventory={'slots':{'owned':{'state':'ready'},'spare':{'state':'ready'}}}
        self.resources={k:1 for k in ['cpuAfterPair','memoryGiBAfterPair','podsAfterPair','storageGiBAfterPair']}

    def call(self):return module.plan(self.policy,self.assignments,self.inventory,self.resources,self.now)
    def test_replenishes_one_and_preserves_owned(self):
        r=self.call();self.assertEqual(r['action'],'provision');self.assertEqual(r['count'],1);self.assertEqual(r['existingSlotsToDelete'],[])
    def test_two_spares_stops_and_does_not_shrink_excess(self):
        for n in range(3):self.inventory['slots'][str(n)]={'state':'ready'}
        self.assertEqual(self.call()['action'],'wait');self.assertEqual(self.call()['existingSlotsToDelete'],[])
    def test_stale_or_future_assignments_stop(self):
        for seconds in [-61,10]:
            self.assignments['observedAt']=(self.now+timedelta(seconds=seconds)).isoformat()
            self.assertEqual(self.call()['reason'],'assignment-state-stale')
    def test_capacity_cap_and_disabled(self):
        self.policy['maxAccounts']=9;self.assertEqual(self.call()['desiredSpares'],0)
        self.policy['enabled']=False;self.assertEqual(self.call()['action'],'wait')
    def test_unknown_or_exhausted_resource_denies(self):
        for k in self.resources:
            original=self.resources[k];self.resources[k]=-1;self.assertEqual(self.call()['action'],'wait');self.resources[k]=original
        self.resources={};self.assertEqual(self.call()['action'],'wait')

    def test_nonfinite_resource_denies_without_removing_existing_slots(self):
        for key in self.resources:
            original = self.resources[key]
            for value in [float('nan'), float('inf'), -float('inf'), True]:
                with self.subTest(resource=key, value=value):
                    self.resources[key] = value
                    actual = self.call()
                    self.assertEqual(actual['action'], 'wait')
                    self.assertEqual(actual['reason'], 'insufficient-or-unknown-' + key)
                    self.assertEqual(actual['existingSlotsToDelete'], [])
                    self.assertEqual(set(self.inventory['slots']), {'owned', 'spare'})
            self.resources[key] = original
    def test_pending_resumes_without_duplicate_pair(self):
        self.inventory['slots']['pending']={'state':'qualifying'};self.assertEqual(self.call()['action'],'resume')
    def test_assigned_slot_cannot_be_removed(self):
        del self.inventory['slots']['owned']
        with self.assertRaises(ValueError):self.call()
    def test_strict_policy_bounds(self):
        for p in [{'maxAccounts':True},{'maxAccounts':100001},{'warmSpareSlots':9},{'enabled':1}]:
            old=self.policy.copy();self.policy.update(p)
            with self.assertRaises(ValueError):self.call()
            self.policy=old

    def test_retired_slots_do_not_count_against_inventory(self):
        self.inventory['slots'].update({'old'+str(i):{'state':'retired'}for i in range(250)})
        self.assertEqual(self.call()['action'],'provision')
    def test_large_account_limit_is_valid(self):
        self.policy['maxAccounts']=100000;self.assertEqual(self.call()['desiredSpares'],2)

if __name__=='__main__':unittest.main()
