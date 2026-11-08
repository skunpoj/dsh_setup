from types import SimpleNamespace
from threading import RLock
from unittest import TestCase
from unittest.mock import Mock
from pathlib import Path
import tempfile
import json
from scripts import a2a_worker_journal as journal


class WorkerJournalTests(TestCase):
    def terminal_task(self):
        from scripts.a2a_worker_receipt import terminal_projection
        task=self.task();record=self.reserve(task)
        pod_uid='22222222-2222-4222-8222-222222222222'
        journal.bind_created(task,operation_id=record['createOperationId'],pod_uid=pod_uid)
        journal.reserve_dispatch(task,pod_uid=pod_uid);journal.reserve_attach(task,pod_uid=pod_uid)
        projection=terminal_projection(dict(task.a2a_cli_context,scopeUid=pod_uid,stopped=True,
            processExitVerified=True,descendantAbsenceVerified=True,pidNamespaceInode=123,
            exitCode=0,output='private synthetic answer'))
        return task,pod_uid,projection

    def test_terminal_metadata_is_retained_without_answer_and_never_retires_worker(self):
        import hashlib
        task,pod_uid,projection=self.terminal_task()
        value=journal.retain_terminal_projection(task,pod_uid=pod_uid,projection=projection)
        raw=(task.directory/'a2a-worker-terminal.json').read_bytes()
        self.assertEqual(json.loads(raw),projection)
        self.assertNotIn(b'private synthetic answer',raw)
        self.assertEqual(value['terminalReceiptSha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(value['phase'],'dispatch-reserved')
        self.assertEqual(journal.read_terminal_projection(task),projection)
        guard_operation=journal.reserve_guard_attach(task,pod_uid=pod_uid)
        self.assertEqual(task.a2a_cli_worker['guardAttachOperationId'],guard_operation)
        with self.assertRaisesRegex(ValueError,'ALREADY_CONSUMED'):
            journal.reserve_guard_attach(task,pod_uid=pod_uid)
        with self.assertRaisesRegex(ValueError,'NO_OVERWRITE'):
            journal.retain_terminal_projection(task,pod_uid=pod_uid,projection=projection)

    def test_foreign_terminal_receipt_or_failed_save_cannot_be_accepted(self):
        task,pod_uid,projection=self.terminal_task()
        with self.assertRaisesRegex(ValueError,'NOT_ADMITTED'):
            journal.reserve_guard_attach(task,pod_uid=pod_uid)
        projection['subject']='foreign'
        with self.assertRaisesRegex(ValueError,'FOREIGN'):
            journal.retain_terminal_projection(task,pod_uid=pod_uid,projection=projection)
        self.assertFalse((task.directory/'a2a-worker-terminal.json').exists())
        projection['subject']='owner';task.save.side_effect=OSError('synthetic save failure')
        with self.assertRaises(OSError):
            journal.retain_terminal_projection(task,pod_uid=pod_uid,projection=projection)
        self.assertEqual(task.state,'interrupted')
        self.assertEqual(task.a2a_cli_worker['phase'],'persistence-uncertain')
        self.assertTrue((task.directory/'a2a-worker-terminal.json').exists())
        with self.assertRaisesRegex(ValueError,'DURABLE_TERMINAL_JOURNAL'):
            journal.read_terminal_projection(task)

    def test_recovery_rejects_changed_receipt_bytes_and_missing_journal_hash(self):
        task,pod_uid,projection=self.terminal_task()
        journal.retain_terminal_projection(task,pod_uid=pod_uid,projection=projection)
        path=task.directory/'a2a-worker-terminal.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'BYTES_CHANGED'):journal.read_terminal_projection(task)
        del task.a2a_cli_worker['terminalReceiptSha256']
        with self.assertRaisesRegex(ValueError,'DURABLE_TERMINAL_JOURNAL'):
            journal.read_terminal_projection(task)

    def test_exact_task_attach_is_durable_once_and_cannot_be_reattached(self):
        task=self.task();record=self.reserve(task)
        pod_uid='22222222-2222-4222-8222-222222222222'
        journal.bind_created(task,operation_id=record['createOperationId'],pod_uid=pod_uid)
        with self.assertRaisesRegex(ValueError,'FENCED'):journal.reserve_attach(task,pod_uid=pod_uid)
        journal.reserve_dispatch(task,pod_uid=pod_uid)
        operation=journal.reserve_attach(task,pod_uid=pod_uid)
        self.assertEqual(task.a2a_cli_worker['attachOperationId'],operation)
        self.assertEqual(task.a2a_cli_worker['phase'],'dispatch-reserved')
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):
            journal.reserve_attach(task,pod_uid=pod_uid)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def task(self):
        task=SimpleNamespace(id='a'*32,correlation_id='b'*32,state='running',
            authenticated_subject='owner',request=dict(project='private',runtime='claude'),
            a2a_cli_worker=None,persistence_lock=RLock(),save=Mock(),directory=Path(self.temp.name))
        task.a2a_cli_context=dict(subject='owner',stageId=task.id,correlationId=task.correlation_id,
                                 project='private',runtime='claude')
        return task

    def reserve(self,task):
        return journal.reserve(task,namespace='private-test',
            namespace_uid='11111111-1111-4111-8111-111111111111',
            template_sha256='c'*64,image='invalid.example/runtime@sha256:'+'d'*64)

    def test_no_second_create_or_dispatch_after_saved_reservation(self):
        task=self.task();record=self.reserve(task)
        task.save.assert_called_once()
        self.assertEqual(record['phase'],'create-reserved')
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):self.reserve(task)
        journal.bind_created(task,operation_id=record['createOperationId'],
                             pod_uid='22222222-2222-4222-8222-222222222222')
        journal.reserve_dispatch(task,pod_uid='22222222-2222-4222-8222-222222222222')
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):
            journal.reserve_dispatch(task,pod_uid='22222222-2222-4222-8222-222222222222')

    def test_persistence_failure_retains_uncertainty_and_never_allows_create_again(self):
        task=self.task();task.save.side_effect=OSError('synthetic write failure')
        with self.assertRaises(OSError):self.reserve(task)
        self.assertEqual(task.state,'interrupted')
        self.assertEqual(task.a2a_cli_worker['phase'],'persistence-uncertain')
        with self.assertRaises(ValueError):self.reserve(task)

    def test_wrong_subject_or_replacement_uid_cannot_bind(self):
        task=self.task();task.a2a_cli_context['subject']='foreign'
        with self.assertRaisesRegex(ValueError,'NOT_ADMITTED'):self.reserve(task)
        task.a2a_cli_context['subject']='owner';record=self.reserve(task)
        with self.assertRaisesRegex(ValueError,'IDENTITY_UNCERTAIN'):
            journal.bind_created(task,operation_id='e'*32,
                                 pod_uid='22222222-2222-4222-8222-222222222222')
        self.assertIsNone(task.a2a_cli_worker['podUID'])
        journal.bind_created(task,operation_id=record['createOperationId'],
                             pod_uid='22222222-2222-4222-8222-222222222222')
        with self.assertRaisesRegex(ValueError,'IDENTITY_UNCERTAIN'):
            journal.bind_created(task,operation_id=record['createOperationId'],
                                 pod_uid='33333333-3333-4333-8333-333333333333')

    def test_guard_ledger_receipt_is_bound_and_cannot_be_overwritten(self):
        task=self.task();record=self.reserve(task)
        raw=(json.dumps(dict(event='task-fenced',task_id=task.id,task_correlation_id=task.correlation_id,
                            operation_id='d'*32,utc='synthetic'))+'\n').encode()
        journal.bind_created(task,operation_id=record['createOperationId'],
                             pod_uid='22222222-2222-4222-8222-222222222222')
        journal.reserve_dispatch(task,pod_uid='22222222-2222-4222-8222-222222222222')
        with self.assertRaisesRegex(ValueError,'IDENTITY_UNCERTAIN'):
            journal.retain_guard_ledger(task,pod_uid='33333333-3333-4333-8333-333333333333',ledger_bytes=raw)
        journal.retain_guard_ledger(task,pod_uid='22222222-2222-4222-8222-222222222222',ledger_bytes=raw)
        self.assertEqual((task.directory/'a2a-guard-ledger.jsonl').read_bytes(),raw)
        with self.assertRaisesRegex(ValueError,'IDENTITY_UNCERTAIN'):
            journal.retain_guard_ledger(task,pod_uid='22222222-2222-4222-8222-222222222222',ledger_bytes=raw)

    def test_guard_ledger_cannot_be_retained_before_dispatch_or_after_uncertainty(self):
        for phase in ('create-reserved','bound','persistence-uncertain'):
            with self.subTest(phase=phase):
                task=self.task();record=self.reserve(task)
                journal.bind_created(task,operation_id=record['createOperationId'],
                                     pod_uid='22222222-2222-4222-8222-222222222222')
                task.a2a_cli_worker['phase']=phase
                raw=(json.dumps(dict(event='task-fenced',task_id=task.id,task_correlation_id=task.correlation_id,
                                     operation_id='d'*32,utc='synthetic'))+'\n').encode()
                with self.assertRaisesRegex(ValueError,'IDENTITY_UNCERTAIN'):
                    journal.retain_guard_ledger(task,pod_uid='22222222-2222-4222-8222-222222222222',ledger_bytes=raw)
                self.assertIsNone(task.a2a_cli_worker['guardLedgerSha256'])
                self.assertFalse((task.directory/'a2a-guard-ledger.jsonl').exists())

    def test_arbitrary_content_or_foreign_task_cannot_be_archived_as_guard_ledger(self):
        task=self.task()
        for raw in (b'{"secret":"synthetic-rejected"}\n',
            (json.dumps(dict(event='task-fenced',task_id='c'*32,task_correlation_id=task.correlation_id,
                            operation_id='d'*32,utc='synthetic'))+'\n').encode()):
            with self.assertRaises(ValueError):journal.validate_guard_ledger(task,raw)
        self.assertFalse((task.directory/'a2a-guard-ledger.jsonl').exists())
