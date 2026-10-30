import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from capacity_report import capacity_report
from capacity_worker import effective_request

class CapacityReportTests(unittest.TestCase):
    def setUp(self):
        self.inputs={'additionalDeploymentsComplete':True,'additionalDeployments':[{'label':'DSH2','accounts':1},{'label':'DSH3','accounts':1}],
          'resources':{k:{'available':a,'reserve':s,'pairBudget':p}for k,a,s,p in [('cpu',5,2,.6),('memoryGiB',100,32,2.25),('pods',40,10,2),('storageGiB',200,32,23)]}}
        self.assignments={'registeredAccounts':12,'assignedSlots':['used']}
        self.inventory={'slots':{'used':{'state':'ready'},'spare1':{'state':'ready'},'spare2':{'state':'ready'},'old':{'state':'retired'}}}
    def test_counts_ready_once_and_includes_additional_accounts(self):
        v=capacity_report(self.inputs,self.assignments,self.inventory)
        self.assertEqual((v['additionalPairsPossible'],v['mainPlanningCeiling'],v['totalRegistered'],v['totalPlanningCeiling']),(5,19,14,21))
        self.assertEqual(v['limitingResources'],['cpu']);self.assertFalse(v['inferenceCapacityIncluded'])
    def test_pressure_does_not_remove_existing_users(self):
        self.inputs['resources']['cpu']['available']=0
        v=capacity_report(self.inputs,self.assignments,self.inventory)
        self.assertEqual(v['additionalPairsPossible'],0);self.assertEqual(v['mainRegistered'],12)
    def test_unknown_additional_deployments_is_not_zero(self):
        self.inputs['additionalDeploymentsComplete']=False
        v=capacity_report(self.inputs,self.assignments,self.inventory)
        self.assertIsNone(v['totalRegistered']);self.assertIsNone(v['mainPlanningCeiling'])
    def test_retired_inventory_does_not_block_new_pairs(self):
        self.inventory['slots'].update({str(i):{'state':'retired'}for i in range(28)})
        v=capacity_report(self.inputs,self.assignments,self.inventory)
        self.assertEqual(v['additionalPairsPossible'],5);self.assertNotIn('inventory',v['limitingResources'])
    def test_nonfinite_or_negative_measurements_refused(self):
        for x in [float('nan'),float('inf'),-1,True]:
            bad=copy.deepcopy(self.inputs);bad['resources']['cpu']['available']=x
            with self.assertRaises(ValueError):capacity_report(bad,self.assignments,self.inventory)
    def test_restartable_init_sidecars_are_counted(self):
        pod={'spec':{'containers':[{'resources':{'requests':{'cpu':'250m'}}}],
          'initContainers':[{'restartPolicy':'Always','resources':{'requests':{'cpu':'500m'}}},{'resources':{'requests':{'cpu':'1'}}}],
          'overhead':{'cpu':'50m'}}}
        self.assertAlmostEqual(effective_request(pod,'cpu'),1.55)
if __name__=='__main__':unittest.main()
