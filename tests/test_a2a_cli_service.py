from types import SimpleNamespace
from threading import RLock,Event
import unittest
from unittest.mock import Mock
from scripts.a2a_cli_service import ProtectedCLIService


class CLIServiceTests(unittest.TestCase):
    def test_recovery_preserves_completed_result_without_transport(self):
        task=self.task();task.state='completed'
        task.a2a_cli_context=dict(subject='owner',stageId=task.id,correlationId=task.correlation_id,
            project='project',runtime='claude')
        task.a2a_terminal_receipt=dict(task.a2a_cli_context,stopped=True,
            processExitVerified=True,descendantAbsenceVerified=True,scopeUid='accepted-scope')
        supervisor=SimpleNamespace(subject='owner',qualified=True,execute_once=Mock(),observe_terminal=Mock())
        service=ProtectedCLIService(subject='owner',supervisor=supervisor,workspace_resolver=lambda _: '/workspace/project')
        self.assertTrue(service.recover_task('owner',task))
        self.assertEqual(task.state,'completed')
        supervisor.execute_once.assert_not_called();supervisor.observe_terminal.assert_not_called()
        task.save.assert_not_called()

    def test_recovery_observes_old_scope_without_restarting_or_claiming_result(self):
        task=self.task();task.state='interrupted'
        task.a2a_cli_context=dict(subject='owner',stageId=task.id,correlationId=task.correlation_id,
            project='project',runtime='claude')
        def observe(context):
            return dict(context,stopped=True,processExitVerified=True,
                descendantAbsenceVerified=True,scopeUid='old-scope')
        supervisor=SimpleNamespace(subject='owner',qualified=True,
            execute_once=Mock(),observe_terminal=Mock(side_effect=observe))
        service=ProtectedCLIService(subject='owner',supervisor=supervisor,workspace_resolver=lambda _: '/workspace/project')
        self.assertTrue(service.recover_task('owner',task))
        self.assertEqual(task.state,'interrupted')
        self.assertTrue(task.finished.is_set())
        supervisor.execute_once.assert_not_called()
        self.assertEqual(supervisor.observe_terminal.call_count,1)

    def test_cancel_is_one_shot_and_requires_exact_scope_absence(self):
        task=self.task();task.state='running'
        task.a2a_cli_context=dict(subject='owner',stageId=task.id,correlationId=task.correlation_id,
            project='project',runtime='claude')
        task.a2a_cli_cancel=None
        def stop(context):
            return dict(context,stopped=True,processExitVerified=True,
                descendantAbsenceVerified=True,scopeUid='synthetic-scope')
        supervisor=SimpleNamespace(subject='owner',qualified=True,stop_and_verify=Mock(side_effect=stop))
        service=ProtectedCLIService(subject='owner',supervisor=supervisor,workspace_resolver=lambda _: '/workspace/project')
        self.assertTrue(service.cancel_task('owner',task))
        self.assertEqual(task.state,'cancelled')
        self.assertFalse(service.cancel_task('owner',task))
        self.assertEqual(supervisor.stop_and_verify.call_count,1)

    def test_a_never_started_stop_receipt_cancels_the_task_and_is_preserved_on_recovery(self):
        task=self.task();task.state='running'
        task.a2a_cli_context=dict(subject='owner',stageId=task.id,correlationId=task.correlation_id,
            project='project',runtime='claude')
        task.a2a_cli_cancel=None
        def stop(context):
            return dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True,neverStarted=True)
        supervisor=SimpleNamespace(subject='owner',qualified=True,stop_and_verify=Mock(side_effect=stop),observe_terminal=Mock())
        service=ProtectedCLIService(subject='owner',supervisor=supervisor,workspace_resolver=lambda _: '/workspace/project')
        self.assertTrue(service.cancel_task('owner',task))
        self.assertEqual(task.state,'cancelled');self.assertEqual(task.a2a_cli_cancel['status'],'verified')
        self.assertTrue(task.a2a_terminal_receipt['neverStarted']);self.assertNotIn('scopeUid',task.a2a_terminal_receipt)
        self.assertTrue(service.recover_task('owner',task))
        supervisor.observe_terminal.assert_not_called()

    def test_a_receipt_without_scope_or_never_started_still_fails_the_cancel(self):
        task=self.task();task.state='running'
        task.a2a_cli_context=dict(subject='owner',stageId=task.id,correlationId=task.correlation_id,
            project='project',runtime='claude')
        task.a2a_cli_cancel=None
        def stop(context):
            return dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True)
        supervisor=SimpleNamespace(subject='owner',qualified=True,stop_and_verify=Mock(side_effect=stop))
        service=ProtectedCLIService(subject='owner',supervisor=supervisor,workspace_resolver=lambda _: '/workspace/project')
        self.assertFalse(service.cancel_task('owner',task))
        self.assertEqual(task.state,'interrupted')

    def task(self):
        return SimpleNamespace(id='a'*32,correlation_id='b'*32,state='queued',
            request=dict(runtime='claude',backend='private',project='project',prompt='synthetic',writes=False),
            finished=Event(),persistence_lock=RLock(),save=Mock())

    def test_verified_scope_output_is_returned_without_replay(self):
        task=self.task()
        def execute(context,command,project):
            self.assertIn('--max-model-starts',command)
            return dict(context,exitCode=0,stopped=True,processExitVerified=True,
                descendantAbsenceVerified=True,scopeUid='synthetic-scope',output='checked')
        supervisor=SimpleNamespace(subject='owner',qualified=True,execute_once=Mock(side_effect=execute))
        service=ProtectedCLIService(subject='owner',supervisor=supervisor,workspace_resolver=lambda _: '/workspace/project')
        self.assertEqual(service.run_task('owner',task),'checked')
        self.assertEqual(task.state,'completed')
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):service.run_task('owner',task)
        self.assertTrue(task.finished.is_set())
        self.assertEqual(supervisor.execute_once.call_count,1)

    def test_wrapper_exit_without_descendant_evidence_is_not_completion(self):
        task=self.task()
        supervisor=SimpleNamespace(subject='owner',qualified=True,
            execute_once=Mock(return_value=dict(exitCode=0,output='not enough')))
        service=ProtectedCLIService(subject='owner',supervisor=supervisor,workspace_resolver=lambda _: '/workspace/project')
        with self.assertRaisesRegex(ValueError,'UNVERIFIED'):service.run_task('owner',task)
        self.assertEqual(task.state,'interrupted')
        self.assertEqual(supervisor.execute_once.call_count,1)
