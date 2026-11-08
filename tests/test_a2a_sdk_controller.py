"""Actual SDK controller composition over a synthetic scoped API only."""
import copy
import json
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_sdk_controller import SDKWorkerController
from scripts.a2a_worker_receipt import terminal_projection


class SDKControllerTests(TestCase):
    def setUp(self):
        from test_a2a_worker_controller import WorkerControllerTests
        self.fixture=WorkerControllerTests();self.fixture.setUp()
        f=self.fixture;self.task=f.task;self.api=f.api
        self.task.request.update(runtime='sdk',backend='private');self.task.a2a_cli_context=None
        self.task.native_sdk=dict(subject='owner',generation='test-generation',taskId=self.task.id,
            sessionId=self.task.id,project=self.task.request['project'],correlationId=self.task.correlation_id,
            launchOperationId='d'*32,phase='launch-reserved',guardLifecyclePending=True)
        self.binding={k:self.task.native_sdk[k] for k in
            ('subject','generation','taskId','sessionId','project','correlationId')}
        self.binding['packageAdmissionSha256']='e'*64
        self.controller=SDKWorkerController(api=self.api,subject='owner',generation='test-generation',
            package_admission_sha256='e'*64,image=f.image,source_commit='f'*40,node_name='fixture-node',
            project_admission=lambda *_:dict(f.project),execution_admission=f.admission,clock=lambda:100)
    def prepare(self):return self.controller.prepare_sdk(self.task,binding=self.binding)
    def bootstrap(self):
        from test_a2a_sdk_worker import SDKWorkerTests
        boot=SDKWorkerTests().request()['bootstrap'];boot['binding']=copy.deepcopy(self.binding)
        boot['options']['env']['DSH_CORRELATION_ID']=self.task.correlation_id
        return boot
    def test_create_exact_sdk_profile_after_native_launch_and_task_reservation(self):
        value=self.prepare()
        self.assertEqual(value['phase'],'bound');self.api.create_pod_once.assert_called_once()
        self.assertEqual(value['sdkBinding'],dict(generation='test-generation',
            launchOperationId='d'*32,packageAdmissionSha256='e'*64))
        command=self.fixture.manifest['spec']['containers'][0]['command']
        self.assertEqual(command[-1],'/opt/dsh/scripts/a2a_sdk_worker.py')
        self.assertNotIn(self.task.request['prompt'],json.dumps(self.fixture.manifest))
    def test_foreign_generation_package_or_fenced_launch_cannot_create(self):
        for field,value in [('generation','foreign'),('packageAdmissionSha256','a'*64)]:
            binding={**self.binding,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.controller.prepare_sdk(self.task,binding=binding)
        self.task.native_sdk['phase']='stop-reserved'
        with self.assertRaisesRegex(ValueError,'LAUNCH_FENCED'):self.prepare()
        self.api.create_pod_once.assert_not_called()
    def test_changed_native_launch_cannot_adopt_existing_physical_worker(self):
        self.prepare();self.api.read_pod.reset_mock();self.task.native_sdk['launchOperationId']='b'*32
        with self.assertRaisesRegex(ValueError,'PHYSICAL_LAUNCH_BINDING_CHANGED'):
            self.controller.observe(self.task)
        self.api.read_pod.assert_not_called();self.api.create_pod_once.assert_called_once()
    def test_uncertain_sdk_create_cannot_be_repeated(self):
        self.api.create_pod_once.side_effect=TimeoutError('synthetic create timeout')
        with self.assertRaises(TimeoutError):self.prepare()
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):self.prepare()
        self.api.create_pod_once.assert_called_once()
    def stream(self):
        self.transport_stream=Mock()
        def factory(**kwargs):
            self.transport_stream.start.side_effect=kwargs['before_attach']
            return self.transport_stream
        return self.controller.make_transport(self.task,binding=self.binding,stream_factory=factory)
    def test_transport_is_inert_and_requires_fresh_model_admission_before_attach(self):
        self.prepare();self.api.read_pod.return_value=self.fixture.pod
        transport=self.stream();self.transport_stream.start.assert_not_called()
        with self.assertRaisesRegex(ValueError,'EXECUTION_ADMISSION'):transport.start(self.bootstrap())
        self.transport_stream.start.assert_not_called();self.transport_stream.send_line.assert_not_called()
        self.assertEqual(self.task.a2a_cli_worker['phase'],'bound')
    def test_private_transport_consumes_dispatch_attach_and_native_stop_once(self):
        self.prepare();self.api.read_pod.return_value=self.fixture.pod;self.fixture.allow_models=1
        transport=self.stream();transport.start(self.bootstrap())
        self.assertEqual(self.task.a2a_cli_worker['phase'],'dispatch-reserved')
        self.assertIn('attachOperationId',self.task.a2a_cli_worker)
        first=json.loads(self.transport_stream.send_line.call_args.args[0])
        self.assertEqual(first['context']['runtime'],'sdk')
        self.assertEqual(first['bootstrap']['options']['cwd'],'/workspace')
        operation='a'*32;self.task.state='finalizing'
        self.task.native_sdk.update(phase='stop-reserved',stopOperationId=operation)
        result=transport.cancel_once(operation);self.assertFalse(result['processExitVerified'])
        self.assertEqual(self.transport_stream.send_line.call_count,2)
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):transport.cancel_once(operation)
        receipt=dict(self.task.a2a_cli_context,scopeUid=self.fixture.pod['metadata']['uid'],stopped=True,
            processExitVerified=True,descendantAbsenceVerified=True,pidNamespaceInode=123,
            exitCode=None,output='',cancelled=True,operationId=operation)
        self.fixture.pod['status']['containerStatuses'][0]['state']={'terminated':dict(exitCode=0,
            finishedAt='synthetic',message=json.dumps(terminal_projection(receipt)))}
        self.assertTrue(self.controller.observe_cancel(self.task,operation_id=operation)['processExitVerified'])
        with self.assertRaises(ValueError):self.controller.observe_cancel(self.task,operation_id='b'*32)
    def test_official_sdk_controller_cannot_fall_back_to_legacy_cli_adapter(self):
        for method in (self.controller.prepare_cli,self.controller.open_cli_stream,self.controller.reserve_cli_dispatch):
            with self.assertRaisesRegex(ValueError,'OFFICIAL_CONTROL_ONLY'):method()
        self.api.create_pod_once.assert_not_called()
