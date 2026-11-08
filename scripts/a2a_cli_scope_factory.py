"""Concrete CLI bridge to the existing protected factory and Task writer.

Composition is inert. Fresh finite admission permits launch; expiry never
prevents observation/stop of an already owned worker. No process/API fallback,
credential discovery, model retry, or second task journal exists here.
"""
import threading
from scripts.agent_runtime_commands import command_for
from scripts.a2a_factory_contract import ProtectedA2AFactory
from scripts.a2a_sdk_scope_factory import ProtectedSDKScope


class ProtectedCLIScope:
    def __init__(self, *, factory, admission):
        # Reuse the same verified source/image/package/placement descriptor.
        # SDK bootstrap must validate its bytes before supplying it here.
        self.identity = ProtectedSDKScope(factory=factory, admission=admission)
        self.factory = factory
        self.subject = factory.cli.subject
        self.lock = threading.RLock()
        self.bound = {}

    @property
    def qualified(self):
        try:
            self._identity()
            return self.identity.qualified
        except Exception:
            return False

    def _identity(self):
        self.identity._bindings()
        sdk, cli = self.factory.sdk, self.factory.cli
        if (cli.subject != self.subject or cli.api is not sdk.api
                or any(getattr(cli, key) != getattr(sdk, key)
                    for key in ('subject', 'image', 'source_commit', 'node_name'))
                or cli.execution_admission is not sdk.execution_admission):
            raise ValueError('CLI_SCOPE_CONTROLLER_IDENTITY_CHANGED')

    def _task(self, context, *, cleanup=False):
        self._identity()
        if cleanup:
            self.identity._bindings()
        else:
            self.identity._fresh()
        if not isinstance(context, dict):
            raise ValueError('EXACT_CLI_SCOPE_CONTEXT_REQUIRED')
        task = self.factory.lookup(context.get('stageId'))
        if task is None:
            raise ValueError('EXISTING_CLI_SCOPE_TASK_REQUIRED')
        expected = dict(subject=self.subject, stageId=task.id,
            correlationId=task.correlation_id, project=task.request['project'],
            runtime=task.request['runtime'])
        if (context != expected or task.authenticated_subject != self.subject
                or task.request.get('backend') != 'private'
                or task.request.get('runtime') not in {'claude', 'deepagents'}
                or getattr(task, 'a2a_cli_context', None) != expected):
            raise ValueError('FOREIGN_CLI_SCOPE_TASK_BINDING')
        return task

    def execute_once(self, context, command, project):
        task = self._task(context)
        with self.lock, task.persistence_lock:
            if self._task(context) is not task:
                raise ValueError('CLI_SCOPE_TASK_REPLACED')
            if task.id in self.bound:
                raise ValueError('CLI_SCOPE_CONSUMED_NO_REBIND')
            if task.state != 'running':
                raise ValueError('EXACT_RUNNING_CLI_SCOPE_REQUIRED')
            components = self.factory.bind(task)
            # The protected boundary independently derives the exact command
            # and workspace. Never rely solely on the downstream controller
            # or the caller having used the normal CLI service.
            broker_path = components['workspace']['brokerPath']
            expected = command_for(task.request['runtime'], task.request['prompt'],
                task.request['writes'], broker_path, task.id)
            if (not isinstance(project, str) or project != broker_path
                    or not isinstance(command, list) or command != expected):
                raise ValueError('CLI_SCOPE_COMMAND_OR_WORKSPACE_SUBSTITUTION')
            # Retain before transport; uncertainty must never re-dispatch.
            self.bound[task.id] = (task, components)
            frozen_context = dict(context)
        return components['lifecycle'].execute_once(frozen_context, expected, broker_path)

    def stop_and_verify(self, context):
        if not isinstance(context, dict) or 'operationId' not in context:
            raise ValueError('EXACT_CLI_STOP_OPERATION_REQUIRED')
        base = {k: v for k, v in context.items() if k != 'operationId'}
        task = self._task(base, cleanup=True)
        cancel = getattr(task, 'a2a_cli_cancel', None)
        if (not isinstance(cancel, dict) or cancel.get('status') != 'reserved'
                or context['operationId'] != cancel.get('operationId')):
            raise ValueError('EXACT_RESERVED_CLI_STOP_REQUIRED')
        with self.lock:
            record = self.bound.get(task.id)
        if record is not None:
            if record[0] is not task:
                raise ValueError('CLI_SCOPE_TASK_REPLACED')
            return record[1]['lifecycle'].stop_and_verify(context)
        # After controller restart, the native lifecycle validates the durable
        # worker/stop reservation. No fresh admission or launch is performed.
        return self.factory.cli_lifecycle.stop_and_verify(context)

    def observe_terminal(self, context):
        task = self._task(context, cleanup=True)
        with self.lock:
            record = self.bound.get(task.id)
        if record is not None:
            if record[0] is not task:
                raise ValueError('CLI_SCOPE_TASK_REPLACED')
            return record[1]['lifecycle'].observe_terminal(context)
        return self.factory.cli_lifecycle.observe_terminal(context)


def build_protected_cli_scope(*, registry, admission):
    factory = getattr(registry, 'protected_a2a_factory', None)
    if type(factory) is not ProtectedA2AFactory or factory.registry is not registry:
        raise ValueError('EXPLICIT_PROTECTED_FACTORY_BINDING_REQUIRED')
    return ProtectedCLIScope(factory=factory, admission=admission)


def build_private_a2a_executor(*, registry, admission, sdk_service):
    """Compose admitted SDK and CLI services without starting any task.

    The caller still verifies the full bootstrap descriptor, installs this
    executor into the existing authenticated broker, and independently admits
    accounting/retirement/rollback. Composition alone is not qualification.
    """
    from scripts.a2a_cli_service import ProtectedCLIService
    from scripts.a2a_executor import PrivateA2AExecutor
    scope = build_protected_cli_scope(registry=registry, admission=admission)
    if sdk_service is None or sdk_service.subject != scope.subject:
        raise ValueError('SAME_SUBJECT_SDK_SERVICE_REQUIRED')

    def workspace(project):
        scope._identity(); scope.identity._fresh()
        policy = scope.factory.dependencies['workspacePolicy'](scope.subject, project)
        if policy != scope.factory.cli.project_admission(scope.subject, project):
            raise ValueError('FACTORY_WORKSPACE_POLICY_CHANGED')
        return policy['brokerPath']

    cli = ProtectedCLIService(subject=scope.subject, supervisor=scope,
        workspace_resolver=workspace)
    return PrivateA2AExecutor(sdk_service=sdk_service, cli_service=cli)
