"""Real CLI controller/lifecycle composition, synthetic API and stream only."""
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_cli_lifecycle import CLIControllerLifecycle
from scripts.a2a_worker_receipt import terminal_projection
from scripts.agent_runtime_commands import command_for


class CLILifecycleTests(TestCase):
    def setUp(self):
        from test_a2a_worker_controller import WorkerControllerTests
        self.fixture=WorkerControllerTests();self.fixture.setUp()
        self.task=self.fixture.task;self.api=self.fixture.api;self.controller=self.fixture.controller
        self.task.request['backend']='private'
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.task.directory=Path(self.temp.name)
        create=self.api.create_pod_once.side_effect
        def make_pod(manifest):
            pod=create(manifest);self.api.read_pod.return_value=pod;return pod
        self.api.create_pod_once.side_effect=make_pod
        self.fixture.allow_models=1
        self.stream=Mock()
        def stream_factory(**kwargs):
            self.stream.start.side_effect=kwargs['before_attach'];return self.stream
        self.lifecycle=CLIControllerLifecycle(controller=self.controller,
            task_lookup=lambda task_id:self.task if task_id==self.task.id else None,
            stream_factory=stream_factory,observation_timeout=.05)
        self.context=dict(self.task.a2a_cli_context)

    def terminal(self,*,cancel=None):
        result=dict(self.task.a2a_cli_context,scopeUid=self.fixture.pod['metadata']['uid'],
            stopped=True,processExitVerified=True,descendantAbsenceVerified=True,
            pidNamespaceInode=123,exitCode=0,output='synthetic checked answer')
        if cancel:result.update(cancelled=True,operationId=cancel,exitCode=None,output='')
        self.fixture.pod['status']['containerStatuses'][0]['state']={'terminated':dict(
            exitCode=0,finishedAt='synthetic',message=json.dumps(terminal_projection(result)))}
        return result

    def test_construction_is_inert_and_never_self_qualifies(self):
        self.assertFalse(hasattr(self.lifecycle,'qualified'))
        self.api.read_pod.assert_not_called();self.api.create_pod_once.assert_not_called()
        self.task.save.assert_not_called();self.stream.start.assert_not_called()

    def test_execution_returns_only_exact_output_matched_to_actual_pod_receipt(self):
        self.stream.receive_line.side_effect=lambda **_:json.dumps(self.terminal())
        result=self.lifecycle.execute_once(self.context,self.fixture.command,self.fixture.project['brokerPath'])
        self.assertEqual(result['output'],'synthetic checked answer')
        self.assertTrue((self.task.directory/'a2a-worker-terminal.json').is_file())
        self.api.create_pod_once.assert_called_once();self.stream.start.assert_called_once()
        self.assertEqual(self.stream.send_line.call_count,1)
        self.assertNotEqual(self.task.a2a_cli_worker['phase'],'retired')
        with self.assertRaises(ValueError):
            self.lifecycle.execute_once(self.context,self.fixture.command,self.fixture.project['brokerPath'])
        self.api.create_pod_once.assert_called_once()

    def test_deepagents_uses_same_physical_lifecycle_with_its_own_command(self):
        self.task.request['runtime']='deepagents';self.task.a2a_cli_context['runtime']='deepagents'
        self.context=dict(self.task.a2a_cli_context)
        command=command_for('deepagents',self.task.request['prompt'],False,self.fixture.project['brokerPath'],self.task.id)
        self.stream.receive_line.side_effect=lambda **_:json.dumps(self.terminal())
        self.assertEqual(self.lifecycle.execute_once(self.context,command,self.fixture.project['brokerPath'])['runtime'],'deepagents')
        self.assertEqual(json.loads(self.stream.send_line.call_args.args[0])['context']['runtime'],'deepagents')

    def test_lost_output_can_recover_only_stop_metadata_without_reattach(self):
        self.stream.receive_line.side_effect=TimeoutError('synthetic lost stream')
        with self.assertRaises(TimeoutError):
            self.lifecycle.execute_once(self.context,self.fixture.command,self.fixture.project['brokerPath'])
        self.terminal()
        recovered=self.lifecycle.observe_terminal(self.context)
        self.assertTrue(recovered['processExitVerified']);self.assertFalse(recovered['outputAvailable'])
        self.assertNotIn('output',recovered)
        self.api.create_pod_once.assert_called_once();self.stream.start.assert_called_once()
        self.assertEqual(self.stream.send_line.call_count,1)

    def test_mismatched_stream_result_is_not_retained(self):
        def mismatch(**_):
            result=self.terminal();result['output']='different content';return json.dumps(result)
        self.stream.receive_line.side_effect=mismatch
        with self.assertRaisesRegex(ValueError,'MISMATCH'):
            self.lifecycle.execute_once(self.context,self.fixture.command,self.fixture.project['brokerPath'])
        self.assertFalse((self.task.directory/'a2a-worker-terminal.json').exists())

    def test_cancel_uses_existing_frame_once_and_recovery_binds_same_operation(self):
        self.controller.prepare_cli(self.task,self.fixture.command,self.fixture.project['brokerPath'])
        self.controller.open_cli_stream(self.task,stream_factory=self.lifecycle.stream_factory)
        self.task.state='cancelling';self.task.a2a_cli_cancel=dict(operationId='d'*32,status='reserved')
        self.stream.send_line.side_effect=lambda raw:self.terminal(cancel=json.loads(raw)['operationId'])
        context={**self.context,'operationId':'d'*32}
        self.assertTrue(self.lifecycle.stop_and_verify(context)['processExitVerified'])
        with self.assertRaises(ValueError):self.lifecycle.stop_and_verify(context)
        self.assertEqual(self.stream.send_line.call_count,2)
        self.assertTrue(self.lifecycle.observe_terminal(self.context)['processExitVerified'])
        self.task.a2a_cli_cancel['operationId']='e'*32
        with self.assertRaisesRegex(ValueError,'RECOVERY_STOP_OPERATION_CHANGED'):
            self.lifecycle.observe_terminal(self.context)

    def test_stop_before_any_launch_returns_a_never_started_receipt_without_a_scope(self):
        # v7 L3 analogue for the CLI stage of L6/L9: the model gate refuses the launch (zero allowance) before any worker reservation exists.
        self.api.read_pod.return_value=None
        self.task.a2a_cli_worker=None
        self.task.state='cancelling';self.task.a2a_cli_cancel=dict(operationId='d'*32,status='reserved')
        context={**self.context,'operationId':'d'*32}
        proof=self.lifecycle.stop_and_verify(context)
        self.assertEqual({k:proof[k] for k in ('stopped','processExitVerified','descendantAbsenceVerified','neverStarted')},
            dict(stopped=True,processExitVerified=True,descendantAbsenceVerified=True,neverStarted=True))
        self.assertNotIn('scopeUid',proof);self.assertEqual(proof['operationId'],'d'*32)
        self.api.create_pod_once.assert_not_called();self.stream.start.assert_not_called();self.stream.send_line.assert_not_called()
        with self.assertRaisesRegex(ValueError,'FENCED'):                    # the cancelled task can never launch afterwards
            self.lifecycle.execute_once(self.context,self.fixture.command,self.fixture.project['brokerPath'])
        self.api.create_pod_once.assert_not_called()

    def test_an_unreadable_pod_api_keeps_the_stop_uncertain(self):
        self.task.a2a_cli_worker=None
        self.task.state='cancelling';self.task.a2a_cli_cancel=dict(operationId='d'*32,status='reserved')
        self.api.read_pod.side_effect=RuntimeError('WORKER_API_OPERATION_UNCERTAIN_NO_RETRY')
        with self.assertRaises(RuntimeError):
            self.lifecycle.stop_and_verify({**self.context,'operationId':'d'*32})

    def test_never_started_stop_refuses_when_a_worker_pod_is_present(self):
        self.task.a2a_cli_worker=None
        self.task.state='cancelling';self.task.a2a_cli_cancel=dict(operationId='d'*32,status='reserved')
        self.api.read_pod.return_value={'metadata':{'name':'present'}}
        with self.assertRaisesRegex(ValueError,'CLI_NEVER_STARTED_BUT_WORKER_POD_PRESENT'):
            self.lifecycle.stop_and_verify({**self.context,'operationId':'d'*32})

    def test_foreign_binding_and_fenced_launch_refuse_before_api(self):
        with self.assertRaisesRegex(ValueError,'FOREIGN_CLI'):
            self.lifecycle.execute_once({**self.context,'subject':'foreign'},self.fixture.command,self.fixture.project['brokerPath'])
        self.task.state='interrupted'
        with self.assertRaisesRegex(ValueError,'FENCED'):
            self.lifecycle.execute_once(self.context,self.fixture.command,self.fixture.project['brokerPath'])
        self.api.create_pod_once.assert_not_called()
