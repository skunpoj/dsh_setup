"""Explicit Test-only official SDK composition; no package/network bootstrap.

Absence keeps SDK disabled. A protected admitted scope factory supplies physical
isolation and the EXISTING model guard, not a parallel credential/model store.
This loader cannot admit Production and cannot manufacture acceptance receipts.
"""
import hashlib
from pathlib import Path
import re
import time
import types

from scripts.official_sdk_package_admission import protected_bytes, unique_json, verify_sdk_admission
from scripts.official_sdk_session import OfficialSDKSessionRunner

SOURCES = {
    "controller": "/opt/dsh/container/dsh-sdk-control.py",
    "peer": "/opt/dsh/scripts/official_sdk_control_peer.py",
    "session": "/opt/dsh/scripts/official_sdk_session.py",
    "packageAdmission": "/opt/dsh/scripts/official_sdk_package_admission.py",
    "bootstrap": "/opt/dsh/scripts/official_sdk_bootstrap.py",
    "deploymentObserver": "/opt/dsh/scripts/official_sdk_deployment_observer.py",
    "protectedControllerObserver": "/opt/dsh/scripts/a2a_controller_observer.py",
    "protectedFactoryContract": "/opt/dsh/scripts/a2a_factory_contract.py",
    "protectedSDKScopeFactory": "/opt/dsh/scripts/a2a_sdk_scope_factory.py",
    "protectedCLIScopeFactory": "/opt/dsh/scripts/a2a_cli_scope_factory.py",
    "protectedFactoryBudget": "/opt/dsh/scripts/a2a_factory_budget.py",
    "physicalCLILifecycle": "/opt/dsh/scripts/a2a_cli_lifecycle.py",
    "protectedCLIService": "/opt/dsh/scripts/a2a_cli_service.py",
    "privateA2AExecutor": "/opt/dsh/scripts/a2a_executor.py",
    "qualificationAPI": "/opt/dsh/scripts/official_sdk_test_api.py",
    "releaseVerifier": "/opt/dsh/scripts/official_sdk_release_admission.py",
    "executingIdentity": "/opt/dsh/scripts/official_sdk_executing_identity.py",
    "physicalSDKWorker": "/opt/dsh/scripts/a2a_sdk_worker.py",
    "physicalSDKTransport": "/opt/dsh/scripts/a2a_sdk_transport.py",
    "physicalSDKController": "/opt/dsh/scripts/a2a_sdk_controller.py",
    "physicalSDKLifecycle": "/opt/dsh/scripts/a2a_sdk_lifecycle.py",
    "physicalSDKPod": "/opt/dsh/scripts/a2a_sdk_worker_pod.py",
    "privateWorkerPod": "/opt/dsh/scripts/a2a_private_worker_pod.py",
    "physicalWorkerStream": "/opt/dsh/scripts/a2a_worker_stream.py",
    "physicalWorkerIdentity": "/opt/dsh/scripts/a2a_worker_identity.py",
    "physicalWorkerJournal": "/opt/dsh/scripts/a2a_worker_journal.py",
    "physicalWorkerReceipt": "/opt/dsh/scripts/a2a_worker_receipt.py",
    "physicalNamespaceWorker": "/opt/dsh/scripts/a2a_pid_namespace_worker.py",
    "modelGuard": "/opt/dsh/scripts/unattended_model_guard.py",
    "modelGuardSidecar": "/opt/dsh/container/dsh-task-guard-sidecar.py",
    "qualificationEntry": "/opt/dsh/container/dsh-native-qualification-broker.py",
    "nativeComposition": "/opt/dsh/scripts/native_qualification_compose.py",
    "taskBroker": "/opt/dsh/container/dsh-task-broker.py",
    "nativeInputs": "/opt/dsh/scripts/native_qualification_inputs.py",
    "nativeProviders": "/opt/dsh/scripts/native_qualification_providers.py",
    "modelGuardControl": "/opt/dsh/scripts/a2a_guard_control.py",
    "correlation": "/opt/dsh/scripts/dsh_correlation.py",
    "approvalBridge": "/opt/dsh/scripts/official_sdk_approval.py",
    "guardEndpointPolicy": "/opt/dsh/scripts/official_sdk_task.py",
    "physicalWorkerAPI": "/opt/dsh/scripts/a2a_worker_api.py",
    "physicalWorkerController": "/opt/dsh/scripts/a2a_worker_controller.py",
    "agentRuntimeCommands": "/opt/dsh/scripts/agent_runtime_commands.py",
    "modelReconciliation": "/opt/dsh/scripts/a2a_model_reconciliation.py",
    "providerCapture": "/opt/dsh/scripts/a2a_provider_capture.py",
    "providerExporter": "/opt/dsh/scripts/a2a_provider_exporter.py",
    "providerRuntime": "/opt/dsh/scripts/a2a_provider_runtime.py",
    "providerQueryJournal": "/opt/dsh/scripts/a2a_provider_query_journal.py",
    "workerRetirement": "/opt/dsh/scripts/a2a_worker_retirement.py",
    "exporterActivation": "/opt/dsh/scripts/a2a_exporter_activation.py",
    "spendMetadataStore": "/opt/dsh/scripts/a2a_spend_store.py",
}


def protected_source_path(value):
    if (not isinstance(value, str) or not value.startswith("/opt/dsh/scripts/")
            or ".." in Path(value).parts or "\\" in value or not value.endswith(".py")):
        raise ValueError("INVALID_OFFICIAL_SDK_SCOPE_SOURCE")
    return value


def exact_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) and value != "0" * 64


def load_factory(path, source):
    module = types.ModuleType("dsh_admitted_official_sdk_scope")
    module.__file__ = path
    exec(compile(source, path, "exec"), module.__dict__)
    factory = getattr(module, "build_official_sdk_scope", None)
    if not callable(factory): raise ValueError("OFFICIAL_SDK_SCOPE_FACTORY_REQUIRED")
    return factory


def configure(server, registry, path, *, qualification_allowed=False, reader=protected_bytes,
              package_check=verify_sdk_admission, factory_loader=load_factory,
              clock=time.time, workspace_root="/workspace", runner_factory=OfficialSDKSessionRunner,
              deployment_observer=None):
    if not path: return False
    # No UI/user field, permissive production flag or fallback can enable this.
    if qualification_allowed is not True:
        raise ValueError("OFFICIAL_SDK_TEST_ADMISSION_REQUIRED")
    # Must be supplied independently by the protected control-plane integration,
    # using actual API-observed Pod/workload/namespace UIDs and classification.
    # Never derive it from environment flags, this descriptor, browser input or
    # a caller-selected module. No default/fake observation exists.
    if not callable(deployment_observer):
        raise ValueError("INDEPENDENT_TEST_DEPLOYMENT_OBSERVER_REQUIRED")
    if path != "/etc/dsh-native-admission/official-sdk-server.json":
        raise ValueError("FIXED_OFFICIAL_SDK_SERVER_ADMISSION_REQUIRED")
    config_raw = reader(path, 65536)
    config = unique_json(config_raw)
    required = {"kind", "mode", "subject", "generation", "expiresAt", "sourceCommit",
        "imageDigest", "packageAdmissionSha256", "scopeModule", "scopeSha256", "sources", "deploymentBinding"}
    if (not isinstance(config, dict) or set(config) != required
            or config["kind"] != "DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1"
            or config["mode"] != "qualification"
            or type(config["expiresAt"]) not in (int, float)
            or not 0 < config["expiresAt"] - clock() <= 300
            or not re.fullmatch(r"[a-f0-9]{40}", str(config["sourceCommit"]))
            or config["sourceCommit"] == "0" * 40
            or not isinstance(config["imageDigest"], str)
            or not config["imageDigest"].startswith("sha256:")
            or not exact_hash(config["imageDigest"][7:])
            or not exact_hash(config["scopeSha256"])
            or not exact_hash(config["packageAdmissionSha256"])):
        raise ValueError("INVALID_OFFICIAL_SDK_SERVER_ADMISSION")
    for name in ("subject", "generation"):
        if not isinstance(config[name], str) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", config[name]):
            raise ValueError("INVALID_OFFICIAL_SDK_SERVER_IDENTITY")
    deployment = config["deploymentBinding"]
    keys = {"namespace", "namespaceUID", "podUID", "workloadUID", "environment", "workloadRole"}
    if (not isinstance(deployment, dict) or set(deployment) != keys
            or deployment["environment"] != "test" or deployment["workloadRole"] != "qualification"
            or not isinstance(deployment["namespace"], str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", deployment["namespace"])
            or any(not re.fullmatch(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                str(deployment[k])) for k in ("namespaceUID", "podUID", "workloadUID"))):
        raise ValueError("INVALID_TEST_DEPLOYMENT_BINDING")
    def check_deployment():
        observed = deployment_observer()
        if not isinstance(observed, dict) or observed != deployment:
            raise ValueError("NON_TEST_OR_FOREIGN_DEPLOYMENT_IDENTITY")
    check_deployment()
    package = package_check()
    if package["admissionSha256"] != config["packageAdmissionSha256"]:
        raise ValueError("OFFICIAL_SDK_PACKAGE_BINDING_CHANGED")
    if not isinstance(config["sources"], dict) or set(config["sources"]) != set(SOURCES):
        raise ValueError("OFFICIAL_SDK_CONTROLLER_SOURCE_BINDINGS_REQUIRED")
    for role, source_path in SOURCES.items():
        expected = config["sources"][role]
        if not exact_hash(expected) or hashlib.sha256(reader(source_path, 1024 * 1024)).hexdigest() != expected:
            raise ValueError("OFFICIAL_SDK_CONTROLLER_SOURCE_MISMATCH")
    module = protected_source_path(config["scopeModule"])
    source = reader(module, 1024 * 1024)
    if hashlib.sha256(source).hexdigest() != config["scopeSha256"]:
        raise ValueError("OFFICIAL_SDK_SCOPE_SOURCE_MISMATCH")
    # Verified source execution is limited to the protected scope factory. It
    # must not spawn during composition. Only a Task launch reservation permits
    # its start() method to invoke the isolated, admitted transport.
    factory = factory_loader(module, source)
    components = factory(registry=registry, admission=dict(config))
    if not isinstance(components, dict) or set(components) != {"scope", "guardFactory"}:
        raise ValueError("OFFICIAL_SDK_SCOPE_COMPONENTS_REQUIRED")
    def fresh_package():
        # Revoke an already configured service when its finite descriptor is
        # removed, replaced or expired; stale configuration cannot keep it on.
        if reader(path, 65536) != config_raw or not clock() < config["expiresAt"]:
            raise ValueError("OFFICIAL_SDK_SERVER_ADMISSION_REVOKED")
        check_deployment()
        # Do not trust source hashes echoed by an earlier supervisor readback.
        # Re-read every protected byte source, including this loader and scope,
        # on EVERY capabilities/task admission.
        for role, source_path in SOURCES.items():
            if hashlib.sha256(reader(source_path, 1024 * 1024)).hexdigest() != config["sources"][role]:
                raise ValueError("OFFICIAL_SDK_CONTROLLER_SOURCE_MISMATCH")
        if hashlib.sha256(reader(module, 1024 * 1024)).hexdigest() != config["scopeSha256"]:
            raise ValueError("OFFICIAL_SDK_SCOPE_SOURCE_MISMATCH")
        current = package_check()
        if current["admissionSha256"] != config["packageAdmissionSha256"]:
            raise ValueError("OFFICIAL_SDK_PACKAGE_BINDING_CHANGED")
        observation = components["scope"].admission_state(config["subject"], config["generation"])
        if (not isinstance(observation, dict)
                or observation.get("sourceCommit") != config["sourceCommit"]
                or observation.get("imageDigest") != config["imageDigest"]
                or observation.get("controllerSha256") != config["sources"]["controller"]
                or observation.get("scopeSha256") != config["scopeSha256"]):
            raise ValueError("OFFICIAL_SDK_SCOPE_IMAGE_BINDING_MISMATCH")
        return current
    service = runner_factory(subject=config["subject"], generation=config["generation"],
        guard_factory=components["guardFactory"], runtime_scope=components["scope"],
        admission_check=fresh_package, workspace_root=workspace_root)
    if service.qualified is not True:
        raise ValueError("OFFICIAL_SDK_SCOPE_NOT_FRESHLY_QUALIFIED")
    # Recover existing records without launching a replacement. If any remains
    # unresolved it already blocks Registry admission; never hide or delete it.
    for task in registry.tasks.values():
        if task.native_sdk is not None and task.native_sdk.get("subject") == config["subject"]:
            service.recover_task(config["subject"], task)
    server.sdk_service = service
    return True
