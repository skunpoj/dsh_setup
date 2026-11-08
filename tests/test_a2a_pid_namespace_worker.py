"""Contract tests only; these cannot qualify a physical Linux worker."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch, MagicMock
from scripts.a2a_pid_namespace_worker import validate_worker_request, require_private_init, unique_json, WorkerCancellation, execute_once
import io


class WorkerRequestTests(TestCase):
    def test_post_spawn_setup_failure_still_stops_descendants_and_closes_pipes(self):
        from contextlib import ExitStack
        for failure in ('construct','register'):
            with self.subTest(failure=failure),ExitStack() as stack:
                request=self.request();request['context']['scopeUid']='22222222-2222-4222-8222-222222222222'
                stack.enter_context(patch('scripts.a2a_pid_namespace_worker.require_private_init',return_value=123))
                stack.enter_context(patch('scripts.a2a_pid_namespace_worker.validate_worker_request',return_value=request['context']))
                path=stack.enter_context(patch('scripts.a2a_pid_namespace_worker.Path'))
                path.return_value.read_text.return_value=request['context']['scopeUid']
                stack.enter_context(patch('scripts.a2a_pid_namespace_worker.namespace_members',return_value=set()))
                stop=stack.enter_context(patch('scripts.a2a_pid_namespace_worker.stop_namespace'))
                popen=stack.enter_context(patch('scripts.a2a_pid_namespace_worker.subprocess.Popen'))
                selector=stack.enter_context(patch('scripts.a2a_pid_namespace_worker.selectors.DefaultSelector'))
                if failure=='construct':selector.side_effect=OSError('synthetic selector failure')
                else:selector.return_value.register.side_effect=OSError('synthetic register failure')
                with self.assertRaises(OSError):execute_once(request)
                stop.assert_called_once()
                popen.return_value.stdout.close.assert_called_once()
                popen.return_value.stderr.close.assert_called_once()
                if failure=='register':selector.return_value.close.assert_called_once()

    def test_cancel_is_exact_scope_one_shot_and_never_a_start(self):
        scope=self.request()['context'];control=WorkerCancellation(scope)
        value=dict(kind='cancel',context=scope,operationId='d'*32)
        foreign=deepcopy(value);foreign['context']['scopeUid']='foreign'
        with self.assertRaisesRegex(ValueError,'FOREIGN'):control.request(foreign)
        self.assertFalse(control.event.is_set())
        control.request(value)
        self.assertTrue(control.event.is_set());self.assertEqual(control.operation_id,'d'*32)
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):control.request(value)

    def test_lost_or_malformed_controller_pipe_fences_without_successful_cancel_receipt(self):
        for raw in (b'',b'not-json\n',b'{"kind":"restart"}\n'):
            control=WorkerCancellation(self.request()['context'])
            control.read_one(io.BytesIO(raw))
            self.assertTrue(control.event.is_set())
            self.assertIsNone(control.operation_id)
            self.assertIsNotNone(control.error)

    def test_duplicate_binding_fields_cannot_be_hidden_by_json_parser(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_WORKER_FIELD'):
            unique_json('{"context":{"subject":"owner","subject":"foreign"}}')
    def request(self):
        return dict(context=dict(subject='owner', stageId='a'*32,
            correlationId='b'*32, project='demo',runtime='claude',scopeUid='scope-uid'),
            command=['/usr/local/bin/dsh-unattended','claude','--task-id','a'*32,
                '--max-model-starts','1','--cwd','/workspace/demo',
                '--external-guard-port','4001','--','-p','synthetic'],
            cwd='/workspace/demo',uid=10001,gid=10001,
            environment={'PATH':'/opt/dsh/deepagents/bin:/usr/local/bin:/usr/bin:/bin','HOME':'/home/dsh',
                         'DSH_CORRELATION_ID':'b'*32},
            timeoutSeconds=30)

    def test_foreign_task_and_model_budget_are_rejected(self):
        for index,value in ((3,'foreign'),(5,'2'),(7,'/workspace/foreign')):
            request=self.request();request['command'][index]=value
            with self.assertRaisesRegex(ValueError,'COMMAND_BINDING'):
                validate_worker_request(request)

    def test_shell_root_and_broker_environment_are_rejected(self):
        for change,error in (({'command':['/bin/sh','-c','true']},'COMMAND'),
                             ({'uid':0},'PAYLOAD_ID'),
                             ({'environment':{'AZDO_PAT':'synthetic-never-used'}},'ENVIRONMENT')):
            request=self.request();request.update(change)
            with self.assertRaisesRegex(ValueError,error):validate_worker_request(request)

    def test_binding_rejects_extra_or_missing_identity(self):
        for field in ('subject','scopeUid','correlationId'):
            request=self.request();del request['context'][field]
            with self.assertRaisesRegex(ValueError,'BINDING'):validate_worker_request(request)

    def test_deadline_and_workspace_are_bounded(self):
        request=self.request();request['cwd']='/tmp';request['command'][7]='/tmp'
        with self.assertRaisesRegex(ValueError,'OUTSIDE_WORKSPACE'):validate_worker_request(request)
        with patch('scripts.a2a_pid_namespace_worker.Path') as path:
            path.return_value.is_absolute.return_value=True
            path.return_value.is_relative_to.return_value=True
            path.return_value.resolve.return_value=path.return_value
            for invalid in (0,301,True,'30'):
                request=self.request();request['timeoutSeconds']=invalid
                with self.assertRaisesRegex(ValueError,'DEADLINE'):validate_worker_request(request)

    def test_normal_worker_request_validation_does_not_launch(self):
        with patch('scripts.a2a_pid_namespace_worker.Path') as path, \
                patch('scripts.a2a_pid_namespace_worker.subprocess.Popen') as popen:
            path.return_value.is_absolute.return_value=True
            path.return_value.is_relative_to.return_value=True
            path.return_value.resolve.return_value=path.return_value
            self.assertEqual(validate_worker_request(self.request()),self.request()['context'])
            popen.assert_not_called()

    def test_worker_refuses_broker_process(self):
        with patch('scripts.a2a_pid_namespace_worker.os.getpid',return_value=123):
            with self.assertRaisesRegex(ValueError,'PID1_WORKER_REQUIRED'):require_private_init()
