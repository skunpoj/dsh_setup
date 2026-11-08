"""Synthetic listener only: no socket, TLS handshake, database or credentials."""
import copy
import json
import ssl
from threading import RLock
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_exporter_activation import ProtectedExporterActivation,START,ACTIVE,STOP,INACTIVE
from scripts.a2a_provider_exporter import TLSProviderMetadataQuery,ROUTE
from scripts.a2a_provider_runtime import ProviderCaptureRuntime


class ExporterActivationTests(TestCase):
    def setUp(self):
        from test_a2a_worker_retirement import WorkerRetirementTests
        self.f=WorkerRetirementTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.task=self.f.task;self.now=100
        api=self.f.controller.api
        self.identity=dict(kind='DSH_SCOPED_EXPORTER_IDENTITY_V1',origin='explicit-injected',subject='owner',
            namespace=api.namespace,namespaceUID=api.namespace_uid,generation='g1',certificateSha256='a'*64,approvalSha256='b'*64)
        self.placement=dict(namespace=api.namespace,namespaceUID=api.namespace_uid,podUID='33333333-3333-4333-8333-333333333333',
            workloadUID='44444444-4444-4444-8444-444444444444',environment='test',workloadRole='qualification')
        self.factory=SimpleNamespace(registry=self.f.registry,sdk=SimpleNamespace(subject='owner',generation='g1',api=api),
            placement=copy.deepcopy(self.placement),observe=lambda:copy.deepcopy(self.placement))
        tls=ssl.create_default_context();tls.minimum_version=ssl.TLSVersion.TLSv1_2
        self.connection=Mock(side_effect=AssertionError('no actual connection allowed'))
        query=TLSProviderMetadataQuery(origin='https://dsh-agent-task-controller.'+api.namespace+'.svc.cluster.local:9443',
            namespace=api.namespace,tls_context=tls,connection_factory=self.connection)
        self.runtime=SimpleNamespace(factory=self.factory,exporter=SimpleNamespace(source=self.f.f.capture.source,
            observe=self.f.f.capture.observe,read=lambda:dict(subject='owner',namespace=api.namespace,
                namespaceUID=api.namespace_uid,generation='g1',controllerCertificateSha256='a'*64,expiresAt=200)),
            query=query,handler=object(),clock=lambda:self.now)
        self.factory.provider_capture_runtime=self.runtime
        scope=dict(taskId=self.task.id,subject='owner',generation='g1',placement=copy.deepcopy(self.placement),
            source=copy.deepcopy(self.f.f.capture.source),identity=copy.deepcopy(self.identity),
            route=dict(origin=query.origin.geturl(),path=ROUTE,redirects=False))
        self.lease=dict(kind='DSH_EXPORTER_ACTIVATION_LEASE_V1',scope=scope,activationId='d'*32,expiresAt=200)
        self.state='inactive'
        self.listener=SimpleNamespace(observe=Mock(side_effect=self.observe),start_once=Mock(side_effect=self.start),
            stop_once=Mock(side_effect=self.stop))
        self.activation=self.make()

    def observe(self):
        return dict(kind='DSH_EXPORTER_LISTENER_OBSERVATION_V1',state=self.state,
            activationId=self.lease['activationId'],scope=copy.deepcopy(self.lease['scope']))

    def start(self,lease,*,handler):
        self.assertEqual(lease,self.lease);self.assertIs(handler,self.runtime.handler)
        self.assertTrue((self.task.directory/START).is_file());self.state='active'

    def stop(self,lease):
        self.assertEqual(lease,self.lease);self.assertTrue((self.task.directory/STOP).is_file());self.state='inactive'

    def make(self):
        return ProtectedExporterActivation(runtime=self.runtime,task=self.task,lease_reader=lambda:copy.deepcopy(self.lease),
            identity_observer=lambda:copy.deepcopy(self.identity),listener=self.listener)

    def restart(self):
        self.f.restart();self.task=self.f.task;self.factory.registry=self.f.registry
        self.activation=self.make()

    def test_disabled_construction_and_single_binding_do_not_start_listener(self):
        self.listener.observe.assert_not_called();self.listener.start_once.assert_not_called()
        installed=ProviderCaptureRuntime.install_activation(self.runtime,task=self.task,
            lease_reader=lambda:copy.deepcopy(self.lease),identity_observer=lambda:copy.deepcopy(self.identity),listener=self.listener)
        self.assertIs(self.factory.exporter_activation,installed)
        with self.assertRaisesRegex(ValueError,'NO_SECOND_LISTENER'):
            ProviderCaptureRuntime.install_activation(self.runtime,task=self.task,lease_reader=Mock(),identity_observer=Mock(),listener=self.listener)
        self.listener.start_once.assert_not_called();self.connection.assert_not_called()

    def test_clean_activation_reconstructs_saved_result_without_second_start(self):
        result=self.activation.activate();self.restart()
        self.assertEqual(self.activation.recover(),result)
        with self.assertRaisesRegex(ValueError,'NO_RESTART'):self.activation.activate()
        self.listener.start_once.assert_called_once();self.connection.assert_not_called()

    def test_restart_before_intent_allows_one_start_and_after_intent_refuses(self):
        self.restart();self.task.save.side_effect=OSError('synthetic commit failure')
        with self.assertRaises(OSError):self.activation.activate()
        self.restart()
        with self.assertRaises(FileNotFoundError):self.activation.recover()
        with self.assertRaisesRegex(ValueError,'NO_RESTART'):self.activation.activate()
        self.listener.start_once.assert_not_called()

    def test_start_failure_and_uncertain_restart_never_start_again(self):
        def lost(lease,*,handler):self.start(lease,handler=handler);raise TimeoutError('synthetic lost result')
        self.listener.start_once.side_effect=lost
        with self.assertRaises(TimeoutError):self.activation.activate()
        self.restart()
        with self.assertRaises(FileNotFoundError):self.activation.recover()
        self.assertFalse(self.activation.rollback_to_inactive()['applicationRollbackVerified'])
        self.assertEqual(self.state,'inactive');self.listener.start_once.assert_called_once()

    def test_active_result_commit_failure_preserves_recoverable_bytes(self):
        original=self.task.save.side_effect
        def save():
            if (self.task.directory/ACTIVE).exists():raise OSError('synthetic result commit failure')
            original()
        self.task.save.side_effect=save
        with self.assertRaises(OSError):self.activation.activate()
        self.restart();self.activation.recover();self.listener.start_once.assert_called_once()

    def test_expiry_stops_exact_listener_without_new_start_and_reconciles_rollback(self):
        self.activation.activate();self.now=201
        with self.assertRaisesRegex(ValueError,'LEASE_REQUIRED|PEER_POLICY'):self.activation.recover()
        result=self.activation.expire();self.restart()
        self.assertEqual(self.activation.recover_rollback(),result)
        self.assertEqual(result['observation']['state'],'inactive')
        self.listener.start_once.assert_called_once();self.listener.stop_once.assert_called_once()

    def test_uncertain_stop_recovery_is_observe_only(self):
        self.activation.activate()
        def lost(lease):self.stop(lease);raise TimeoutError('synthetic lost stop reply')
        self.listener.stop_once.side_effect=lost
        with self.assertRaises(TimeoutError):self.activation.rollback_to_inactive()
        self.restart();self.activation.recover_rollback()
        self.listener.stop_once.assert_called_once();self.listener.start_once.assert_called_once()
        with self.assertRaisesRegex(ValueError,'ROLLBACK_RESERVED'):self.activation.recover()

    def test_start_failure_before_effect_rolls_back_without_stop_or_restart(self):
        self.listener.start_once.side_effect=OSError('synthetic refused start')
        with self.assertRaises(OSError):self.activation.activate()
        self.restart();self.activation.rollback_to_inactive()
        self.listener.start_once.assert_called_once();self.listener.stop_once.assert_not_called()
        with self.assertRaisesRegex(ValueError,'NO_RESTART'):self.activation.activate()

    def test_uncertain_stop_still_active_and_stop_commit_failure_do_not_repeat_stop(self):
        self.activation.activate()
        self.listener.stop_once.side_effect=TimeoutError('synthetic no confirmed effect')
        with self.assertRaises(TimeoutError):self.activation.rollback_to_inactive()
        self.restart()
        with self.assertRaisesRegex(ValueError,'LISTENER_STATE'):self.activation.recover_rollback()
        self.listener.stop_once.assert_called_once()
        with self.assertRaises(FileExistsError):self.activation.rollback_to_inactive()

    def test_stop_intent_commit_failure_never_invokes_stop(self):
        self.activation.activate();self.task.save.side_effect=OSError('synthetic stop intent commit failure')
        with self.assertRaises(OSError):self.activation.rollback_to_inactive()
        self.restart()
        with self.assertRaisesRegex(ValueError,'LISTENER_STATE'):self.activation.recover_rollback()
        self.listener.stop_once.assert_not_called()

    def test_missing_secret_default_foreign_identity_and_expired_lease_refuse(self):
        original=copy.deepcopy(self.identity)
        for origin in ('Secret','default','environment','saved-session'):
            self.identity['origin']=origin
            with self.assertRaisesRegex(ValueError,'SCOPED_IDENTITY'):self.activation.activate()
        self.identity=copy.deepcopy(original);self.identity['subject']='foreign'
        with self.assertRaises(ValueError):self.activation.activate()
        self.identity=original;self.now=201
        with self.assertRaisesRegex(ValueError,'LEASE_REQUIRED|PEER_POLICY'):self.activation.activate()
        self.listener.start_once.assert_not_called()

    def test_redirected_route_foreign_listener_and_partial_intent_refuse(self):
        from urllib.parse import urlsplit
        self.runtime.query.origin=urlsplit('https://external.invalid')
        with self.assertRaises(ValueError):self.activation.activate()
        self.runtime.query.origin=urlsplit(self.lease['scope']['route']['origin'])
        self.listener.observe.side_effect=lambda:{**self.observe(),'activationId':'f'*32}
        with self.assertRaisesRegex(ValueError,'LISTENER_STATE'):self.activation.activate()
        self.listener.observe.side_effect=self.observe
        (self.task.directory/START).write_bytes(b'{')
        with self.assertRaises(ValueError):self.activation.recover()
        self.listener.start_once.assert_not_called()

    def test_missing_identity_stale_generation_peer_policy_and_cancelled_task_refuse(self):
        self.identity=None
        with self.assertRaisesRegex(ValueError,'SCOPED_IDENTITY'):self.activation.activate()
        self.identity=copy.deepcopy(self.lease['scope']['identity']);self.identity['generation']='old'
        with self.assertRaisesRegex(ValueError,'SCOPED_IDENTITY'):self.activation.activate()
        self.identity=copy.deepcopy(self.lease['scope']['identity'])
        old=self.runtime.exporter.read
        self.runtime.exporter.read=lambda:{**old(),'controllerCertificateSha256':'f'*64}
        with self.assertRaisesRegex(ValueError,'PEER_POLICY'):self.activation.activate()
        self.runtime.exporter.read=old;self.task.state='cancelling'
        with self.assertRaisesRegex(ValueError,'OWNER_REQUIRED'):self.activation.activate()
        self.listener.start_once.assert_not_called()

    def test_retirement_after_synthetic_activation_preserves_separate_receipts(self):
        self.activation.activate()
        result=self.f.retirement.retire(self.task,self.f.binding)
        self.assertTrue(result['resourceAbsent']);self.assertFalse(result['rollbackVerified'])
        self.assertEqual(self.state,'active')  # Retiring a worker never stops the controller listener.
        self.activation.rollback_to_inactive()
        self.f.controller.api.delete_pod_once.assert_called_once();self.f.f.query.assert_called_once()
