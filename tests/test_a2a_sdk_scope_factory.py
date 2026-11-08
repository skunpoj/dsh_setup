"""Concrete bootstrap bridge tests; actual factory, synthetic lifecycle only."""
import copy
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_sdk_scope_factory import install_protected_a2a_factory,build_official_sdk_scope,PATH
from scripts.official_sdk_control_peer import COMMAND


class SDKScopeFactoryTests(TestCase):
    def setUp(self):
        from test_a2a_factory_contract import FactoryContractTests
        self.f=FactoryContractTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.config=dict(kind='DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1',mode='qualification',subject='owner',
            generation='generation-1',expiresAt=200,sourceCommit=self.f.sdk.source_commit,
            imageDigest='sha256:'+'a'*64,packageAdmissionSha256=self.f.sdk.package_hash,
            scopeModule=PATH,scopeSha256='e'*64,sources={'controller':'d'*64},deploymentBinding=copy.deepcopy(self.f.placement))
        self.context=dict(subject='owner',generation='generation-1',taskId=self.f.task.id,sessionId=self.f.task.id,
            project='project',correlationId=self.f.task.correlation_id)
        self.lifecycle=Mock();self.f.factory.sdk_lifecycle=self.lifecycle
        install_protected_a2a_factory(registry=self.f.registry,factory=self.f.factory)
        self.components=build_official_sdk_scope(registry=self.f.registry,admission=self.config)
        self.scope=self.components['scope']

    def test_construction_binding_inert_and_factory_cannot_be_replaced(self):
        self.assertEqual(set(self.components),{'scope','guardFactory'})
        for value in self.f.deps.values():value.assert_not_called()
        self.lifecycle.assert_not_called();self.f.task.save.assert_not_called()
        with self.assertRaisesRegex(ValueError,'NO_REPLACEMENT'):
            install_protected_a2a_factory(registry=self.f.registry,factory=self.f.factory)

    def test_qualified_is_fresh_placement_and_lease_not_a_stored_flag(self):
        self.assertTrue(self.scope.qualified)
        result=self.scope.admission_state('owner','generation-1')
        self.assertEqual(result['imageDigest'],self.config['imageDigest'])
        self.assertEqual(result['packageAdmissionSha256'],self.f.sdk.package_hash)
        self.f.now=201;self.assertFalse(self.scope.qualified)
        self.f.now=100;self.f.placement['podUID']='44444444-4444-4444-8444-444444444444'
        self.assertFalse(self.scope.qualified);self.lifecycle.start.assert_not_called()

    def test_preflight_binds_once_and_guard_reuses_existing_task_dependency(self):
        result=self.scope.preflight(self.context)
        self.assertTrue(result['admitted']);self.f.task.save.assert_not_called()
        self.components['guardFactory'](self.f.task)
        self.f.deps['guardFactory'].assert_called_once()
        with self.assertRaisesRegex(ValueError,'NO_REBIND'):self.scope.preflight(self.context)
        self.lifecycle.start.assert_not_called()

    def test_foreign_context_missing_owner_and_changed_image_refuse(self):
        with self.assertRaisesRegex(ValueError,'FOREIGN'):
            self.scope.preflight({**self.context,'sessionId':'f'*32})
        self.f.registry.protected_a2a_factory=None
        self.assertFalse(self.scope.qualified)
        with self.assertRaisesRegex(ValueError,'BINDING_REQUIRED'):
            build_official_sdk_scope(registry=self.f.registry,admission=self.config)
        self.f.registry.protected_a2a_factory=self.f.factory
        self.scope.admission['imageDigest']='sha256:'+'f'*64
        self.assertFalse(self.scope.qualified);self.lifecycle.start.assert_not_called()

    def test_transport_and_start_use_bound_lifecycle_and_durable_one_shot_budget(self):
        self.f.lease['modelStartsAllowed']=1
        self.scope.preflight(self.context)
        binding={**self.context,'packageAdmissionSha256':self.f.sdk.package_hash}
        self.assertIs(self.scope.control_transport(binding=binding,command=COMMAND),self.lifecycle.control_transport.return_value)
        events=[];self.f.task.save.side_effect=lambda:events.append('saved')
        self.lifecycle.start.side_effect=lambda *args:events.append('started')
        harness=Mock();context={**self.context,'operationId':'f'*32}
        self.scope.start(harness,context)
        self.assertEqual(events,['saved','started'])
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):self.scope.start(harness,context)
        self.lifecycle.start.assert_called_once()

    def test_cleanup_delegates_original_bound_lifecycle_after_expiry_without_launch(self):
        self.scope.preflight(self.context);self.f.now=201
        context={**self.context,'operationId':'f'*32,'launchOperationId':'e'*32}
        self.scope.stop_and_verify(Mock(),context)
        self.lifecycle.stop_and_verify.assert_called_once();self.lifecycle.start.assert_not_called()
        self.f.placement['podUID']='44444444-4444-4444-8444-444444444444'
        with self.assertRaisesRegex(ValueError,'PLACEMENT_CHANGED'):self.scope.stop_and_verify(Mock(),context)
        self.lifecycle.stop_and_verify.assert_called_once()

    def test_restart_inspect_delegates_read_only_without_new_preflight_or_start(self):
        recovered=build_official_sdk_scope(registry=self.f.registry,admission=self.config)['scope']
        self.assertIs(recovered.inspect_exit(self.context),self.lifecycle.inspect_exit.return_value)
        self.lifecycle.inspect_exit.assert_called_once_with(self.context)
        self.lifecycle.start.assert_not_called();self.f.task.save.assert_not_called()
        with self.assertRaisesRegex(ValueError,'PREFLIGHT_REQUIRED'):
            recovered.start(Mock(),self.context)

    def test_task_replacement_revokes_bound_handles_without_new_dependency(self):
        self.scope.preflight(self.context)
        self.f.task=copy.copy(self.f.task)
        with self.assertRaisesRegex(ValueError,'PREFLIGHT_REQUIRED'):
            self.scope.guard_factory(self.f.task)
        self.f.deps['guardFactory'].assert_not_called();self.lifecycle.start.assert_not_called()

    def test_earlier_bootstrap_expiry_fences_new_transport_guard_and_start(self):
        self.scope.admission['expiresAt']=150;self.f.lease['modelStartsAllowed']=1
        self.scope.preflight(self.context);self.f.now=151
        binding={**self.context,'packageAdmissionSha256':self.f.sdk.package_hash}
        for operation in (lambda:self.scope.control_transport(binding=binding,command=COMMAND),
                          lambda:self.scope.guard_factory(self.f.task),
                          lambda:self.scope.start(Mock(),self.context)):
            with self.assertRaisesRegex(ValueError,'BOOTSTRAP_DESCRIPTOR'):operation()
        self.lifecycle.start.assert_not_called();self.lifecycle.control_transport.assert_not_called()
        self.f.deps['guardFactory'].assert_not_called();self.f.task.save.assert_not_called()

    def test_owner_or_source_image_package_change_blocks_cleanup_and_inspection(self):
        self.scope.preflight(self.context)
        for attribute,value in [('subject','foreign'),('generation','other-generation'),
                                ('source_commit','f'*40),('image','registry.invalid/other@sha256:'+'f'*64),
                                ('package_hash','f'*64)]:
            previous=getattr(self.f.sdk,attribute);setattr(self.f.sdk,attribute,value)
            with self.subTest(attribute=attribute):
                with self.assertRaises(ValueError):self.scope.stop_and_verify(Mock(),self.context)
                with self.assertRaises(ValueError):self.scope.inspect_exit(self.context)
            setattr(self.f.sdk,attribute,previous)
        self.f.registry.protected_a2a_factory=None
        with self.assertRaisesRegex(ValueError,'OWNER_CHANGED'):self.scope.inspect_exit(self.context)
        self.lifecycle.stop_and_verify.assert_not_called();self.lifecycle.inspect_exit.assert_not_called()
