"""Durable launch reservations, not provider calls or inferred model spend."""
import copy
import hashlib
from pathlib import Path
import tempfile
from threading import RLock
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_factory_budget import reserve_launch


class FactoryBudgetTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.registry=SimpleNamespace(tasks={},lock=RLock())
        self.admission=dict(modelStartsAllowed=1,subject='owner',generation='generation-1')

    def task(self,letter='a'):
        task=SimpleNamespace(id=letter*32,correlation_id='f'*32,authenticated_subject='owner',state='running',
            request=dict(prompt='synthetic task',runtime='claude',project='private',writes=False),
            persistence_lock=RLock(),save=Mock(),a2a_factory_allowance=None,a2a_stages=[],active_a2a_child=None)
        task.directory=self.root/task.id;task.directory.mkdir(exist_ok=True)
        return task

    def binding(self,task):
        return dict(subject='owner',generation='generation-1',taskId=task.id,correlationId=task.correlation_id,
            runtime='claude',project='private',writes=False,
            promptSha256=hashlib.sha256(task.request['prompt'].encode()).hexdigest())

    def reserve(self,task):
        return reserve_launch(task,registry=self.registry,admission=self.admission,binding=self.binding(task))

    def test_reserved_and_saved_before_return_no_refund_or_replay(self):
        task=self.task();self.registry.tasks[task.id]=task
        record=self.reserve(task)
        task.save.assert_called_once();self.assertEqual(record,task.a2a_factory_allowance)
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):self.reserve(task)
        other=self.task('b');self.registry.tasks[other.id]=other
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_EXHAUSTED'):self.reserve(other)
        other.save.assert_not_called()

    def test_failed_task_save_consumes_uncertain_reservation_and_does_not_start(self):
        task=self.task();self.registry.tasks[task.id]=task
        task.save.side_effect=OSError('synthetic persistence failure')
        with self.assertRaises(OSError):self.reserve(task)
        self.assertEqual(task.state,'interrupted')
        self.assertEqual(task.a2a_factory_allowance['status'],'persistence-uncertain')
        with self.assertRaisesRegex(ValueError,'FENCED_CHANGED_OR_ALREADY_RESERVED'):self.reserve(task)

    def parent(self,child):
        parent=self.task('c');self.registry.tasks[parent.id]=parent
        parent.active_a2a_child=child
        parent.a2a_stages=[dict(stageId=child.id,correlationId=child.correlation_id,status='reserved')]
        return parent

    def test_parent_preserves_allowance_after_child_is_no_longer_active(self):
        child=self.task();parent=self.parent(child)
        events=[];parent.save.side_effect=lambda:events.append('parent');child.save.side_effect=lambda:events.append('child')
        record=self.reserve(child)
        self.assertEqual(events,['parent','child'])
        self.assertEqual(parent.a2a_stages[-1]['factoryAllowance'],record)
        parent.active_a2a_child=None
        next_child=self.task('b');parent.active_a2a_child=next_child
        parent.a2a_stages.append(dict(stageId=next_child.id,correlationId=next_child.correlation_id,status='reserved'))
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_EXHAUSTED'):self.reserve(next_child)

    def test_parent_and_active_child_copy_are_counted_once(self):
        self.admission['modelStartsAllowed']=2
        child=self.task();parent=self.parent(child);record=self.reserve(child)
        self.registry.tasks[child.id]=child  # A recovered canonical entry may also be present.
        other=self.task('b');self.registry.tasks[other.id]=other
        self.reserve(other)
        self.assertEqual(parent.a2a_stages[-1]['factoryAllowance'],record)
        third=self.task('d');self.registry.tasks[third.id]=third
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_EXHAUSTED'):self.reserve(third)

    def test_changed_prompt_foreign_or_unregistered_task_refuses(self):
        task=self.task()
        with self.assertRaisesRegex(ValueError,'CANONICAL_FACTORY_TASK'):self.reserve(task)
        self.registry.tasks[task.id]=task
        binding=self.binding(task);task.request['prompt']='changed'
        with self.assertRaisesRegex(ValueError,'TASK_FENCED_CHANGED'):
            reserve_launch(task,registry=self.registry,admission=self.admission,binding=binding)
        task.save.assert_not_called()

    def test_disagreeing_durable_copies_block_new_reservation(self):
        child=self.task();parent=self.parent(child);self.reserve(child)
        parent.a2a_stages[-1]['factoryAllowance']['project']='foreign'
        other=self.task('b');self.registry.tasks[other.id]=other
        with self.assertRaisesRegex(ValueError,'DURABILITY_UNRESOLVED'):self.reserve(other)

    def test_concurrent_different_tasks_share_one_launch_allowance(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        tasks=[self.task('a'),self.task('b')]
        self.registry.tasks.update({task.id:task for task in tasks})
        barrier=Barrier(2)
        def attempt(task):
            barrier.wait(timeout=2)
            try:self.reserve(task);return 'reserved'
            except ValueError as error:return str(error)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(attempt,tasks))
        self.assertEqual(results.count('reserved'),1)
        self.assertEqual(results.count('FACTORY_LAUNCH_ALLOWANCE_EXHAUSTED'),1)

    def test_parent_persistence_failure_never_allows_launch_or_replay(self):
        child=self.task();parent=self.parent(child)
        parent.save.side_effect=OSError('synthetic parent persistence failure')
        with self.assertRaises(OSError):self.reserve(child)
        child.save.assert_not_called();self.assertIsNone(child.a2a_factory_allowance)
        self.assertIsNotNone(parent.a2a_stages[-1]['factoryAllowance'])
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_EXHAUSTED'):self.reserve(child)
