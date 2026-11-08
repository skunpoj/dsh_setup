"""Protected factory composition policy; no real runtime/API/provider calls."""
import copy
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from threading import RLock
from pathlib import Path
import tempfile
from scripts.a2a_factory_contract import ProtectedA2AFactory,DEPENDENCIES,PROVIDER,BUDGET


class FactoryContractTests(TestCase):
    def setUp(self):
        self.api=SimpleNamespace(namespace='dsh-a2a-qual',namespace_uid='11111111-1111-4111-8111-111111111111')
        self.admit=Mock()
        common=dict(api=self.api,subject='owner',image='registry.invalid/image@sha256:'+'a'*64,
            source_commit='b'*40,node_name='test-node',execution_admission=self.admit)
        self.policy=dict(claim='private',subpath='owner/project',writes=False,
            brokerPath='/broker/project',credentialSecret='task-only')
        self.workspace=Mock(side_effect=lambda *_:copy.deepcopy(self.policy))
        self.sdk=SimpleNamespace(**common,generation='generation-1',package_hash='c'*64,project_admission=self.workspace)
        self.cli=SimpleNamespace(**common,project_admission=self.workspace)
        self.placement=dict(namespace=self.api.namespace,namespaceUID=self.api.namespace_uid,
            podUID='22222222-2222-4222-8222-222222222222',workloadUID='33333333-3333-4333-8333-333333333333',
            environment='test',workloadRole='qualification')
        self.lease=dict(subject='owner',generation='generation-1',namespace=self.api.namespace,
            namespaceUID=self.api.namespace_uid,nodeName='test-node',image=self.sdk.image,
            sourceCommit=self.sdk.source_commit,packageAdmissionSha256=self.sdk.package_hash,
            provider=copy.deepcopy(PROVIDER),resourceBudget=copy.deepcopy(BUDGET),
            expiresAt=200,modelStartsAllowed=0,rollbackOwner='test-owner')
        self.deps={name:Mock() for name in DEPENDENCIES}
        self.deps.update(workspacePolicy=self.workspace,executionAdmission=self.admit)
        self.task=SimpleNamespace(id='a'*32,correlation_id='b'*32,authenticated_subject='owner',state='running',
            request=dict(project='project',runtime='sdk',backend='private',writes=False,prompt='synthetic bounded task'))
        self.lookup=lambda task_id:self.task if task_id==self.task.id else None
        self.task.persistence_lock=RLock();self.task.save=Mock();self.task.a2a_factory_allowance=None
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.task.directory=Path(self.temp.name)/self.task.id;self.task.directory.mkdir()
        self.registry=SimpleNamespace(tasks={self.task.id:self.task},lock=RLock())
        self.now=100
        self.kwargs=dict(registry=self.registry,sdk_controller=self.sdk,cli_controller=self.cli,task_lookup=self.lookup,
            placement_observer=lambda:copy.deepcopy(self.placement),placement_binding=copy.deepcopy(self.placement),
            admission_reader=lambda:copy.deepcopy(self.lease),dependencies=self.deps,clock=lambda:self.now)
        self.factory=ProtectedA2AFactory(**self.kwargs)

    def test_constructor_and_binding_never_execute_or_self_qualify(self):
        self.assertFalse(hasattr(self.factory,'qualified'))
        for call in self.deps.values():call.assert_not_called()
        components=self.factory.bind(self.task)
        self.assertEqual(components['binding']['taskId'],self.task.id)
        for name in DEPENDENCIES-{'workspacePolicy'}:self.deps[name].assert_not_called()
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_EXHAUSTED'):
            components['before_model']()

    def test_missing_dependency_different_api_or_admission_refuses(self):
        for key in DEPENDENCIES:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'DEPENDENCIES'):
                ProtectedA2AFactory(**{**self.kwargs,'dependencies':{k:v for k,v in self.deps.items() if k!=key}})
        self.cli.api=copy.copy(self.api)
        with self.assertRaisesRegex(ValueError,'ONE_PROTECTED'):
            ProtectedA2AFactory(**self.kwargs)

    def test_foreign_stale_provider_budget_and_mutated_admission_refuse(self):
        components=self.factory.bind(self.task)
        for key,value in [('subject','foreign'),('generation','old'),('image','latest'),('expiresAt',99),
                          ('expiresAt',401),('modelStartsAllowed',True),('modelStartsAllowed',4)]:
            old=self.lease[key];self.lease[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):components['guard_factory']()
            self.lease[key]=old
        for section,key,value in [('provider','temperature',True),('provider','externalFallback',True),
                                  ('provider','model','external-model'),('resourceBudget','workerCPU','2'),
                                  ('resourceBudget','taskSeconds',True)]:
            old=self.lease[section][key];self.lease[section][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.factory.bind(self.task)
            self.lease[section][key]=old

    def test_expiry_blocks_new_work_but_bound_cleanup_still_requires_placement(self):
        components=self.factory.bind(self.task);self.now=201
        with self.assertRaises(ValueError):components['guard_factory']()
        components['capture_provider']('metadata-only')
        components['retire']();components['rollback']()
        self.deps['providerCapture'].assert_called_once()
        self.placement['podUID']='44444444-4444-4444-8444-444444444444'
        with self.assertRaisesRegex(ValueError,'PLACEMENT_CHANGED'):components['rollback']()
        self.assertEqual(self.deps['rollback'].call_count,1)

    def test_new_start_cannot_bypass_allowance_through_lifecycle(self):
        lifecycle=Mock();self.factory.sdk_lifecycle=lifecycle
        components=self.factory.bind(self.task)
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_EXHAUSTED'):
            components['lifecycle'].start(Mock(),{})
        lifecycle.start.assert_not_called()
        self.lease['modelStartsAllowed']=1
        with self.assertRaisesRegex(ValueError,'ADMISSION_CHANGED'):
            components['lifecycle'].start(Mock(),{})

    def test_foreign_task_replacement_and_workspace_write_escalation_refuse(self):
        components=self.factory.bind(self.task)
        self.task.authenticated_subject='foreign'
        with self.assertRaisesRegex(ValueError,'REPLACED_OR_FOREIGN'):components['rollback']()
        self.task.authenticated_subject='owner';self.task.request['writes']=True
        with self.assertRaisesRegex(ValueError,'WORKSPACE_POLICY'):self.factory.bind(self.task)

    def test_bound_task_prompt_writes_policy_and_execution_request_cannot_change(self):
        components=self.factory.bind(self.task)
        self.task.request['writes']=True
        with self.assertRaisesRegex(ValueError,'PROMPT_OR_WRITE_BINDING_CHANGED'):components['rollback']()
        self.task.request['writes']=False;self.task.request['prompt']='different task'
        with self.assertRaisesRegex(ValueError,'PROMPT_OR_WRITE_BINDING_CHANGED'):components['guard_factory']()
        self.task.request['prompt']='synthetic bounded task'
        self.policy['claim']='other-claim'
        with self.assertRaisesRegex(ValueError,'WORKSPACE_POLICY_CHANGED'):components['guard_factory']()
        self.policy['claim']='private'
        binding=components['binding']
        args=[binding[k] for k in ('subject','taskId','correlationId','project','runtime','writes','promptSha256')]
        foreign=list(args);foreign[1]='f'*32
        with self.assertRaisesRegex(ValueError,'FOREIGN_FACTORY_EXECUTION'):components['execution_admission'](*foreign)
        self.admit.assert_not_called()
        components['execution_admission'](*args);self.admit.assert_called_once_with(*args)

    def test_cleanup_without_raw_prompt_requires_same_retained_hash(self):
        components=self.factory.bind(self.task)
        del self.task.request['prompt']
        with self.assertRaisesRegex(ValueError,'PROMPT_OR_WRITE_BINDING_CHANGED'):components['rollback']()
        self.task.a2a_cli_worker={'promptSha256':components['binding']['promptSha256']}
        components['rollback']();self.deps['rollback'].assert_called_once()
        with self.assertRaisesRegex(ValueError,'PROMPT_OR_WRITE_BINDING_CHANGED'):components['guard_factory']()

    def test_lifecycle_launch_is_after_durable_allowance_and_cannot_replay(self):
        self.lease['modelStartsAllowed']=1
        events=[];self.task.save.side_effect=lambda:events.append('saved')
        lifecycle=Mock();lifecycle.start.side_effect=lambda *_:events.append('start')
        self.factory.sdk_lifecycle=lifecycle
        components=self.factory.bind(self.task)
        components['lifecycle'].start(Mock(),{})
        self.assertEqual(events,['saved','start'])
        self.assertEqual(self.task.a2a_factory_allowance['status'],'reserved')
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):
            components['lifecycle'].start(Mock(),{})
        lifecycle.start.assert_called_once()
