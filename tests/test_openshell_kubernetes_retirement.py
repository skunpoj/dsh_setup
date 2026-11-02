import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from scripts.openshell_kubernetes_retirement import NativeKubernetesRetirement
from tests import test_openshell_kubernetes_identity as identity_cases


class RetirementTests(unittest.TestCase):
    def setUp(self):
        f=identity_cases.NativeIdentityTests();f.setUp();self.f=f
        self.operation='e'*32;self.assigned={**f.context,'podUID':'worker-uid'}
        identity=f.verify()['identity']
        self.task=SimpleNamespace(request={'backend':'openshell'},save=Mock(),openshell={
            **self.assigned,'phase':'stop-reserved','stopOperationId':self.operation,
            'fenced':True,'revoked':True,'nativeResources':identity})
        self.registry=Mock();self.registry.get.return_value=self.task
        self.objects={('Sandbox','native-workload'):copy.deepcopy(f.sandbox),
            ('Pod','worker-pod'):copy.deepcopy(f.workload),('Pod','os-supervisor-native-1'):copy.deepcopy(f.supervisor)}
        self.api=Mock(namespace=f.namespace)
        self.api.read_resource.side_effect=lambda ns,k,v,n:copy.deepcopy(self.objects.get((k,n)))
        def delete(ns,k,v,n,*,uid,resource_version):
            value=self.objects[(k,n)]
            if value['metadata']['uid']!=uid or value['metadata']['resourceVersion']!=resource_version:
                raise ValueError('CONFLICT')
            self.objects.pop((k,n))
            return {'uid':uid,'resourceVersion':resource_version,'deleteAccepted':True}
        self.api.delete_exact.side_effect=delete
        self.api.list_pods.return_value={'items':[],'metadata':{'resourceVersion':'21'}}
        self.api.list_sandboxes.return_value={'items':[],'metadata':{'resourceVersion':'22'}}
        self.retirement=NativeKubernetesRetirement(self.registry,self.api,namespace=f.namespace)

    def retire(self):return self.retirement.retire_exact(self.assigned,self.operation)

    def test_exact_cleanup_uses_saved_identity_and_does_not_claim_process_exit(self):
        result=self.retire()
        self.assertTrue(result['resourcesAbsent']);self.assertFalse(result['processExitVerified'])
        self.assertNotIn('stopped',result)
        self.assertEqual([c.args[1] for c in self.api.delete_exact.call_args_list],['Sandbox','Pod','Pod'])
        self.assertEqual([c.kwargs['uid'] for c in self.api.delete_exact.call_args_list],
                         ['sandbox-uid','worker-uid','supervisor-uid'])
        self.assertTrue(all(v['phase']=='accepted' for v in self.task.openshell['nativeDeleteOperations'].values()))
        self.assertTrue(all('prompt' not in v for v in self.task.openshell['nativeDeleteOperations'].values()))

    def test_already_absent_resources_require_no_mutation(self):
        self.objects.clear();self.assertTrue(self.retire()['resourcesAbsent'])
        self.api.delete_exact.assert_not_called()

    def test_replaced_sibling_detected_before_any_delete(self):
        self.objects[('Pod','os-supervisor-native-1')]['metadata']['uid']='replacement'
        with self.assertRaisesRegex(ValueError,'RESOURCE_REPLACED'):self.retire()
        self.api.delete_exact.assert_not_called()

    def test_replacement_after_snapshot_hits_api_preconditions(self):
        self.api.delete_exact.side_effect=ValueError('CONFLICT')
        with self.assertRaisesRegex(ValueError,'CONFLICT'):self.retire()
        self.assertEqual(self.api.delete_exact.call_count,1)
        with self.assertRaisesRegex(ValueError,'NO_RETRY'):self.retire()
        self.assertEqual(self.api.delete_exact.call_count,1)

    def test_timeout_retains_reservation_and_cannot_resubmit(self):
        self.api.delete_exact.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.retire()
        self.assertEqual(self.task.openshell['nativeDeleteOperations']['Sandbox/sandbox-uid']['phase'],'reserved')
        with self.assertRaisesRegex(ValueError,'NO_RETRY'):self.retire()
        self.assertEqual(self.api.delete_exact.call_count,1)

    def test_accepted_but_pending_delete_is_not_absence_or_retried(self):
        self.api.delete_exact.side_effect=lambda *a,**k:{'uid':k['uid'],'resourceVersion':k['resource_version'],'deleteAccepted':True}
        with self.assertRaisesRegex(ValueError,'STILL_PRESENT'):self.retire()
        self.assertEqual(self.api.delete_exact.call_count,3)
        with self.assertRaisesRegex(ValueError,'NO_RETRY'):self.retire()
        self.assertEqual(self.api.delete_exact.call_count,3)

    def test_readback_can_resolve_uncertainty_without_another_delete(self):
        self.api.delete_exact.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.retire()
        self.objects.clear()
        result=self.retirement.verify_resources_absent(self.assigned,self.operation)
        self.assertTrue(result['resourcesAbsent']);self.assertEqual(self.api.delete_exact.call_count,1)

    def test_foreign_binding_or_unfenced_state_never_queries_cluster(self):
        with self.assertRaisesRegex(ValueError,'UNRESERVED'):
            self.retirement.retire_exact({**self.assigned,'subject':'bob'},self.operation)
        self.task.openshell['fenced']=False
        with self.assertRaisesRegex(ValueError,'UNRESERVED'):self.retire()
        self.api.read_resource.assert_not_called();self.api.delete_exact.assert_not_called()

    def test_incomplete_list_reappearance_and_api_failure_are_not_absence(self):
        self.objects.clear()
        self.api.list_pods.return_value={'items':[],'metadata':{'resourceVersion':'21','continue':'next'}}
        with self.assertRaisesRegex(ValueError,'LIST_INCOMPLETE'):self.retire()
        self.api.list_pods.return_value={'items':[self.f.workload],'metadata':{'resourceVersion':'21'}}
        with self.assertRaisesRegex(ValueError,'REAPPEARED'):self.retire()
        self.api.list_pods.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.retire()
        self.api.delete_exact.assert_not_called()


if __name__=='__main__':unittest.main()
