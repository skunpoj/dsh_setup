import copy
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from scripts.openshell_kubernetes_observer import NativeKubernetesObserver
from tests import test_openshell_kubernetes_identity as identity_cases


class NativeObserverTests(unittest.TestCase):
    def setUp(self):
        fixture=identity_cases.NativeIdentityTests();fixture.setUp();self.f=fixture
        self.task=SimpleNamespace(request={'backend':'openshell'},openshell=dict(fixture.context),save=Mock())
        self.registry=Mock();self.registry.get.return_value=self.task
        self.api=Mock()
        self.api.list_sandboxes.return_value={'metadata':{'resourceVersion':'20'},'items':[fixture.sandbox]}
        self.api.list_pods.return_value={'metadata':{'resourceVersion':'21'},'items':[fixture.workload,fixture.supervisor]}
        self.observer=NativeKubernetesObserver(self.registry,self.api,fixture.verifier,
            api_version='agents.x-k8s.io/v1beta1')

    def test_exact_observation_is_persisted_in_existing_task_only(self):
        receipt=self.observer.observe_exact(self.f.context)
        self.assertEqual(receipt,{**self.f.context,'podUID':'worker-uid'})
        self.task.save.assert_called_once()
        self.assertEqual(self.task.openshell['nativeResources']['supervisorPodUID'],'supervisor-uid')
        self.assertEqual(self.api.method_calls[0].args[0],self.f.namespace)

    def test_foreign_context_cannot_query_cluster(self):
        with self.assertRaisesRegex(ValueError,'TASK_BINDING'):
            self.observer.observe_exact({**self.f.context,'subject':'bob'})
        self.api.list_sandboxes.assert_not_called()

    def test_selector_injection_cannot_query_cluster(self):
        with self.assertRaisesRegex(ValueError,'SELECTOR_IDENTITY'):
            self.observer.observe_exact({**self.f.context,'workerUID':'native-1,foreign=true'})
        self.api.list_sandboxes.assert_not_called()

    def test_partial_paginated_list_is_not_accepted(self):
        self.api.list_pods.return_value['metadata']['continue']='next-page'
        with self.assertRaisesRegex(ValueError,'LIST_INCOMPLETE'):self.observer.observe_exact(self.f.context)
        self.task.save.assert_not_called()

    def test_unversioned_list_or_python_pagination_alias_refuses(self):
        for metadata in [{},{'resourceVersion':'21','_continue':'next-page'}]:
            self.api.list_pods.return_value['metadata']=metadata
            with self.subTest(metadata=metadata),self.assertRaisesRegex(ValueError,'LIST_INCOMPLETE'):
                self.observer.observe_exact(self.f.context)
        self.task.save.assert_not_called()

    def test_ambiguous_pair_is_not_accepted(self):
        self.api.list_pods.return_value['items'].append(copy.deepcopy(self.f.workload))
        with self.assertRaisesRegex(ValueError,'PAIR_NOT_UNIQUE'):self.observer.observe_exact(self.f.context)
        self.task.save.assert_not_called()

    def test_api_failure_is_not_absence(self):
        self.api.list_sandboxes.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):self.observer.observe_exact(self.f.context)
        self.task.save.assert_not_called()

    def test_returned_api_version_must_match_admitted_route(self):
        self.f.sandbox['apiVersion']='agents.x-k8s.io/v1alpha1'
        with self.assertRaisesRegex(ValueError,'API_VERSION_MISMATCH'):
            self.observer.observe_exact(self.f.context)
        self.task.save.assert_not_called()

    def test_revalidation_never_follows_replaced_worker(self):
        self.observer.observe_exact(self.f.context)
        self.task.save.reset_mock();self.f.workload['metadata']['uid']='replacement'
        with self.assertRaisesRegex(ValueError,'RESOURCE_REPLACED'):
            self.observer.revalidate(self.f.context,require_running=True)
        self.task.save.assert_not_called()


if __name__=='__main__':unittest.main()
