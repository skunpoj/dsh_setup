"""Protected provider runtime of the native qualification broker (D10 option (b): REDUCED ASSURANCE, first SDK proof only).

`install(registry, namespace, node_name, env, observer)` is called by the entry after the node name is known and before the SDK
service is configured. It reads the operator-delivered files, builds the worker API, the two controllers, the factory with its
six dependencies, the provider capture and the retirement, binds the factory to the registry once, and returns the CLI service.

Reduced assurance, stated plainly: provider rows come from an operator-delivered file (see native_qualification_inputs), and the
cleanup-only retirement admission is DERIVED here from the task's own retained worker record, not delivered by an operator. The
controllers still verify the live Pod UID, the guard ledger and the provider rows EXACTLY. Every verdict that uses this module
must be labelled "reduced assurance". Nothing here opens a socket or reads a file at import time; `install` does that.
"""
import copy
import ssl
import time

from scripts import native_qualification_compose as compose
from scripts import native_qualification_inputs as inputs
from scripts.a2a_cli_scope_factory import ProtectedCLIScope
from scripts.a2a_provider_capture import TaskProviderCapture
from scripts.a2a_worker_api import WorkerAPI
from scripts.a2a_worker_retirement import INTENT, TaskWorkerRetirement

KUBERNETES_ORIGIN = "https://kubernetes.default.svc"
KUBERNETES_CA = "/etc/dsh-native-identity/kubernetes-ca.crt"
WORKER_TOKEN = "/run/dsh-worker-identity/token"
ADMISSION = "/etc/dsh-native-admission/official-sdk-server.json"
GUARD_URL = "http://127.0.0.1:4001/v1"
CLEANUP_SECONDS = 120


class WorkerGuardHandle:
    """The task's guard lives in the worker Pod sidecar (127.0.0.1:4001); the broker side only needs this binding handle.
    Its exit does nothing: the controller's single fence-and-snapshot drain and the retirement do the teardown."""
    temperature = 0

    def __init__(self, task_id, correlation_id, base_url=GUARD_URL):
        self.task_id, self.correlation_id, self.base_url = task_id, correlation_id, base_url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def guard_factory(task, binding):
    if binding.get("taskId") != task.id or binding.get("correlationId") != task.correlation_id:
        raise ValueError("EXACT_GUARD_TASK_BINDING_REQUIRED")
    return WorkerGuardHandle(task.id, task.correlation_id)


def assemble(*, registry, namespace, node_name, observer, reader, unique_json, make_api, clock=time.time,
             descriptor_path=ADMISSION, lease_path=inputs.LEASE_FILE, policy_path=inputs.WORKSPACE_POLICY_FILE,
             rows_path=inputs.PROVIDER_ROWS_DIR):
    descriptor = inputs.read_json(reader, descriptor_path, unique_json)
    lease = inputs.read_json(reader, lease_path, unique_json)
    if not isinstance(descriptor, dict) or not isinstance(lease, dict):
        raise ValueError("EXACT_ADMISSION_AND_LEASE_OBJECTS_REQUIRED")
    binding = descriptor.get("deploymentBinding")
    if not isinstance(binding, dict) or binding.get("namespace") != namespace or lease.get("nodeName") != node_name:
        raise ValueError("EXACT_PLACEMENT_FOR_THIS_POD_REQUIRED")
    subject, generation = descriptor["subject"], descriptor["generation"]
    image, commit = lease.get("image"), descriptor["sourceCommit"]
    if (lease.get("subject") != subject or lease.get("generation") != generation or lease.get("sourceCommit") != commit
            or lease.get("namespaceUID") != binding["namespaceUID"] or not isinstance(image, str)
            or image.split("@")[-1] != descriptor["imageDigest"]):
        raise ValueError("EXECUTION_LEASE_DESCRIPTOR_MISMATCH")
    policy = inputs.workspace_policy_lookup(reader=reader, unique_json=unique_json, path=policy_path)
    lease_read = inputs.lease_reader(reader=reader, unique_json=unique_json, path=lease_path)
    values = dict(subject=subject, namespace=namespace, namespaceUID=binding["namespaceUID"], image=image,
                  sourceCommit=commit, nodeName=node_name)
    admit = inputs.make_execution_admission(controller_values=values, lease_reader=lease_read, clock=clock)
    api = make_api(namespace, binding["namespaceUID"])
    sdk, cli = compose.build_controllers(api=api, subject=subject, generation=generation,
        package_admission_sha256=descriptor["packageAdmissionSha256"], image=image, source_commit=commit,
        node_name=node_name, project_admission=policy, execution_admission=admit)

    def observe_source():
        return inputs.provider_source_binding(reader=reader, source_commit=commit, image_digest=descriptor["imageDigest"])
    source = observe_source()
    query = inputs.RowsDirectoryProviderQuery(reader=reader, unique_json=unique_json, directory=rows_path,
                                               source_observer=observe_source)
    captures = {runtime: TaskProviderCapture(controller=controller, generation=generation, query_metadata=query,
                                              source_observer=observe_source, source_binding=source)
                for runtime, controller in (("sdk", sdk), ("claude", cli), ("deepagents", cli))}

    def capture(task, bound):
        one = captures.get(task.request.get("runtime"))
        if one is None:
            raise ValueError("UNSUPPORTED_PROVIDER_CAPTURE_RUNTIME")
        with task.persistence_lock:
            reserved = getattr(task, "a2a_cli_worker", {}).get("providerCaptureOperationId")
        return one.recover(task, bound) if reserved is not None else one(task, bound)

    def cleanup_admission(task, bound):
        worker = getattr(task, "a2a_cli_worker", None)
        if not isinstance(worker, dict):
            raise ValueError("EXACT_RETIREMENT_WORKER_REQUIRED")
        scope = dict(binding=copy.deepcopy(bound), namespace=worker.get("namespace"), namespaceUID=worker.get("namespaceUID"),
                     podName=worker.get("podName"), podUID=worker.get("podUID"),
                     source=copy.deepcopy(source), captureSha256=worker.get("providerCaptureSha256"))
        return dict(scope=scope, expiresAt=clock() + CLEANUP_SECONDS, cleanupOnly=True)

    def retire(task, bound):
        one = captures.get(task.request.get("runtime"))
        if one is None:
            raise ValueError("UNSUPPORTED_RETIREMENT_RUNTIME")
        retirement = TaskWorkerRetirement(registry=registry, controller=one.controller, capture=one,
                                          admission_reader=lambda: cleanup_admission(task, bound), clock=clock)
        path = task.directory / INTENT
        if path.exists() or path.is_symlink():
            return retirement.recover(task, bound)
        return retirement.retire(task, bound)

    dependencies = dict(workspacePolicy=policy, executionAdmission=admit, guardFactory=guard_factory,
                        providerCapture=capture, retirement=retire, rollback=inputs.RollbackRecorder())

    def lookup(task_id):
        with registry.lock:
            return registry.tasks.get(task_id)

    factory = compose.build_and_install_factory(registry=registry, sdk_controller=sdk, cli_controller=cli, task_lookup=lookup,
        placement_observer=observer, placement_binding=copy.deepcopy(binding), admission_reader=lease_read,
        dependencies=dependencies, clock=clock)
    scope = ProtectedCLIScope(factory=factory, admission=copy.deepcopy(descriptor))

    def workspace(project):
        found = policy(subject, project)
        if found != cli.project_admission(subject, project):
            raise ValueError("FACTORY_WORKSPACE_POLICY_CHANGED")
        return found["brokerPath"]

    return {"cli_service": compose.build_cli_service(subject=subject, supervisor=scope, workspace_resolver=workspace),
            "factory": factory}


def real_api(namespace, namespace_uid):
    context = ssl.create_default_context(cafile=KUBERNETES_CA)

    def authorization():
        with open(WORKER_TOKEN, "rb") as handle:
            return "Bearer " + handle.read(16384).decode("ascii").strip()
    return WorkerAPI(origin=KUBERNETES_ORIGIN, tls_context=context, authorization=authorization, namespace=namespace,
                     namespace_uid=namespace_uid)


def install(*, registry, namespace, node_name, env, observer):
    from scripts.official_sdk_package_admission import protected_bytes, unique_json
    return assemble(registry=registry, namespace=namespace, node_name=node_name, observer=observer,
                    reader=protected_bytes, unique_json=unique_json, make_api=real_api)
