import unittest
from unittest.mock import Mock
from scripts.openshell_kubernetes_api import NativeKubernetesAPI


class NativeAPITests(unittest.TestCase):
    def setUp(self):
        self.ns='dsh-openshell-test-20261028';self.request=Mock(return_value=(200,{}))
        self.api=NativeKubernetesAPI(self.request,namespace=self.ns)

    def test_delete_has_actual_uid_and_version_preconditions_without_force(self):
        self.api.delete_exact(self.ns,'Pod','v1','worker-pod',uid='uid-original',resource_version='123')
        method,path,body=self.request.call_args.args
        self.assertEqual(method,'DELETE')
        self.assertEqual(path,'/api/v1/namespaces/'+self.ns+'/pods/worker-pod')
        self.assertEqual(body,{'apiVersion':'v1','kind':'DeleteOptions','propagationPolicy':'Foreground',
                               'preconditions':{'uid':'uid-original','resourceVersion':'123'}})

    def test_foreign_namespace_resource_or_path_cannot_be_requested(self):
        for ns,kind,version,name in [('other','Pod','v1','worker'),(self.ns,'Secret','v1','worker'),
            (self.ns,'Pod','v1','../foreign'),(self.ns,'Sandbox','evil/v1','worker')]:
            with self.subTest(kind=kind,name=name),self.assertRaises(ValueError):
                self.api.read_resource(ns,kind,version,name)
        self.request.assert_not_called()

    def test_delete_conflict_or_timeout_is_not_retried(self):
        self.request.return_value=(409,{'reason':'Conflict'})
        with self.assertRaisesRegex(ValueError,'NOT_ACCEPTED'):
            self.api.delete_exact(self.ns,'Pod','v1','worker',uid='uid',resource_version='123')
        self.assertEqual(self.request.call_count,1)
        self.request.reset_mock();self.request.side_effect=TimeoutError
        with self.assertRaises(TimeoutError):
            self.api.delete_exact(self.ns,'Pod','v1','worker',uid='uid',resource_version='123')
        self.assertEqual(self.request.call_count,1)

    def test_only_real_404_is_absence(self):
        self.request.return_value=(404,{'reason':'NotFound'})
        self.assertIsNone(self.api.read_resource(self.ns,'Pod','v1','worker'))
        for status in (401,403,429,500,503):
            self.request.return_value=(status,{})
            with self.subTest(status=status),self.assertRaisesRegex(ValueError,'READ_FAILED'):
                self.api.read_resource(self.ns,'Pod','v1','worker')

    def test_native_list_query_is_encoded_without_watch_or_cache_version(self):
        self.request.return_value=(200,{'items':[],'metadata':{'resourceVersion':'1'}})
        self.api.list_sandboxes(self.ns,'agents.x-k8s.io/v1beta1','openshell.ai/sandbox-id=native-1')
        self.assertEqual(self.request.call_args.args,('GET','/apis/agents.x-k8s.io/v1beta1/namespaces/'+self.ns+
            '/sandboxes?labelSelector=openshell.ai%2Fsandbox-id%3Dnative-1',None))


if __name__=='__main__':unittest.main()
