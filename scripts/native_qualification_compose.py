"""Pure composition helpers for the native qualification broker (P1, A2A lane).

Everything here takes its dependencies as arguments: no environment, no file, no network, no Kubernetes call,
no thread and no process start. The entry point (a later P1 step) supplies real objects; the tests supply fakes.
Nothing here qualifies anything by itself: `PrivateA2AExecutor.qualified` still needs a qualified SDK service
and a qualified CLI service.
"""
import contextlib
import re
import time

from scripts.a2a_cli_service import ProtectedCLIService
from scripts.a2a_executor import PrivateA2AExecutor
from scripts.a2a_factory_contract import DEPENDENCIES, ProtectedA2AFactory
from scripts.a2a_sdk_controller import SDKWorkerController
from scripts.a2a_sdk_scope_factory import install_protected_a2a_factory
from scripts.a2a_worker_controller import WorkerController

ADMISSION_NOT_DELIVERED = "ADMISSION_NOT_DELIVERED"
MAX_WAIT_SECONDS = 240


def build_controllers(*, api, subject, generation, package_admission_sha256, image, source_commit, node_name,
                      project_admission, execution_admission):
    """One SDK controller and one CLI controller sharing ONE api object, subject, image, commit, node and admission."""
    common = dict(api=api, subject=subject, image=image, source_commit=source_commit, node_name=node_name,
                  project_admission=project_admission, execution_admission=execution_admission)
    return (SDKWorkerController(generation=generation, package_admission_sha256=package_admission_sha256, **common),
            WorkerController(**common))


def build_and_install_factory(*, registry, sdk_controller, cli_controller, task_lookup, placement_observer,
                              placement_binding, admission_reader, dependencies, clock=time.time):
    """Construct the protected A2A factory and bind it to the registry exactly once (no replacement)."""
    missing = DEPENDENCIES - set(dependencies)
    if missing:
        raise ValueError("COMPLETE_PROTECTED_FACTORY_DEPENDENCIES_REQUIRED")
    factory = ProtectedA2AFactory(registry=registry, sdk_controller=sdk_controller, cli_controller=cli_controller,
                                  task_lookup=task_lookup, placement_observer=placement_observer,
                                  placement_binding=placement_binding, admission_reader=admission_reader,
                                  dependencies=dependencies, clock=clock)
    install_protected_a2a_factory(registry=registry, factory=factory)
    return factory


def build_cli_service(*, subject, supervisor, workspace_resolver):
    return ProtectedCLIService(subject=subject, supervisor=supervisor, workspace_resolver=workspace_resolver)


def attach_executor(server, *, sdk_service, cli_service):
    """Assign server.a2a_executor once; nothing else in the repo does."""
    if getattr(server, "a2a_executor", None) is not None:
        raise ValueError("A2A_EXECUTOR_ALREADY_BOUND_NO_REPLACEMENT")
    if sdk_service is None or cli_service is None:
        raise ValueError("EXPLICIT_SDK_AND_CLI_SERVICES_REQUIRED")
    executor = PrivateA2AExecutor(sdk_service=sdk_service, cli_service=cli_service)
    server.a2a_executor = executor
    return executor


LOCAL_TASKS_DISABLED = "LOCAL_SUBPROCESS_TASKS_DISABLED_IN_QUALIFICATION"


def restrict_registry_to_native_paths(registry):
    """Refuse every request that the broker would run as a LOCAL subprocess of this uid-0 control-plane process.

    The stock Registry.create starts `task.run` (a subprocess inside the broker container) for any private runtime that is
    neither `sdk` nor a native sdk chain. In the qualification broker that process owns the root-only observer key and the
    admission files, so only the SDK service and the worker-Pod chains may run tasks. Idempotent refusal, not a rewrite.
    """
    if getattr(registry, "native_paths_only", False):
        raise ValueError("NATIVE_PATHS_ALREADY_RESTRICTED")
    original = registry.create

    def create(request, *args, **kwargs):
        private = request.get("backend", "private") == "private"
        runtimes = {request.get("runtime"), request.get("handoffRuntime")}
        native_chain = private and request.get("handoffRuntime") is not None and "sdk" in runtimes
        sdk_task = private and request.get("runtime") == "sdk"
        if not (native_chain or sdk_task):
            raise RuntimeError(LOCAL_TASKS_DISABLED)
        return original(request, *args, **kwargs)
    registry.create = create
    # Audit item A1: tasks RECOVERED from a persisted journal were loaded before this restriction. `Task.approve` would resume a
    # recovered non-native sdk task as a LOCAL subprocess (run(resume=True)) of this uid-0 process. Native tasks answer approvals
    # only through the SDK service (approve already returns False for them), so every recovered task without a native binding gets
    # approve and run refused. Defence in depth: the generated Job also mounts the state root on an empty emptyDir.
    def refuse_run(*_args, **_kwargs):
        raise RuntimeError(LOCAL_TASKS_DISABLED)
    with getattr(registry, "lock", None) or contextlib.nullcontext():
        for task in list(getattr(registry, "tasks", {}).values()):
            if getattr(task, "native_sdk", None) is None:
                task.approve = lambda: False
                task.run = refuse_run
    registry.native_paths_only = True


def wait_for_admission(path, *, deadline_seconds, stat, read_mtime, clock=time.time, sleep=time.sleep, interval=1.0):
    """Wait, bounded, until the late-bound server admission exists; never create or modify it.

    `stat(path)` returns True when a regular file exists; `read_mtime(path)` returns its mtime. The file must also
    be fresh: a descriptor older than MAX_WAIT_SECONDS is refused rather than used.
    """
    if not isinstance(deadline_seconds, (int, float)) or not 0 < deadline_seconds <= MAX_WAIT_SECONDS:
        raise ValueError("BOUNDED_ADMISSION_WAIT_REQUIRED")
    end = clock() + deadline_seconds
    while True:
        if stat(path):
            if clock() - read_mtime(path) > MAX_WAIT_SECONDS:
                raise ValueError("STALE_ADMISSION_REFUSED")
            return True
        if clock() >= end:
            raise ValueError(ADMISSION_NOT_DELIVERED)
        sleep(interval)


def parse_wait_seconds(value, default=120):
    """DSH_QUALIFICATION_WAIT_SECONDS: a plain integer 1..MAX_WAIT_SECONDS, otherwise the default is NOT used silently."""
    if value is None:
        return default
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,2}", value) or int(value) > MAX_WAIT_SECONDS:
        raise ValueError("BOUNDED_ADMISSION_WAIT_REQUIRED")
    return int(value)


# ----------------------------------------------------------------------------------------------------------------------
# Entry sequencing (still pure: every real object is injected; the entry script supplies the real ones)
# ----------------------------------------------------------------------------------------------------------------------
EXCLUDED_NODES_ENV = "DSH_QUALIFICATION_EXCLUDED_NODES"  # optional comma list set in the Job manifest; empty = no node is refused
OWN_NODE_UNAVAILABLE = "OWN_NODE_NAME_UNAVAILABLE"
OWN_NODE_EXCLUDED = "OWN_NODE_EXCLUDED"


def parse_excluded_nodes(value):
    """Nodes this broker must NOT run on, from the Job manifest. Not hard-coded: the survey found a one-node cluster, so whether
    any node is refused is a decision of the manifest (OpenShell generator), not of this file. Malformed entries are refused."""
    if value is None or value == "":
        return frozenset()
    if not isinstance(value, str):
        raise ValueError("EXCLUDED_NODES_INVALID")
    names = value.split(",")
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", n) for n in names):
        raise ValueError("EXCLUDED_NODES_INVALID")
    return frozenset(names)


def read_own_node_name(read_resource, *, namespace, pod_name, excluded=frozenset()):
    """The node this broker actually runs on, from its OWN Pod through the same fixed named-GET API the observer uses.

    The qualification Job is not node-pinned, so the controllers, the execution lease and the worker Pods must use the node the
    scheduler chose. Defence in depth: a node on the (optional) exclusion list is refused even if an affinity should have prevented it.
    """
    pod = read_resource("Pod", "v1", namespace, pod_name)
    node = (pod.get("spec") or {}).get("nodeName") if isinstance(pod, dict) else None
    if not isinstance(node, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", node):
        raise ValueError(OWN_NODE_UNAVAILABLE)
    if node in excluded:
        raise ValueError(OWN_NODE_EXCLUDED)
    return node


BINDING_KEYS = frozenset({"namespace", "namespaceUID", "podUID", "workloadUID", "environment", "workloadRole"})
EXIT_ADMISSION_NOT_DELIVERED = 3
EXIT_PROVIDER_RUNTIME_NOT_COMPOSED = 4
EXIT_REFUSED = 1
PROVIDER_RUNTIME_NOT_COMPOSED = "PROTECTED_PROVIDER_RUNTIME_NOT_COMPOSED"


def parse_admission_binding(raw, *, unique_json):
    """Only what the observer needs from the late-bound descriptor; configure() re-validates the whole file."""
    value = unique_json(raw)
    if not isinstance(value, dict) or not isinstance(value.get("deploymentBinding"), dict):
        raise ValueError("SERVER_ADMISSION_BINDING_REQUIRED")
    binding = value["deploymentBinding"]
    if set(binding) != BINDING_KEYS:
        raise ValueError("SERVER_ADMISSION_BINDING_REQUIRED")
    digest = value.get("imageDigest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("SERVER_ADMISSION_IMAGE_DIGEST_REQUIRED")
    return binding, digest


def build_observer(*, admission_raw, pod_name, namespace, job_name, container_name, unique_json,
                   requester_factory, api_factory, identity_factory, observer_factory):
    """Observer for the executing Job/Pod; every UID comes from the descriptor and is then re-verified against the API."""
    binding, digest = parse_admission_binding(admission_raw, unique_json=unique_json)
    if namespace != binding["namespace"]:
        raise ValueError("EXECUTING_NAMESPACE_BINDING_MISMATCH")
    requester = requester_factory(namespace=namespace, pod_name=pod_name, job_name=job_name)
    api = api_factory(requester, namespace=namespace, pod_name=pod_name, job_name=job_name)
    identity = identity_factory(read_resource=api.read_resource, namespace=namespace,
                                namespace_uid=binding["namespaceUID"], pod_name=pod_name, pod_uid=binding["podUID"],
                                container_name=container_name)
    return observer_factory(read_resource=api.read_resource, executing_identity=identity, namespace=namespace,
                            namespace_uid=binding["namespaceUID"], pod_name=pod_name, pod_uid=binding["podUID"],
                            job_name=job_name, job_uid=binding["workloadUID"], container_name=container_name,
                            image_digest=digest)


def run_entry(*, env, wait, read_admission, read_downward, build_observer_for, read_node_name, load_providers, load_broker,
              configure_sdk, log):
    """The whole entry sequence; returns an exit code and never raises. Order matters:
    1 wait (never writes) -> 2 observer from the descriptor, then the node this Pod runs on -> 3 registry restricted to native paths, protected providers install the factory
    -> 4 configure(SDK service, observer) -> 5 executor assignment -> 6 serve."""
    try:
        if env.get("DSH_NATIVE_QUALIFICATION_MODE") != "1":
            raise ValueError("NATIVE_QUALIFICATION_MODE_REQUIRED")
        seconds = parse_wait_seconds(env.get("DSH_QUALIFICATION_WAIT_SECONDS"))
        try:
            wait(seconds)
        except ValueError as error:
            if str(error) == ADMISSION_NOT_DELIVERED:
                log(ADMISSION_NOT_DELIVERED)
                return EXIT_ADMISSION_NOT_DELIVERED
            raise
        pod_name, namespace = read_downward()
        observer = build_observer_for(admission_raw=read_admission(), pod_name=pod_name, namespace=namespace,
                                      job_name=env.get("DSH_QUALIFICATION_JOB_NAME", ""),
                                      container_name=env.get("DSH_QUALIFICATION_CONTAINER_NAME", ""))
        node_name = read_node_name(observer, namespace=namespace, pod_name=pod_name,
                                   excluded=parse_excluded_nodes(env.get(EXCLUDED_NODES_ENV)))
        providers = load_providers()
        if providers is None:
            log(PROVIDER_RUNTIME_NOT_COMPOSED)
            return EXIT_PROVIDER_RUNTIME_NOT_COMPOSED
        broker = load_broker()
        restrict_registry_to_native_paths(broker.REGISTRY)
        server = broker.make_server()
        services = providers.install(registry=broker.REGISTRY, namespace=namespace, node_name=node_name, env=dict(env),
                                     observer=observer)
        if not configure_sdk(server, broker.REGISTRY, observer):
            raise ValueError("SDK_SERVICE_NOT_CONFIGURED")
        attach_executor(server, sdk_service=server.sdk_service, cli_service=services["cli_service"])
        server.serve_forever()
        return 0
    except (ValueError, OSError, KeyError) as error:
        log("REFUSED " + str(error)[:120])
        return EXIT_REFUSED
