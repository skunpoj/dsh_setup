"""File-backed Task recovery and synthetic exact-UID worker deletion only."""
import copy
import json
from threading import RLock
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_worker_retirement import TaskWorkerRetirement,INTENT,RESULT


class WorkerRetirementTests(TestCase):
    def setUp(self):
        from test_a2a_provider_capture import ProviderCaptureTests
        self.f=ProviderCaptureTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.guard();self.f.capture(self.f.task,self.f.binding)
        self.task=self.f.task;self.binding=self.f.binding;self.controller=self.f.f.controller
        self.registry=SimpleNamespace(tasks={self.task.id:self.task},lock=RLock())
        w=self.task.a2a_cli_worker
        self.lease=dict(scope=dict(binding=copy.deepcopy(self.binding),namespace=w['namespace'],namespaceUID=w['namespaceUID'],
            podName=w['podName'],podUID=w['podUID'],source=copy.deepcopy(self.f.capture.source),captureSha256=w['providerCaptureSha256']),
            expiresAt=200,cleanupOnly=True)
        self.now=100
        self.controller.api.delete_pod_once=Mock(side_effect=self.delete)
        self.task.save=Mock(side_effect=lambda:self.save(self.task))
        self.task.save()
        self.retirement=self.make()

    def save(self,task):
        (task.directory/'fixture-task.json').write_text(json.dumps(task.a2a_cli_worker),encoding='utf-8')

    def restart(self):
        # Reconstruct persisted worker state, lock, registry and lifecycle;
        # never copy failed in-memory worker metadata into the new owner.
        restored=copy.copy(self.task)
        restored.a2a_cli_worker=json.loads((self.task.directory/'fixture-task.json').read_text(encoding='utf-8'))
        restored.persistence_lock=RLock();restored.save=Mock(side_effect=lambda:self.save(restored))
        self.task=restored;self.registry=SimpleNamespace(tasks={restored.id:restored},lock=RLock())
        self.retirement=self.make()

    def make(self):
        return TaskWorkerRetirement(registry=self.registry,controller=self.controller,capture=self.f.capture,
            admission_reader=lambda:copy.deepcopy(self.lease),clock=lambda:self.now)

    def delete(self,**kwargs):
        self.assertTrue((self.task.directory/INTENT).is_file())
        self.assertEqual(kwargs,dict(name=self.lease['scope']['podName'],pod_uid=self.lease['scope']['podUID'],resource_version='2'))
        self.controller.api.read_pod.return_value=None
        return dict(deleteAccepted=True,podUID=kwargs['pod_uid'])

    def test_retire_persists_before_delete_and_recovery_retains_result_without_replay(self):
        result=self.retirement.retire(self.task,self.binding)
        self.assertTrue(result['resourceAbsent']);self.assertFalse(result['providerExecutionStoppedVerified'])
        self.assertFalse(result['rollbackVerified'])
        self.restart()
        self.assertEqual(self.retirement.recover(self.task,self.binding),result)
        self.controller.api.delete_pod_once.assert_called_once();self.f.query.assert_called_once()

    def test_uncertain_delete_is_get_only_after_restart(self):
        def uncertain(**kwargs):self.delete(**kwargs);raise TimeoutError('synthetic lost response')
        self.controller.api.delete_pod_once.side_effect=uncertain
        with self.assertRaises(TimeoutError):self.retirement.retire(self.task,self.binding)
        self.restart()
        self.assertTrue(self.retirement.recover(self.task,self.binding)['resourceAbsent'])
        self.controller.api.delete_pod_once.assert_called_once();self.f.query.assert_called_once()

    def test_delete_timeout_with_worker_present_never_replays(self):
        self.controller.api.delete_pod_once.side_effect=TimeoutError('synthetic')
        with self.assertRaises(TimeoutError):self.retirement.retire(self.task,self.binding)
        self.restart()
        self.assertFalse(self.retirement.recover(self.task,self.binding)['resourceAbsent'])
        with self.assertRaisesRegex(ValueError,'OBSERVE_ONLY'):self.retirement.retire(self.task,self.binding)
        self.controller.api.delete_pod_once.assert_called_once()

    def test_task_commit_failure_after_durable_intent_does_not_delete_or_resend(self):
        self.task.save.side_effect=OSError('synthetic persistence failure')
        # capture.recover also commits Task state; allow that first commit.
        self.task.save.side_effect=[None,OSError('synthetic persistence failure')]
        with self.assertRaises(OSError):self.retirement.retire(self.task,self.binding)
        self.restart()
        self.assertFalse(self.retirement.recover(self.task,self.binding)['resourceAbsent'])
        self.controller.api.delete_pod_once.assert_not_called()

    def test_result_commit_failure_recovers_existing_bytes_without_second_delete(self):
        original=self.task.save.side_effect
        def fail_result():
            if (self.task.directory/RESULT).exists():raise OSError('synthetic result commit failure')
            original()
        self.task.save.side_effect=fail_result
        with self.assertRaises(OSError):self.retirement.retire(self.task,self.binding)
        self.restart()
        self.assertTrue(self.retirement.recover(self.task,self.binding)['resourceAbsent'])
        self.controller.api.delete_pod_once.assert_called_once()

    def test_expiry_foreign_identity_and_unreserved_absence_refuse(self):
        self.now=201
        with self.assertRaisesRegex(ValueError,'ADMISSION_REQUIRED'):self.retirement.retire(self.task,self.binding)
        self.now=100
        with self.assertRaisesRegex(ValueError,'FOREIGN'):self.retirement.retire(self.task,{**self.binding,'generation':'foreign'})
        self.controller.api.read_pod.return_value=None
        with self.assertRaises(ValueError):self.retirement.retire(self.task,self.binding)
        self.controller.api.delete_pod_once.assert_not_called()

    def test_partial_intent_and_replaced_uid_refuse_without_delete(self):
        (self.task.directory/INTENT).write_bytes(b'{')
        with self.assertRaises(ValueError):self.retirement.recover(self.task,self.binding)
        self.controller.api.delete_pod_once.assert_not_called()
        (self.task.directory/INTENT).unlink()  # Disposable fault fixture only.
        self.controller.api.delete_pod_once.side_effect=TimeoutError('synthetic')
        with self.assertRaises(TimeoutError):self.retirement.retire(self.task,self.binding)
        self.restart()
        pod=copy.deepcopy(self.controller.api.read_pod.return_value)
        pod['metadata']['uid']='33333333-3333-4333-8333-333333333333'
        self.controller.api.read_pod.return_value=pod
        with self.assertRaisesRegex(ValueError,'REPLACED'):self.retirement.recover(self.task,self.binding)
        self.controller.api.delete_pod_once.assert_called_once()

    def test_expired_recovery_needs_fresh_exact_cleanup_admission_and_never_deletes_again(self):
        result=self.retirement.retire(self.task,self.binding)
        self.restart();self.now=201
        with self.assertRaisesRegex(ValueError,'ADMISSION_REQUIRED'):self.retirement.recover(self.task,self.binding)
        self.lease['expiresAt']=250  # Synthetic newly supplied cleanup-only lease.
        self.assertEqual(self.retirement.recover(self.task,self.binding),result)
        self.controller.api.delete_pod_once.assert_called_once();self.f.query.assert_called_once()

    def test_tampered_retained_result_is_refused_without_query_or_delete_replay(self):
        self.retirement.retire(self.task,self.binding)
        path=self.task.directory/INTENT
        value=json.loads(path.read_bytes());value['retainedResult']['workerRetired']=True
        from scripts.a2a_provider_capture import canonical
        path.write_bytes(canonical(value))
        self.restart()
        with self.assertRaises(ValueError):self.retirement.recover(self.task,self.binding)
        self.controller.api.delete_pod_once.assert_called_once();self.f.query.assert_called_once()
