"""REST contract tests with synthetic responses, never runtime acceptance."""
import json
import ssl
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_worker_api import WorkerAPI


NS_UID='11111111-1111-4111-8111-111111111111'
POD_UID='22222222-2222-4222-8222-222222222222'


class WorkerAPITests(TestCase):
    def namespace(self):
        return dict(kind='Namespace',apiVersion='v1',metadata=dict(name='dsh-a2a-qual',uid=NS_UID,
            resourceVersion='1',labels={'dsh.example.com/runtime-environment':'test',
                                       'dsh.example.com/runtime-purpose':'qualification'}))

    def pod(self):
        return dict(kind='Pod',apiVersion='v1',metadata=dict(name='a2a-'+'a'*32,
            namespace='dsh-a2a-qual',uid=POD_UID,resourceVersion='2'))

    def api(self,responses):
        self.connections=[]
        def factory(*args,**kwargs):
            status,value=responses.pop(0)
            connection=Mock();response=connection.getresponse.return_value
            response.status=status;response.read.return_value=json.dumps(value).encode()
            self.connections.append(connection);return connection
        return WorkerAPI(origin='https://kubernetes.invalid:6443',tls_context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            authorization=lambda:'Bearer synthetic-not-a-real-token',namespace='dsh-a2a-qual',
            namespace_uid=NS_UID,connection_factory=factory)

    def test_exact_named_reads_recheck_namespace_uid_around_actual_response(self):
        api=self.api([(200,self.namespace()),(200,self.pod()),(200,self.namespace())])
        self.assertEqual(api.read_pod('a2a-'+'a'*32)['metadata']['uid'],POD_UID)
        self.assertEqual([c.request.call_args.args[:2] for c in self.connections],
            [('GET','/api/v1/namespaces/dsh-a2a-qual'),
             ('GET','/api/v1/namespaces/dsh-a2a-qual/pods/a2a-'+'a'*32),
             ('GET','/api/v1/namespaces/dsh-a2a-qual')])
        self.assertTrue(all(c.close.call_count==1 for c in self.connections))

    def test_namespace_replacement_invalidates_even_a_not_found_response(self):
        replacement=self.namespace();replacement['metadata']['uid']=POD_UID
        api=self.api([(200,self.namespace()),(404,dict(kind='Status',reason='NotFound')),(200,replacement)])
        with self.assertRaisesRegex(ValueError,'NAMESPACE_IDENTITY'):
            api.read_pod('a2a-'+'a'*32)

    def test_no_secrets_routes_redirects_or_insecure_tls(self):
        api=self.api([])
        with self.assertRaisesRegex(ValueError,'ROUTE_REFUSED'):
            api._request('GET','/api/v1/namespaces/dsh-a2a-qual/secrets')
        insecure=ssl._create_unverified_context()
        with self.assertRaisesRegex(ValueError,'VERIFIED_KUBERNETES_TLS'):
            WorkerAPI(origin='https://kubernetes.invalid',tls_context=insecure,authorization=Mock(),
                      namespace='dsh-a2a-qual',namespace_uid=NS_UID)
        api=self.api([(302,dict(kind='Status'))])
        with self.assertRaisesRegex(RuntimeError,'UNCERTAIN_NO_RETRY'):
            api.read_namespace()
        self.assertEqual(len(self.connections),1)

    def test_uncertain_create_has_exactly_one_post_and_no_retry(self):
        api=self.api([(200,self.namespace()),(500,dict(kind='Status',reason='InternalError'))])
        with self.assertRaisesRegex(ValueError,'CREATE_UNCERTAIN_NO_RESEND'):
            api.create_pod_once(self.pod())
        self.assertEqual([c.request.call_args.args[0] for c in self.connections],['GET','POST'])

    def test_delete_binds_uid_and_resource_version_but_does_not_claim_absence(self):
        api=self.api([(200,self.namespace()),(202,dict(kind='Status',status='Success'))])
        result=api.delete_pod_once(name='a2a-'+'a'*32,pod_uid=POD_UID,resource_version='2')
        body=json.loads(self.connections[-1].request.call_args.kwargs['body'])
        self.assertEqual(body['preconditions'],dict(uid=POD_UID,resourceVersion='2'))
        self.assertEqual(result,dict(deleteAccepted=True,podUID=POD_UID))
        self.assertNotIn('absent',result)

    def test_authentication_failure_has_no_fallback_or_error_secret(self):
        secret='synthetic-never-displayed-by-client'
        auth=Mock(side_effect=RuntimeError(secret));connection=Mock()
        api=WorkerAPI(origin='https://kubernetes.invalid',tls_context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            authorization=auth,namespace='dsh-a2a-qual',namespace_uid=NS_UID,connection_factory=connection)
        with self.assertRaisesRegex(RuntimeError,'UNCERTAIN_NO_RETRY') as caught:
            api.read_namespace()
        self.assertNotIn(secret,str(caught.exception))
        auth.assert_called_once();connection.assert_not_called()
