"""Physical lifecycle composition with actual controllers and synthetic IO."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_sdk_lifecycle import SDKControllerLifecycle
from scripts.official_sdk_control_peer import COMMAND
from scripts.a2a_worker_receipt import terminal_projection


class SDKLifecycleTests(TestCase):
    def setUp(self):
        from test_a2a_sdk_controller import SDKControllerTests
        self.fixture=SDKControllerTests();self.fixture.setUp()
        self.task=self.fixture.task;self.controller=self.fixture.controller
        self.api=self.fixture.api;self.binding=self.fixture.binding
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.task.directory=Path(self.temp.name)
        self.stream=Mock()
        def stream_factory(**kwargs):
            self.stream.start.side_effect=kwargs['before_attach'];return self.stream
        self.lifecycle=SDKControllerLifecycle(controller=self.controller,
            task_lookup=lambda task_id:self.task if task_id==self.task.id else None,
            stream_factory=stream_factory,observation_timeout=.05)
        self.transport=self.lifecycle.control_transport(binding=self.binding,command=COMMAND)
        self.harness=SimpleNamespace(binding=copy.deepcopy(self.binding),transport=self.transport,
            start=lambda:self.transport.start(self.fixture.bootstrap()),close=self.transport.close)
        self.context={k:v for k,v in self.binding.items() if k!='packageAdmissionSha256'}
        self.context['operationId']=self.task.native_sdk['launchOperationId']
        create=self.api.create_pod_once.side_effect
        def make_pod(manifest):
            pod=create(manifest);self.api.read_pod.return_value=pod;return pod
        self.api.create_pod_once.side_effect=make_pod
        self.fixture.fixture.allow_models=1

    def test_peer_construction_is_inert_and_does_not_self_qualify(self):
        self.api.read_pod.assert_not_called();self.api.create_pod_once.assert_not_called()
        self.task.save.assert_not_called();self.stream.start.assert_not_called()
        self.assertFalse(hasattr(self.lifecycle,'qualified'))
        with self.assertRaisesRegex(ValueError,'NOT_LAUNCH_BOUND'):
            self.transport.start(self.fixture.bootstrap())

    def test_start_uses_existing_launch_and_actual_controller_dispatch_once(self):
        result=self.lifecycle.start(self.harness,self.context)
        self.assertTrue(result['started'])
        self.assertEqual(result['runtimeIdentity']['podUID'],self.fixture.fixture.pod['metadata']['uid'])
        self.assertEqual(self.task.a2a_cli_worker['phase'],'dispatch-reserved')
        self.api.create_pod_once.assert_called_once();self.stream.start.assert_called_once()
        with self.assertRaisesRegex(ValueError,'NO_REPLAY'):
            self.lifecycle.start(self.harness,self.context)
        self.api.create_pod_once.assert_called_once()

    def test_foreign_context_fenced_launch_and_replacement_handles_refuse(self):
        for key in ('operationId','project','subject'):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'DURABLE_SDK_LAUNCH'):
                self.lifecycle.start(self.harness,{**self.context,key:'foreign'})
        self.task.native_sdk['phase']='stop-reserved'
        with self.assertRaisesRegex(ValueError,'LAUNCH_FENCED'):
            self.lifecycle.start(self.harness,self.context)
        with self.assertRaisesRegex(ValueError,'NO_REPLACEMENT'):
            self.lifecycle.control_transport(binding=self.binding,command=COMMAND)
        self.api.create_pod_once.assert_not_called()

    def test_uncertain_physical_create_cannot_be_repeated_or_local_fallback(self):
        self.api.create_pod_once.side_effect=TimeoutError('synthetic uncertain create')
        with self.assertRaises(TimeoutError):self.lifecycle.start(self.harness,self.context)
        with self.assertRaisesRegex(ValueError,'NO_REPLAY'):
            self.lifecycle.start(self.harness,self.context)
        self.api.create_pod_once.assert_called_once();self.stream.start.assert_not_called()

    def stopped_worker(self):
        started=self.lifecycle.start(self.harness,self.context)
        self.task.native_sdk['runtimeIdentity']=started['runtimeIdentity']
        self.task.state='finalizing'
        self.task.native_sdk.update(phase='stop-reserved',stopOperationId='b'*32)
        context={k:v for k,v in self.binding.items() if k!='packageAdmissionSha256'}
        context.update(operationId='b'*32,launchOperationId=self.context['operationId'])
        def on_frame(raw):
            value=json.loads(raw)
            if value.get('kind')!='cancel':raise AssertionError('unexpected resend')
            proof=dict(self.task.a2a_cli_context,scopeUid=self.fixture.fixture.pod['metadata']['uid'],
                stopped=True,processExitVerified=True,descendantAbsenceVerified=True,
                pidNamespaceInode=123,exitCode=None,output='',cancelled=True,operationId='b'*32)
            self.fixture.fixture.pod['status']['containerStatuses'][0]['state']={'terminated':dict(
                exitCode=0,finishedAt='synthetic',message=json.dumps(terminal_projection(proof)))}
        self.stream.send_line.side_effect=on_frame
        return context

    def test_stop_retains_physical_receipt_and_recovery_never_reattaches(self):
        context=self.stopped_worker()
        proof=self.lifecycle.stop_and_verify(self.harness,context)
        self.assertTrue(proof['processExitVerified']);self.assertTrue(proof['launchFenced'])
        self.assertTrue((self.task.directory/'a2a-worker-terminal.json').is_file())
        self.assertEqual(self.stream.send_line.call_count,2)
        recovery={k:v for k,v in context.items() if k!='operationId'}
        recovery['runtimeIdentity']=self.task.native_sdk['runtimeIdentity']
        recovered=self.lifecycle.inspect_exit(recovery)
        self.assertTrue(recovered['processExitVerified'])
        self.api.create_pod_once.assert_called_once();self.stream.start.assert_called_once()
        self.assertEqual(self.stream.send_line.call_count,2)
        self.assertNotEqual(self.task.a2a_cli_worker['phase'],'retired')
        self.task.native_sdk['stopOperationId']='e'*32
        with self.assertRaisesRegex(ValueError,'RECOVERY_STOP_OPERATION_CHANGED'):
            self.lifecycle.inspect_exit(recovery)

    def test_closed_inert_handle_cannot_create_worker(self):
        self.transport.close()
        with self.assertRaisesRegex(ValueError,'CLOSED_BEFORE_LAUNCH'):
            self.lifecycle.start(self.harness,self.context)
        self.api.create_pod_once.assert_not_called()

    def test_terminal_status_observation_does_not_resend_stop(self):
        context=self.stopped_worker();observe=self.controller.observe_cancel
        calls=[]
        def delayed(*args,**kwargs):
            calls.append(1)
            if len(calls)==1:raise ValueError('WORKER_INIT_EXIT_UNVERIFIED')
            return observe(*args,**kwargs)
        self.controller.observe_cancel=delayed
        self.assertTrue(self.lifecycle.stop_and_verify(self.harness,context)['processExitVerified'])
        self.assertEqual(len(calls),2);self.assertEqual(self.stream.send_line.call_count,2)

    def test_stop_without_actual_terminal_and_foreign_stop_cannot_claim_exit(self):
        self.lifecycle.start(self.harness,self.context)
        self.task.state='finalizing';self.task.native_sdk.update(phase='stop-reserved',stopOperationId='b'*32)
        context={k:v for k,v in self.binding.items() if k!='packageAdmissionSha256'}
        context.update(operationId='b'*32,launchOperationId=self.context['operationId'])
        with self.assertRaisesRegex(ValueError,'DURABLE_SDK_STOP'):
            self.lifecycle.stop_and_verify(self.harness,{**context,'operationId':'c'*32})
        with self.assertRaisesRegex(ValueError,'WORKER_INIT_EXIT_UNVERIFIED'):
            self.lifecycle.stop_and_verify(self.harness,context)
        self.assertFalse((self.task.directory/'a2a-worker-terminal.json').exists())

    def test_late_physical_stop_receipt_can_be_retained_without_resending_cancel(self):
        context=self.stopped_worker()
        finish=self.stream.send_line.side_effect
        self.stream.send_line.side_effect=None  # Actual stop not visible yet.
        with self.assertRaisesRegex(ValueError,'WORKER_INIT_EXIT_UNVERIFIED'):
            self.lifecycle.stop_and_verify(self.harness,context)
        self.assertFalse((self.task.directory/'a2a-worker-terminal.json').exists())
        finish(self.stream.send_line.call_args.args[0])  # Same worker stops later.
        recovery={k:v for k,v in context.items() if k!='operationId'}
        recovery['runtimeIdentity']=self.task.native_sdk['runtimeIdentity']
        self.assertTrue(self.lifecycle.inspect_exit(recovery)['processExitVerified'])
        self.assertTrue((self.task.directory/'a2a-worker-terminal.json').is_file())
        self.assertEqual(self.stream.send_line.call_count,2)
        self.api.create_pod_once.assert_called_once();self.stream.start.assert_called_once()
