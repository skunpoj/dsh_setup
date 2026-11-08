"""Actual factory/CLI service composition with synthetic physical lifecycle.

No API, process, model, database or credential access. These are source tests.
"""
import copy
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_cli_scope_factory import build_protected_cli_scope, build_private_a2a_executor
from scripts.a2a_cli_service import ProtectedCLIService
from scripts.a2a_sdk_scope_factory import install_protected_a2a_factory, PATH
from scripts.agent_runtime_commands import command_for


class CLIScopeFactoryTests(TestCase):
    def setUp(self):
        from test_a2a_factory_contract import FactoryContractTests
        self.f = FactoryContractTests(); self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.task = self.f.task
        self.task.request['runtime'] = 'claude'
        self.task.a2a_cli_context = self.context = dict(subject='owner',
            stageId=self.task.id, correlationId=self.task.correlation_id,
            project='project', runtime='claude')
        self.config = dict(kind='DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1',
            mode='qualification', subject='owner', generation='generation-1',
            expiresAt=200, sourceCommit=self.f.sdk.source_commit,
            imageDigest='sha256:'+'a'*64, packageAdmissionSha256=self.f.sdk.package_hash,
            scopeModule=PATH, scopeSha256='e'*64, sources={'controller':'d'*64},
            deploymentBinding=copy.deepcopy(self.f.placement))
        self.lifecycle = Mock(); self.f.factory.cli_lifecycle = self.lifecycle
        install_protected_a2a_factory(registry=self.f.registry, factory=self.f.factory)
        self.scope = build_protected_cli_scope(registry=self.f.registry, admission=self.config)
        self.command = command_for('claude', self.task.request['prompt'], False,
            self.f.policy['brokerPath'], self.task.id)

    def launch(self):
        return self.scope.execute_once(self.context, self.command, self.f.policy['brokerPath'])

    def test_composition_is_inert_and_requires_exact_owner(self):
        self.assertTrue(self.scope.qualified)
        self.lifecycle.execute_once.assert_not_called(); self.task.save.assert_not_called()
        self.f.registry.protected_a2a_factory = None
        self.assertFalse(self.scope.qualified)
        with self.assertRaisesRegex(ValueError, 'BINDING_REQUIRED'):
            build_protected_cli_scope(registry=self.f.registry, admission=self.config)

    def test_executor_composition_uses_same_sdk_and_rejects_foreign_subject(self):
        sdk = Mock(subject='owner', qualified=True)
        executor = build_private_a2a_executor(registry=self.f.registry,
            admission=self.config, sdk_service=sdk)
        self.assertIs(executor.sdk_service, sdk)
        self.assertTrue(executor.qualified)
        sdk.run_task.assert_not_called(); self.lifecycle.execute_once.assert_not_called()
        self.task.save.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'SAME_SUBJECT'):
            build_private_a2a_executor(registry=self.f.registry,
                admission=self.config, sdk_service=Mock(subject='foreign'))

    def test_executor_dispatches_cli_through_actual_service_and_existing_factory(self):
        import threading
        self.f.lease['modelStartsAllowed'] = 1
        self.task.state = 'queued'; self.task.finished = threading.Event()
        self.lifecycle.execute_once.return_value = dict(self.context, exitCode=0,
            stopped=True, processExitVerified=True, descendantAbsenceVerified=True,
            scopeUid='synthetic-scope', output='synthetic checked output')
        sdk = Mock(subject='owner', qualified=True)
        executor = build_private_a2a_executor(registry=self.f.registry,
            admission=self.config, sdk_service=sdk)
        self.assertEqual(executor(self.task), 'synthetic checked output')
        self.assertEqual(self.task.state, 'completed')
        sdk.run_task.assert_not_called(); self.lifecycle.execute_once.assert_called_once()

    def test_budget_saved_before_one_launch_and_no_rebind(self):
        self.f.lease['modelStartsAllowed'] = 1
        events = []; self.task.save.side_effect = lambda: events.append('saved')
        self.lifecycle.execute_once.side_effect = lambda *args: events.append('launch')
        self.launch(); self.assertEqual(events, ['saved', 'launch'])
        with self.assertRaisesRegex(ValueError, 'NO_REBIND'): self.launch()
        self.lifecycle.execute_once.assert_called_once_with(self.context, self.command,
            self.f.policy['brokerPath'])

    def test_zero_allowance_or_fenced_task_never_launch(self):
        with self.assertRaisesRegex(ValueError, 'ALLOWANCE_EXHAUSTED'): self.launch()
        self.lifecycle.execute_once.assert_not_called()
        self.task.state = 'cancelled'
        self.scope = build_protected_cli_scope(registry=self.f.registry, admission=self.config)
        with self.assertRaisesRegex(ValueError, 'RUNNING'): self.launch()

    def test_transport_uncertainty_cannot_relaunch(self):
        self.f.lease['modelStartsAllowed'] = 1
        self.lifecycle.execute_once.side_effect = TimeoutError('synthetic observation timeout')
        with self.assertRaises(TimeoutError): self.launch()
        with self.assertRaisesRegex(ValueError, 'NO_REBIND'): self.launch()
        self.lifecycle.execute_once.assert_called_once()

    def test_substituted_command_refused_before_binding_or_budget(self):
        self.f.lease['modelStartsAllowed'] = 1
        with self.assertRaisesRegex(ValueError, 'SUBSTITUTION'):
            self.scope.execute_once(self.context, ['/bin/sh', '-c', 'wrong-command'],
                self.f.policy['brokerPath'])
        self.assertEqual(self.scope.bound, {})
        self.lifecycle.execute_once.assert_not_called(); self.task.save.assert_not_called()
        self.launch(); self.lifecycle.execute_once.assert_called_once()

    def test_substituted_workspace_refused_even_with_command_for_that_path(self):
        self.f.lease['modelStartsAllowed'] = 1
        wrong = '/broker/other-project'
        command = command_for('claude', self.task.request['prompt'], False, wrong, self.task.id)
        with self.assertRaisesRegex(ValueError, 'SUBSTITUTION'):
            self.scope.execute_once(self.context, command, wrong)
        self.assertEqual(self.scope.bound, {})
        self.lifecycle.execute_once.assert_not_called(); self.task.save.assert_not_called()

    def test_prompt_and_writes_mutation_refuses_stale_command(self):
        self.f.lease['modelStartsAllowed'] = 1
        self.task.request['prompt'] = 'changed synthetic prompt'
        with self.assertRaisesRegex(ValueError, 'SUBSTITUTION'): self.launch()
        self.task.request['prompt'] = 'synthetic bounded task'
        self.f.policy['writes'] = True
        self.task.request['writes'] = True
        with self.assertRaisesRegex(ValueError, 'SUBSTITUTION'): self.launch()
        self.assertEqual(self.scope.bound, {})
        self.lifecycle.execute_once.assert_not_called(); self.task.save.assert_not_called()

    def test_workspace_policy_drift_refuses_previous_path(self):
        self.f.lease['modelStartsAllowed'] = 1
        self.f.policy['brokerPath'] = '/broker/moved-project'
        with self.assertRaisesRegex(ValueError, 'SUBSTITUTION'):
            self.scope.execute_once(self.context, self.command, '/broker/project')
        self.assertEqual(self.scope.bound, {})
        self.lifecycle.execute_once.assert_not_called(); self.task.save.assert_not_called()

    def test_foreign_context_and_sdk_runtime_refuse(self):
        for field, value in [('subject','other'), ('stageId','f'*32),
                             ('correlationId','e'*32), ('runtime','sdk')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.scope.execute_once({**self.context, field:value}, self.command, '/broker/project')
        self.lifecycle.execute_once.assert_not_called()

    def test_expiry_stops_launch_but_allows_owned_stop_and_observation(self):
        self.f.lease['modelStartsAllowed'] = 1; self.launch()
        self.f.now = 201
        self.assertFalse(self.scope.qualified)
        self.task.a2a_cli_cancel = dict(operationId='f'*32, status='reserved')
        context = {**self.context, 'operationId':'f'*32}
        self.scope.stop_and_verify(context); self.scope.observe_terminal(self.context)
        self.lifecycle.stop_and_verify.assert_called_once_with(context)
        self.lifecycle.observe_terminal.assert_called_once_with(self.context)
        self.lifecycle.execute_once.assert_called_once()

    def test_recovery_without_inmemory_launch_only_observes_existing_worker(self):
        self.f.now = 201
        self.scope.observe_terminal(self.context)
        self.lifecycle.observe_terminal.assert_called_once_with(self.context)
        self.lifecycle.execute_once.assert_not_called(); self.task.save.assert_not_called()
        for dep in self.f.deps.values(): dep.assert_not_called()

    def test_cleanup_refuses_changed_controller_or_replaced_task(self):
        self.f.lease['modelStartsAllowed'] = 1; self.launch()
        old = self.f.cli.image; self.f.cli.image = 'registry.invalid/other@sha256:'+'f'*64
        self.assertFalse(self.scope.qualified)
        with self.assertRaisesRegex(ValueError, 'IDENTITY_CHANGED'):
            self.scope.observe_terminal(self.context)
        self.f.cli.image = old; self.f.task = copy.copy(self.task)
        with self.assertRaisesRegex(ValueError, 'TASK_REPLACED'):
            self.scope.observe_terminal(self.context)
        self.lifecycle.observe_terminal.assert_not_called()

    def test_stop_requires_exact_reserved_operation(self):
        self.task.a2a_cli_cancel = dict(operationId='f'*32, status='reserved')
        with self.assertRaisesRegex(ValueError, 'RESERVED'):
            self.scope.stop_and_verify({**self.context, 'operationId':'e'*32})
        self.lifecycle.stop_and_verify.assert_not_called()

    def test_real_cli_service_uses_bridge_for_both_runtimes(self):
        import threading
        for runtime in ('claude', 'deepagents'):
            with self.subTest(runtime=runtime):
                self.setUp()
                self.task.request['runtime'] = runtime
                self.task.state = 'queued'; self.task.finished = threading.Event()
                self.f.lease['modelStartsAllowed'] = 1
                self.context['runtime'] = runtime
                self.lifecycle.execute_once.return_value = dict(self.context, exitCode=0,
                    stopped=True, processExitVerified=True, descendantAbsenceVerified=True,
                    scopeUid='synthetic-scope', output='synthetic checked output')
                service = ProtectedCLIService(subject='owner', supervisor=self.scope,
                    workspace_resolver=lambda _: self.f.policy['brokerPath'])
                self.assertEqual(service.run_task('owner', self.task), 'synthetic checked output')
                self.assertEqual(self.task.state, 'completed')
                self.assertTrue(self.task.finished.is_set())
                self.lifecycle.execute_once.assert_called_once()
