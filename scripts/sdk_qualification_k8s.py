"""Kubernetes objects for the native SDK qualification run (OpenShell lane, P1). Generates and checks; NEVER applies anything.

What the protected modules force (read in source, enforced again here and proven by running the real modules in the tests):
  * official_sdk_deployment_observer: a Namespace labelled runtime-environment=test and runtime-purpose=qualification; a Job with backoffLimit 0, parallelism 1,
    completions 1, activeDeadlineSeconds 1..300, not suspended, restartPolicy Never; ONE container whose image ends with the admitted digest; labels on Namespace,
    Job, Job template and Pod; a Pod controlled by that Job.
  * official_sdk_executing_identity: NO initContainers and no ephemeral containers; the broker container has allowPrivilegeEscalation false, readOnlyRootFilesystem
    true, capabilities drop ALL and none added; a downwardAPI volume named exactly dsh-executing-identity with defaultMode 0444 and the three fixed items, mounted with
    exactly three readOnly subPath mounts under /run/dsh-executing-identity.
  * protected_bytes / protected_identity_file: every path component, including the file, must be a root-owned regular file or directory that is not a symlink and
    not group/other writable. Kubelet projects ConfigMap, Secret, downward-API and projected volumes as SYMLINKS, so every protected file here is a subPath file mount
    (a regular file) and the one late-bound file (the server admission, which embeds the Pod and Job UIDs) is written into a memory-backed emptyDir by the operator.
  * Root-owned files and a 0600 private key mean the broker process is uid 0, so the namespace needs a Pod Security level that allows it (baseline).
The checker accepts LIVE read-backs: the API server omits fields that are false by default, so an absent field equals its default.
"""
import base64
import copy
import hashlib
import ipaddress
import json
import re

from scripts import official_sdk_deployment_observer as observer
from scripts import official_sdk_executing_identity as identity

KIND = "DSH_SDK_QUALIFICATION_K8S_V1"
NAMESPACE = re.compile(r"dsh-a2a-[a-z0-9][a-z0-9-]{0,54}")
NAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,50}[a-z0-9])?")
IMAGE = re.compile(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}")
SHA256 = re.compile(r"[a-f0-9]{64}")
WHEEL_NAME = "deepseek_harness_sdk-0.2.2a2-py3-none-any.whl"
SERVICE_ACCOUNT = "sdk-qualification"
ADMISSION_DIR = "/etc/dsh-native-admission"
IDENTITY_DIR = "/etc/dsh-native-identity"
WORKER_TOKEN = "/run/dsh-worker-identity/token"
BROKER_LABEL, BROKER_VALUE = "app.kubernetes.io/component", "qualification-broker"
WORKER_LABEL, WORKER_VALUE = "app.kubernetes.io/part-of", "dsh-a2a-qualification"   # set by a2a_private_worker_pod
CLIENT_PORT = 7682
LITELLM_PORT = 4000
ROUTES = ("secret-client-certificate", "projected-token")
GIB = 1024 ** 3
WORKSPACE_CLAIM = "dsh-a2a-qual-workspace"
TASK_CREDENTIAL_SECRET = "dsh-a2a-qual-task-credential"   # created per run by the operator; NEVER generated or mounted into the broker
WORKSPACE_SUBPATH = "qual"
TASK_STATE_MOUNT = "/state"
BROKER_TOKEN_SECRET = "dsh-a2a-test-broker-token"   # created by the operator/user (>= 32 chars, key "token"); only NAMED here, never generated, read or printed
BROKER_TOKEN_FILE = "/runtime-tokens/token"        # DSH_TASK_TOKEN_FILE of container/dsh-task-broker.py: without it every request is refused (fail closed)
TASK_STATE_ROOT = TASK_STATE_MOUNT + "/web-tasks"   # DSH_TASK_STATE_ROOT of container/dsh-task-broker.py; Registry.__init__ loads task.json files found here
WORKSPACE_POLICY_FILE = "a2a-workspace-policy.json"
# The test client (OpenShell lane, after USER "make it live now"): ONE Pod that only runs the A2A lane's hash-pinned case driver against the broker on 7682.
# It has no API identity, no workspace, no task credential and no LiteLLM route; its only egress is the broker Pod, its only Secret is the broker token (by name).
CLIENT_POD = "sdk-qualification-client"
CLIENT_CONTAINER = "client"
CLIENT_SCRIPT_CONFIGMAP = "dsh-a2a-qual-client-script"
CLIENT_FILES = ("a2a_through_openshell_test.py", "native_case_driver.py")   # the A2A lane's files, hash-pinned by the contract
CLIENT_MOUNT = "/client"
CLIENT_EVIDENCE = "/evidence"
CLIENT_DEADLINE_SECONDS = 3600
DECIDED_NAMESPACE = "dsh-a2a-qual"            # ORCH-DECISION-P2-COMPOSITION
ENGINE_NODE = "dagpu-gn-p1"                 # the ONLY node of the cluster (survey 10 Nov): GPU/engine node, so nothing can be excluded from it
STORAGE_CLASS = "topolvm-immediate"           # the only Immediate-binding class (survey); node-local LVM on the single node
MAX_WORKSPACE_BYTES = GIB                     # ORCH-DECISION-P2-REVISED-AFTER-SURVEY: a PVC only where unavoidable, <= 1Gi
CONTAINER_MAX = {"cpu": 4, "memory": 8 * GIB}   # LimitRange pattern of dsh-openshell-test-20261102
# one broker (2 CPU / 4Gi, requests = limits) + one test client + one worker with its guard (A2A-LANE-ON-REVISED-P2-QUOTA-FACTS: worker 100m/256Mi req, 1 CPU/1Gi limit;
# guard 50m/64Mi req, 250m/256Mi limit; client 100m/256Mi req, 1 CPU/1Gi limit) with headroom. Ephemeral storage is deliberately NOT in the quota.
QUOTA = {"requests.cpu": "3", "limits.cpu": "5", "requests.memory": str(6 * GIB), "limits.memory": str(8 * GIB), "pods": 6, "configmaps": 10, "secrets": 4,
         "count/jobs.batch": 2, "persistentvolumeclaims": 1}
EXCLUDED_NODES_ENV = "DSH_QUALIFICATION_EXCLUDED_NODES"   # optional; read by the A2A entry (c4334e3); empty list = no node refused
INTERPRETERS = ("python3", "/usr/local/bin/python3", "/opt/dsh/deepagents/bin/python")


class SpecError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise SpecError(code)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_spec(spec):
    required = {"namespace", "jobName", "containerName", "image", "command", "identityRoute", "observerSubject", "podSecurity",
                "activeDeadlineSeconds", "resources", "wheelSha256", "nodeName", "excludedNodes", "workspaceBytes", "workspaceStorageClass", "clientPodLabels",
                "apiServerTargets", "litellmPodLabels"}
    _require(isinstance(spec, dict) and set(spec) == required, "SPEC_KEYS_EXACT_REQUIRED")
    _require(isinstance(spec["namespace"], str) and NAMESPACE.fullmatch(spec["namespace"]), "A2A_OWNED_TEST_NAMESPACE_REQUIRED")
    for key in ("jobName", "containerName", "observerSubject"):
        _require(isinstance(spec[key], str) and NAME.fullmatch(spec[key]), "BAD_" + key.upper())
    _require(isinstance(spec["image"], str) and IMAGE.fullmatch(spec["image"]), "IMMUTABLE_IMAGE_REQUIRED")
    command = spec["command"]
    _require(isinstance(command, list) and len(command) == 3 and all(isinstance(x, str) and x for x in command), "COMMAND_REQUIRED")
    # isolated interpreter, no PYTHONPATH, no -c/-m: the entry point is one protected file inside the image (hashed in the admission as a source role)
    _require(command[0] in INTERPRETERS and command[1] == "-I", "ISOLATED_PYTHON_REQUIRED")
    _require(command[2].startswith("/opt/dsh/container/") and command[2].endswith(".py") and ".." not in command[2].split("/"), "PROTECTED_ENTRY_POINT_PATH_REQUIRED")
    _require(spec["identityRoute"] in ROUTES, "IDENTITY_ROUTE_UNKNOWN")
    _require(spec["podSecurity"] == "baseline", "BASELINE_POD_SECURITY_REQUIRED_FOR_ROOT_OWNED_PROTECTED_FILES")
    _require(type(spec["activeDeadlineSeconds"]) is int and 0 < spec["activeDeadlineSeconds"] <= 300, "DEADLINE_1_TO_300_REQUIRED")
    resources = spec["resources"]
    _require(isinstance(resources, dict) and set(resources) == {"cpu", "memoryBytes", "ephemeralBytes"} and all(type(v) is int and v > 0 for v in resources.values()), "BAD_RESOURCES")
    _require(resources["cpu"] <= CONTAINER_MAX["cpu"] and resources["memoryBytes"] <= CONTAINER_MAX["memory"], "RESOURCES_ABOVE_THE_LIMITRANGE_MAX")
    _require(isinstance(spec["wheelSha256"], str) and SHA256.fullmatch(spec["wheelSha256"]) and spec["wheelSha256"] != "0" * 64, "BAD_WHEEL_SHA256")
    _require(spec["nodeName"] is None or (isinstance(spec["nodeName"], str) and re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", spec["nodeName"])), "BAD_NODE")
    excluded = spec["excludedNodes"]
    _require(isinstance(excluded, list) and all(isinstance(n, str) and re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", n) for n in excluded)
             and len(set(excluded)) == len(excluded), "EXCLUDED_NODES_LIST_REQUIRED")
    _require(ENGINE_NODE not in excluded, "THE_ONLY_NODE_CANNOT_BE_EXCLUDED")
    _require(spec["nodeName"] not in excluded, "NODE_PIN_IS_AN_EXCLUDED_NODE")
    _require(type(spec["workspaceBytes"]) is int and 0 < spec["workspaceBytes"] <= MAX_WORKSPACE_BYTES, "BAD_WORKSPACE")
    _require(spec["workspaceStorageClass"] == STORAGE_CLASS, "STORAGE_CLASS_MUST_BE_THE_IMMEDIATE_BINDING_ONE")
    for key in ("clientPodLabels", "litellmPodLabels"):
        labels = spec[key]
        _require(isinstance(labels, dict) and labels and all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in labels.items()), "BAD_" + key.upper())
    targets = spec["apiServerTargets"]
    _require(isinstance(targets, list) and 1 <= len(targets) <= 2 and all(isinstance(t, dict) and set(t) == {"cidr", "port"} for t in targets), "BAD_API_SERVER_TARGETS")
    for target in targets:
        try:
            network = ipaddress.ip_network(target["cidr"], strict=True)
        except (ValueError, TypeError):
            raise SpecError("BAD_API_SERVER_CIDR") from None
        _require(network.version == 4 and network.prefixlen >= 24, "API_SERVER_CIDR_MUST_BE_A_NARROW_IPV4_RANGE")
        _require(type(target["port"]) is int and target["port"] in (443, 6443), "API_SERVER_PORT_443_OR_6443")
    _require(len({(t["cidr"], t["port"]) for t in targets}) == len(targets), "API_SERVER_TARGETS_DISTINCT")


def _labels(spec, extra=None):
    labels = {observer.ENVIRONMENT: "test", observer.ROLE: "qualification", "app.kubernetes.io/managed-by": "dsh-sdk-qualification-k8s"}
    labels.update(extra or {})
    return labels


def _meta(spec, name, **extra):
    value = {"name": name, "namespace": spec["namespace"], "labels": _labels(spec)}
    value.update(extra)
    return value


def _observer_subjects(spec):
    if spec["identityRoute"] == "secret-client-certificate":
        return [{"kind": "User", "apiGroup": "rbac.authorization.k8s.io", "name": spec["observerSubject"]}]
    return [{"kind": "ServiceAccount", "name": SERVICE_ACCOUNT, "namespace": spec["namespace"]}]


def _worker_subjects(spec):
    return [{"kind": "ServiceAccount", "name": SERVICE_ACCOUNT, "namespace": spec["namespace"]}]


def _dns_rule():
    return {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}],
            "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]}


def _binding(kind, name, role_kind, role_name, subjects, spec, namespaced=True):
    value = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": kind, "metadata": {"name": name, "labels": _labels(spec)},
             "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": role_kind, "name": role_name}, "subjects": subjects}
    if namespaced:
        value["metadata"]["namespace"] = spec["namespace"]
    return value


def _mounts_and_volumes(spec):
    container_mounts = [
        {"name": "admission", "mountPath": ADMISSION_DIR},
        {"name": "package-admission", "mountPath": ADMISSION_DIR + "/official-sdk-package.json", "subPath": "official-sdk-package.json", "readOnly": True},
        {"name": "sdk-wheel", "mountPath": "/packages/approved/python/" + WHEEL_NAME, "subPath": WHEEL_NAME, "readOnly": True},
        {"name": "workspace", "mountPath": "/workspace"},
        {"name": "broker-token", "mountPath": BROKER_TOKEN_FILE, "subPath": "token", "readOnly": True},
        {"name": "task-state", "mountPath": TASK_STATE_MOUNT},   # A1: the task journal root is an EMPTY memory emptyDir, so no seeded journal can exist
        {"name": "workspace-policy", "mountPath": ADMISSION_DIR + "/" + WORKSPACE_POLICY_FILE, "subPath": WORKSPACE_POLICY_FILE, "readOnly": True},
    ]
    # exactly the mounts official_sdk_executing_identity compares against
    container_mounts += [{"name": identity.VOLUME, "mountPath": identity.ROOT.as_posix() + "/" + field, "subPath": field, "readOnly": True} for field in identity.FIELDS]
    volumes = [
        {"name": "admission", "emptyDir": {"medium": "Memory", "sizeLimit": "1Mi"}},
        {"name": "package-admission", "configMap": {"name": "sdk-package-admission", "defaultMode": 0o444}},
        {"name": "sdk-wheel", "configMap": {"name": "sdk-wheel", "defaultMode": 0o444}},
        # A2A lane D12 correction: brokerPath is only a string on the broker side, so the broker keeps a scratch emptyDir; only the WORKER Pods mount the claim
        {"name": "workspace", "emptyDir": {"medium": "Memory", "sizeLimit": str(spec["workspaceBytes"])}},
        {"name": "task-state", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}},
        {"name": "broker-token", "secret": {"secretName": BROKER_TOKEN_SECRET, "defaultMode": 0o400, "items": [{"key": "token", "path": "token", "mode": 0o400}]}},
        {"name": "workspace-policy", "configMap": {"name": "a2a-workspace-policy", "defaultMode": 0o444}},
        {"name": identity.VOLUME, "downwardAPI": {"defaultMode": 0o444, "items": [
            {"path": field, "fieldRef": {"apiVersion": "v1", "fieldPath": source}} for field, source in identity.FIELDS.items()]}},
    ]
    if spec["identityRoute"] == "secret-client-certificate":
        # The Secret is created by whoever holds the credential and is NEVER generated or stored here. Each key is a subPath file mount (a regular file).
        for key, target in (("ca.crt", "kubernetes-ca.crt"), ("client.crt", "kubernetes-client.crt"), ("client.key", "kubernetes-client.key")):
            container_mounts.append({"name": "kubernetes-identity", "mountPath": IDENTITY_DIR + "/" + target, "subPath": key, "readOnly": True})
        volumes.append({"name": "kubernetes-identity", "secret": {"secretName": "sdk-qualification-identity", "defaultMode": 0o400,
                                                                  "items": [{"key": "ca.crt", "path": "ca.crt", "mode": 0o444}, {"key": "client.crt", "path": "client.crt", "mode": 0o444},
                                                                            {"key": "client.key", "path": "client.key", "mode": 0o400}]}})
    else:
        # route B needs a change to the protected requester module (it refuses tokens today); the projected token is short-lived and audience bound
        container_mounts.append({"name": "kubernetes-token", "mountPath": IDENTITY_DIR + "/token", "subPath": "token", "readOnly": True})
        volumes.append({"name": "kubernetes-token", "projected": {"defaultMode": 0o400, "sources": [{"serviceAccountToken": {
            "expirationSeconds": 600, "path": "token"}}]}})
    # Omit audience so the API server chooses its accepted default; API URL is not its audience.
    # Keep projected Pod-bound tokens short-lived, read-only and scoped by the same RBAC.
    # the worker controller's bearer supplier reads this token (A2A lane to confirm the path)
    container_mounts.append({"name": "worker-token", "mountPath": WORKER_TOKEN, "subPath": "token", "readOnly": True})
    volumes.append({"name": "worker-token", "projected": {"defaultMode": 0o400, "sources": [{"serviceAccountToken": {
        "expirationSeconds": 600, "path": "token"}}]}})
    return container_mounts, volumes


WAIT_SECONDS = "120"


def _environment(spec):
    """The non-secret configuration of the A2A lane's entry point (P0 design freeze, section 3.2). The admission descriptor has no field for the Job or
    container name, and the observer needs both; a wrong value can only make verification fail."""
    env = [("DSH_NATIVE_QUALIFICATION_MODE", "1"), ("DSH_OFFICIAL_SDK_ADMISSION_FILE", ADMISSION_DIR + "/official-sdk-server.json"),
           ("DSH_QUALIFICATION_JOB_NAME", spec["jobName"]), ("DSH_QUALIFICATION_CONTAINER_NAME", spec["containerName"]),
           ("DSH_QUALIFICATION_WAIT_SECONDS", WAIT_SECONDS), ("DSH_QUALIFICATION_WORKER_NAMESPACE", spec["namespace"]), ("DSH_TASK_STATE_ROOT", TASK_STATE_ROOT),
           ("DSH_TASK_TOKEN_FILE", BROKER_TOKEN_FILE)]
    if spec["nodeName"]:
        env.append(("DSH_QUALIFICATION_NODE_NAME", spec["nodeName"]))
    if spec["excludedNodes"]:
        env.append((EXCLUDED_NODES_ENV, ",".join(sorted(spec["excludedNodes"]))))
    return [{"name": k, "value": v} for k, v in env]


def _resources(spec):
    r = spec["resources"]
    one = {"cpu": str(r["cpu"]), "memory": str(r["memoryBytes"]), "ephemeral-storage": str(r["ephemeralBytes"])}
    return {"requests": dict(one), "limits": dict(one)}


def workspace_policy_text():
    """Static and non-secret (A2A lane D12): the only project is '.', never writable; the credential Secret is only NAMED here."""
    policy = {"policies": {".": {"claim": WORKSPACE_CLAIM, "subpath": WORKSPACE_SUBPATH, "writes": False, "brokerPath": "/workspace",
                                  "credentialSecret": TASK_CREDENTIAL_SECRET}}}
    return json.dumps(policy, sort_keys=True, indent=2) + "\n"


def _client_objects(spec, client_files):
    _require(isinstance(client_files, dict) and set(client_files) == set(CLIENT_FILES) and all(isinstance(v, bytes) and v for v in client_files.values()), "CLIENT_FILES_EXACT_REQUIRED")
    labels = _labels(spec, spec["clientPodLabels"])
    meta = {"name": CLIENT_POD, "namespace": spec["namespace"], "labels": labels}
    mib = 1024 ** 2
    pod_spec = {"restartPolicy": "Never", "serviceAccountName": "default", "automountServiceAccountToken": False, "enableServiceLinks": False,
                "hostNetwork": False, "hostPID": False, "hostIPC": False, "shareProcessNamespace": False, "activeDeadlineSeconds": CLIENT_DEADLINE_SECONDS,
                "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{"name": CLIENT_CONTAINER, "image": spec["image"], "imagePullPolicy": "IfNotPresent",
                                "command": ["python3", "-I", "-c", "import time; time.sleep(%d)" % (CLIENT_DEADLINE_SECONDS - 60)],
                                "securityContext": {"privileged": False, "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "runAsUser": 0,
                                                    "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}},
                                "resources": {"requests": {"cpu": "100m", "memory": str(256 * mib), "ephemeral-storage": str(64 * mib)},
                                              "limits": {"cpu": "1", "memory": str(GIB), "ephemeral-storage": str(256 * mib)}},
                                "volumeMounts": [{"name": "client-script", "mountPath": CLIENT_MOUNT, "readOnly": True},
                                                 {"name": "broker-token", "mountPath": BROKER_TOKEN_FILE, "subPath": "token", "readOnly": True},
                                                 {"name": "evidence", "mountPath": CLIENT_EVIDENCE}]}],
                "volumes": [{"name": "client-script", "configMap": {"name": CLIENT_SCRIPT_CONFIGMAP, "defaultMode": 0o444}},
                            {"name": "broker-token", "secret": {"secretName": BROKER_TOKEN_SECRET, "defaultMode": 0o400, "items": [{"key": "token", "path": "token", "mode": 0o400}]}},
                            {"name": "evidence", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}}]}
    return {
        "networkpolicy-client": {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": _meta(spec, "client"),
                                 "spec": {"podSelector": {"matchLabels": dict(spec["clientPodLabels"])}, "policyTypes": ["Ingress", "Egress"], "ingress": [],
                                          "egress": [{"to": [{"podSelector": {"matchLabels": {BROKER_LABEL: BROKER_VALUE}}}],
                                                      "ports": [{"protocol": "TCP", "port": CLIENT_PORT}]}]}},
        "configmap-client-script": {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _meta(spec, CLIENT_SCRIPT_CONFIGMAP), "immutable": True,
                                    "data": {name: client_files[name].decode("utf-8") for name in CLIENT_FILES}},
        "pod-client": {"apiVersion": "v1", "kind": "Pod", "metadata": meta, "spec": pod_spec},
    }


# The three named qualification Jobs share ONE namespace and ONE observer Role (the Role is a shared object and must be byte-identical in every case folder,
# otherwise the live re-check of the shared objects at the next case refuses with READBACK_VALUE_MISMATCH role-observer.rules[1].resourceNames[0]).
# The Role therefore names the union of the three Jobs plus this spec's own Job, sorted: still exact names, never a wildcard, never wider than these Jobs.
QUALIFICATION_JOBS = ("sdk-qualification-b", "sdk-qualification-c", "sdk-qualification-d")


def observer_job_names(job):
    return sorted(set(QUALIFICATION_JOBS) | {job})


def build_objects(spec, *, wheel_raw, package_admission_raw, client_files=None):
    validate_spec(spec)
    _require(_sha(wheel_raw) == spec["wheelSha256"], "WHEEL_NOT_THE_ADMITTED_ONE")
    package = json.loads(package_admission_raw)
    _require(package.get("kind") == "DSH_OFFICIAL_SDK_PACKAGE_V1" and package.get("sdkWheelSha256") == spec["wheelSha256"], "PACKAGE_ADMISSION_NOT_FOR_THIS_WHEEL")
    ns, job = spec["namespace"], spec["jobName"]
    level = spec["podSecurity"]
    mounts, volumes = _mounts_and_volumes(spec)
    pod_spec = {"restartPolicy": "Never", "serviceAccountName": SERVICE_ACCOUNT, "automountServiceAccountToken": False, "enableServiceLinks": False,
                "hostNetwork": False, "hostPID": False, "hostIPC": False, "shareProcessNamespace": False,
                "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{"name": spec["containerName"], "image": spec["image"], "imagePullPolicy": "IfNotPresent", "command": list(spec["command"]),
                                "securityContext": {"privileged": False, "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "runAsUser": 0,
                                                    "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}},
                                "env": _environment(spec), "resources": _resources(spec), "volumeMounts": mounts}],
                "volumes": volumes}
    if spec["nodeName"]:
        pod_spec["nodeName"] = spec["nodeName"]
    if spec["excludedNodes"]:   # empty on the one-node cluster: no affinity at all
        pod_spec["affinity"] = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [
            {"matchExpressions": [{"key": "kubernetes.io/hostname", "operator": "NotIn", "values": sorted(spec["excludedNodes"])}]}]}}}
    objects = {
        "namespace": {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns, "labels": _labels(spec, {
            "pod-security.kubernetes.io/enforce": level, "pod-security.kubernetes.io/audit": level, "pod-security.kubernetes.io/warn": level})}},
        "limitrange": {"apiVersion": "v1", "kind": "LimitRange", "metadata": _meta(spec, "dsh-qualification-container-bounds"),
                       # ephemeral-storage defaults: the hash-bound worker containers set none, and a LimitRange default keeps them admissible
                       "spec": {"limits": [{"type": "Container", "default": {"cpu": "1", "memory": str(GIB), "ephemeral-storage": str(256 * 1024 ** 2)},
                                            "defaultRequest": {"cpu": "100m", "memory": str(128 * 1024 ** 2), "ephemeral-storage": str(64 * 1024 ** 2)},
                                            "max": {"cpu": str(CONTAINER_MAX["cpu"]), "memory": str(CONTAINER_MAX["memory"])}}]}},
        "resourcequota": {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": _meta(spec, "dsh-qualification-budget"),
                          "spec": {"hard": dict({k: str(v) for k, v in QUOTA.items()}, **{"requests.storage": str(MAX_WORKSPACE_BYTES)})}},
        "serviceaccount": {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": _meta(spec, SERVICE_ACCOUNT), "automountServiceAccountToken": False},
        "networkpolicy-default-deny": {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": _meta(spec, "default-deny-all"),
                                       "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []}},
        # broker: ingress from the client Pod on 7682 only; egress DNS plus the Kubernetes API only (no broker-to-worker traffic: the worker stream is an attach through the API)
        "networkpolicy-broker": {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": _meta(spec, "broker"),
                                 "spec": {"podSelector": {"matchLabels": {BROKER_LABEL: BROKER_VALUE}}, "policyTypes": ["Ingress", "Egress"],
                                          "ingress": [{"from": [{"podSelector": {"matchLabels": dict(spec["clientPodLabels"])}}],
                                                       "ports": [{"protocol": "TCP", "port": CLIENT_PORT}]}],
                                          "egress": [_dns_rule()] + [{"to": [{"ipBlock": {"cidr": t["cidr"]}}], "ports": [{"protocol": "TCP", "port": t["port"]}]}
                                                                      for t in spec["apiServerTargets"]]}},
        # worker Pods: egress to the LiteLLM gateway (namespace llm) on 4000 only, no ingress
        "networkpolicy-worker": {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": _meta(spec, "worker"),
                                 "spec": {"podSelector": {"matchLabels": {WORKER_LABEL: WORKER_VALUE}}, "policyTypes": ["Ingress", "Egress"], "ingress": [],
                                          "egress": [_dns_rule(), {"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "llm"}},
                                                                           "podSelector": {"matchLabels": dict(spec["litellmPodLabels"])}}],
                                                                   "ports": [{"protocol": "TCP", "port": LITELLM_PORT}]}]}},
        "clusterrole-read-namespace": {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
                                       "metadata": {"name": "dsh-sdk-qualification-" + ns, "labels": _labels(spec)},
                                       "rules": [{"apiGroups": [""], "resources": ["namespaces"], "resourceNames": [ns], "verbs": ["get"]}]},
        "role-observer": {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": _meta(spec, "sdk-qualification-observer"),
                          "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get"]},
                                    {"apiGroups": ["batch"], "resources": ["jobs"], "resourceNames": observer_job_names(job), "verbs": ["get"]}]},
        "role-worker-controller": {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": _meta(spec, "sdk-qualification-worker-controller"),
                                   "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["create", "get", "delete"]},
                                               {"apiGroups": [""], "resources": ["pods/attach"], "verbs": ["create"]}]},
        "configmap-workspace-policy": {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _meta(spec, "a2a-workspace-policy"), "immutable": True,
                                       "data": {WORKSPACE_POLICY_FILE: workspace_policy_text()}},
        "persistentvolumeclaim-workspace": {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": _meta(spec, WORKSPACE_CLAIM),
                                            "spec": dict({"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": str(spec["workspaceBytes"])}},
                                                          "volumeMode": "Filesystem"},
                                                         storageClassName=spec["workspaceStorageClass"])},
        "configmap-sdk-wheel": {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _meta(spec, "sdk-wheel"), "immutable": True,
                                "binaryData": {WHEEL_NAME: base64.b64encode(wheel_raw).decode("ascii")}},
        "configmap-package-admission": {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _meta(spec, "sdk-package-admission"), "immutable": True,
                                        "data": {"official-sdk-package.json": package_admission_raw.decode("utf-8")}},
        "job": {"apiVersion": "batch/v1", "kind": "Job", "metadata": _meta(spec, job),
                "spec": {"backoffLimit": 0, "parallelism": 1, "completions": 1, "activeDeadlineSeconds": spec["activeDeadlineSeconds"], "suspend": False,
                         "template": {"metadata": {"labels": _labels(spec, {BROKER_LABEL: BROKER_VALUE})}, "spec": pod_spec}}},
    }
    objects["clusterrolebinding-read-namespace"] = _binding("ClusterRoleBinding", "dsh-sdk-qualification-" + ns, "ClusterRole", "dsh-sdk-qualification-" + ns,
                                                            _observer_subjects(spec) + [s for s in _worker_subjects(spec) if s not in _observer_subjects(spec)], spec, namespaced=False)
    objects["rolebinding-observer"] = _binding("RoleBinding", "sdk-qualification-observer", "Role", "sdk-qualification-observer", _observer_subjects(spec), spec)
    objects["rolebinding-worker-controller"] = _binding("RoleBinding", "sdk-qualification-worker-controller", "Role", "sdk-qualification-worker-controller",
                                                        _worker_subjects(spec), spec)
    if client_files is not None:
        objects.update(_client_objects(spec, client_files))
    return objects


# ----------------------------------------------------------------------------------------------------------------------------------------------------------
# read-back checking
def _absent_ok(value):
    return value is False or value is None or value == [] or value == {}


def contains(actual, expected, path="$"):
    """True when `actual` (possibly a live read-back with extra server fields) holds everything `expected` admits. An admitted false/empty field may be absent."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise SpecError("READBACK_TYPE_MISMATCH:" + path)
        for key, value in expected.items():
            if key not in actual:
                if _absent_ok(value):
                    continue
                raise SpecError("READBACK_FIELD_MISSING:" + path + "." + key)
            contains(actual[key], value, path + "." + key)
        return True
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise SpecError("READBACK_LIST_MISMATCH:" + path)
        for index, (a, e) in enumerate(zip(actual, expected)):
            contains(a, e, path + "[%d]" % index)
        return True
    if actual != expected:
        raise SpecError("READBACK_VALUE_MISMATCH:" + path)
    return True


def check_client_objects(objects, client_files):
    """The test client may only talk to the broker, holds no API identity and carries exactly the hash-pinned driver files."""
    pod = objects["pod-client"]["spec"]
    container = pod["containers"][0]
    _require(len(pod["containers"]) == 1 and not pod.get("initContainers") and not pod.get("ephemeralContainers"), "CLIENT_ONE_CONTAINER")
    _require(pod.get("automountServiceAccountToken") is False and pod.get("serviceAccountName") == "default", "CLIENT_HAS_NO_API_IDENTITY")
    _require(all(pod.get(f, False) is False for f in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")), "CLIENT_HOST_NAMESPACES_REFUSED")
    sc = container["securityContext"]
    _require(sc.get("privileged", False) is False and sc.get("allowPrivilegeEscalation") is False and sc.get("readOnlyRootFilesystem") is True
             and sc.get("capabilities", {}).get("drop") == ["ALL"] and not sc.get("capabilities", {}).get("add"), "CLIENT_CONTAINER_PROFILE")
    _require(not container.get("env") and "args" not in container and container["command"][:2] == ["python3", "-I"], "CLIENT_ISOLATED_PYTHON_NO_ENV")
    kinds = {v["name"]: [k for k in v if k != "name"] for v in pod["volumes"]}
    _require(kinds == {"client-script": ["configMap"], "broker-token": ["secret"], "evidence": ["emptyDir"]}, "CLIENT_VOLUMES_EXACT")
    secrets = [v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v]
    _require(secrets == [BROKER_TOKEN_SECRET], "CLIENT_ONLY_THE_BROKER_TOKEN_SECRET")
    _require(TASK_CREDENTIAL_SECRET not in json.dumps(pod) and "sdk-qualification-identity" not in json.dumps(pod), "CLIENT_MUST_NOT_REFERENCE_CREDENTIALS")
    _require(not any(k.startswith(("nvidia.com", "amd.com")) or "gpu" in k.lower() for part in container["resources"].values() for k in part), "CLIENT_NO_GPU")
    data = objects["configmap-client-script"]["data"]
    _require(set(data) == set(CLIENT_FILES) and all(data[n].encode("utf-8") == client_files[n] for n in CLIENT_FILES), "CLIENT_SCRIPT_NOT_THE_PINNED_FILES")
    policy = objects["networkpolicy-client"]["spec"]
    _require(not policy.get("ingress") and len(policy.get("egress", [])) == 1 and policy["egress"][0]["to"] == [{"podSelector": {"matchLabels": {BROKER_LABEL: BROKER_VALUE}}}]
             and policy["egress"][0]["ports"] == [{"protocol": "TCP", "port": CLIENT_PORT}], "CLIENT_EGRESS_BROKER_ONLY")
    return ["test-client-broker-only-no-identity-pinned-files"]


def check_objects(objects, spec, *, wheel_raw, package_admission_raw, client_files=None):
    """Independent check of generated objects OR live read-backs against the admitted spec. Returns the list of checks passed."""
    validate_spec(spec)
    expected = build_objects(spec, wheel_raw=wheel_raw, package_admission_raw=package_admission_raw, client_files=client_files)
    _require(set(objects) == set(expected), "OBJECT_SET_MISMATCH")
    passed = []
    for key, value in expected.items():
        contains(objects[key], value, key)
    passed.append("readback-contains-the-admitted-objects")
    always_refused = {"secrets", "pods/exec", "pods/portforward", "configmaps", "serviceaccounts/token"}
    for key in ("role-observer", "role-worker-controller", "clusterrole-read-namespace"):
        for rule in objects[key]["rules"]:
            _require("*" not in json.dumps(rule), "RBAC_WILDCARD_REFUSED")
            resources = set(rule.get("resources", []))
            _require(not resources & always_refused, "RBAC_SENSITIVE_RESOURCE_REFUSED")
            if "pods/attach" in resources:   # only the worker identity, only to create, and never mixed with other resources in one rule
                _require(key == "role-worker-controller" and resources == {"pods/attach"} and set(rule["verbs"]) == {"create"}, "RBAC_ATTACH_ONLY_FOR_THE_WORKER_IDENTITY")
            _require(not set(rule.get("verbs", [])) & {"list", "watch", "update", "patch", "deletecollection", "escalate", "bind", "impersonate"}, "RBAC_VERB_REFUSED")
    passed.append("rbac-minimal-named-and-without-secrets")
    pod = objects["job"]["spec"]["template"]["spec"]
    _require(not pod.get("initContainers") and not pod.get("ephemeralContainers") and len(pod["containers"]) == 1, "ONE_CONTAINER_NO_INIT_REQUIRED")
    sc = pod["containers"][0]["securityContext"]
    _require(sc.get("privileged", False) is False and sc.get("allowPrivilegeEscalation") is False and sc.get("readOnlyRootFilesystem") is True
             and sc.get("capabilities", {}).get("drop") == ["ALL"] and not sc.get("capabilities", {}).get("add"), "EXECUTING_IDENTITY_CONTAINER_PROFILE")
    _require(all(pod.get(f, False) is False for f in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace")), "HOST_NAMESPACES_REFUSED")
    terms = pod.get("affinity", {}).get("nodeAffinity", {}).get("requiredDuringSchedulingIgnoredDuringExecution", {}).get("nodeSelectorTerms", [])
    if spec["excludedNodes"]:
        _require(len(terms) == 1 and any(e.get("key") == "kubernetes.io/hostname" and e.get("operator") == "NotIn" and set(spec["excludedNodes"]) <= set(e.get("values", []))
                                         for e in terms[0].get("matchExpressions", [])), "NODE_EXCLUSION_MISSING")
    else:
        _require(not pod.get("affinity"), "NO_AFFINITY_ON_THE_ONE_NODE_CLUSTER")
    _require(pod.get("nodeName") not in spec["excludedNodes"], "POD_ON_AN_EXCLUDED_NODE")
    # ORCH-DECISION-P2-REVISED-AFTER-SURVEY: it shares the GPU node, so no GPU, no priority above the default, requests and limits inside the LimitRange
    _require("priorityClassName" not in pod and "priority" not in pod, "NO_PRIORITY_ABOVE_THE_DEFAULT")
    for resources in (pod["containers"][0]["resources"].get("requests", {}), pod["containers"][0]["resources"].get("limits", {})):
        _require(not any("gpu" in k.lower() or k.startswith("nvidia.com") or "mig" in k for k in resources), "NO_GPU_REQUEST")
    quantities = pod["containers"][0]["resources"]
    _require(quantities.get("requests") and quantities.get("limits") and quantities["requests"] == quantities["limits"], "EXPLICIT_EQUAL_REQUESTS_AND_LIMITS")
    _require(not any("hostPath" in v or "nfs" in v or "csi" in v for v in pod["volumes"]), "FORBIDDEN_VOLUME")
    _require(not any(v.get("persistentVolumeClaim") for v in pod["volumes"]), "BROKER_MUST_NOT_MOUNT_THE_WORKSPACE_CLAIM")
    workspace = [v for v in pod["volumes"] if v["name"] == "workspace"]
    _require(len(workspace) == 1 and workspace[0].get("emptyDir", {}).get("medium") == "Memory", "BROKER_WORKSPACE_MUST_BE_A_MEMORY_EMPTYDIR")
    state = [v for v in pod["volumes"] if v["name"] == "task-state"]
    _require(len(state) == 1 and state[0].get("emptyDir", {}).get("medium") == "Memory" and set(state[0]) == {"name", "emptyDir"}, "TASK_STATE_MUST_BE_AN_EMPTY_MEMORY_EMPTYDIR")
    state_mounts = [m for m in pod["containers"][0]["volumeMounts"] if m["mountPath"] == TASK_STATE_MOUNT or m["mountPath"].startswith(TASK_STATE_MOUNT + "/")]
    _require(len(state_mounts) == 1 and state_mounts[0]["name"] == "task-state" and "subPath" not in state_mounts[0] and not state_mounts[0].get("readOnly"), "ONLY_THE_EMPTY_STATE_VOLUME_MAY_BE_UNDER_STATE")
    _require({"name": "DSH_TASK_STATE_ROOT", "value": TASK_STATE_ROOT} in pod["containers"][0].get("env", []), "TASK_STATE_ROOT_ENV_REQUIRED")
    workspace_mounts = [m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "workspace"]
    _require(len(workspace_mounts) == 1 and workspace_mounts[0].get("mountPath") == "/workspace" and "subPath" not in workspace_mounts[0], "BROKER_WORKSPACE_MOUNT_AT_WORKSPACE")
    _require(TASK_CREDENTIAL_SECRET not in json.dumps(pod), "BROKER_MUST_NOT_REFERENCE_THE_TASK_CREDENTIAL")
    claim_spec = objects["persistentvolumeclaim-workspace"]["spec"]
    _require(claim_spec["accessModes"] == ["ReadWriteOnce"], "WORKSPACE_CLAIM_ACCESS_MODE")
    _require(claim_spec.get("storageClassName") == STORAGE_CLASS, "WORKSPACE_CLAIM_MUST_USE_THE_IMMEDIATE_CLASS")
    _require(claim_spec["resources"]["requests"]["storage"] == str(spec["workspaceBytes"]) and spec["workspaceBytes"] <= MAX_WORKSPACE_BYTES, "WORKSPACE_CLAIM_AT_MOST_1GI")
    limit_range = objects["limitrange"]["spec"]["limits"][0]
    _require(limit_range["max"] == {"cpu": str(CONTAINER_MAX["cpu"]), "memory": str(CONTAINER_MAX["memory"])}, "LIMITRANGE_MAX")
    hard = objects["resourcequota"]["spec"]["hard"]
    _require(hard == dict({k: str(v) for k, v in QUOTA.items()}, **{"requests.storage": str(MAX_WORKSPACE_BYTES)}), "RESOURCEQUOTA_BOUNDS")
    _require(not any("ephemeral" in k for k in hard), "EPHEMERAL_STORAGE_NOT_IN_THE_QUOTA")
    _require({"ephemeral-storage"} <= set(limit_range.get("default", {})) and {"ephemeral-storage"} <= set(limit_range.get("defaultRequest", {})), "LIMITRANGE_EPHEMERAL_DEFAULTS")
    egress = objects["networkpolicy-broker"]["spec"]["egress"]
    for target in spec["apiServerTargets"]:
        _require(any(rule.get("to") == [{"ipBlock": {"cidr": target["cidr"]}}] and rule.get("ports") == [{"protocol": "TCP", "port": target["port"]}] for rule in egress), "API_SERVER_EGRESS_MISSING")
    _require(all(set(e) == {"name", "value"} for e in pod["containers"][0].get("env", [])), "ENV_VALUE_FROM_REFUSED")
    _require(not any(e["name"].startswith("PYTHON") or e["name"] in ("LD_PRELOAD", "LD_LIBRARY_PATH") for e in pod["containers"][0].get("env", [])), "INTERPRETER_ENV_REFUSED")
    _require(pod["containers"][0].get("command", [None, None])[1:2] == ["-I"] and "args" not in pod["containers"][0], "ISOLATED_PYTHON_NO_ARGS_REQUIRED")
    _require(not any(re.search(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", e["name"]) for e in pod["containers"][0].get("env", []) if e["name"] != "DSH_TASK_TOKEN_FILE"), "SECRET_LOOKING_ENV_REFUSED")
    _require({"name": "DSH_TASK_TOKEN_FILE", "value": BROKER_TOKEN_FILE} in pod["containers"][0].get("env", []), "BROKER_TOKEN_FILE_ENV_REQUIRED")   # a PATH, not a secret value
    token_volumes = [v for v in pod["volumes"] if v["name"] == "broker-token"]
    _require(len(token_volumes) == 1 and token_volumes[0].get("secret", {}).get("secretName") == BROKER_TOKEN_SECRET and token_volumes[0]["secret"].get("defaultMode") == 0o400, "BROKER_TOKEN_SECRET_BY_NAME_MODE_0400")
    token_mounts = [m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "broker-token"]
    _require(len(token_mounts) == 1 and token_mounts[0].get("mountPath") == BROKER_TOKEN_FILE and token_mounts[0].get("subPath") == "token" and token_mounts[0].get("readOnly") is True, "BROKER_TOKEN_SUBPATH_FILE_READ_ONLY")
    for volume in pod["volumes"]:   # contains() tolerates extra live fields, so a Job that still names the refused audience would pass: refuse any explicit audience here
        for source in (volume.get("projected") or {}).get("sources", []):
            if "serviceAccountToken" in source:
                _require("audience" not in source["serviceAccountToken"], "PROJECTED_TOKEN_MUST_NOT_NAME_AN_AUDIENCE")
    passed.append("job-pod-profile-for-observer-and-executing-identity")
    if client_files is not None:
        passed += check_client_objects(objects, client_files)
    return passed


def check_server_admission(raw, spec, binding, *, now):
    """The late-bound server admission, before it is delivered: the UIDs must be the live ones, the window short, the image and namespace the admitted ones."""
    validate_spec(spec)
    value = json.loads(raw)
    _require(value.get("kind") == "DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1" and value.get("mode") == "qualification", "ADMISSION_KIND_OR_MODE")
    _require(0 < value.get("expiresAt", 0) - now <= 300, "ADMISSION_WINDOW_1_TO_300_SECONDS")
    _require(value["imageDigest"] == "sha256:" + spec["image"].rsplit("@sha256:", 1)[1], "ADMISSION_IMAGE_MISMATCH")
    expected = {"namespace": spec["namespace"], "namespaceUID": binding["namespaceUID"], "podUID": binding["podUID"], "workloadUID": binding["workloadUID"],
                "environment": "test", "workloadRole": "qualification"}
    _require(value["deploymentBinding"] == expected, "ADMISSION_DEPLOYMENT_BINDING_MISMATCH")
    return True


# ----------------------------------------------------------------------------------------------------------------------------------------------------------
# what the API would return for the generated objects (used by the tests to run the REAL observer and the REAL executing-identity reader)
def live_view(objects, spec, *, namespace_uid, job_uid, pod_uid, pod_name="sdk-qualification-pod"):
    ns = copy.deepcopy(objects["namespace"])
    ns["metadata"].update({"uid": namespace_uid, "resourceVersion": "1"})
    job = copy.deepcopy(objects["job"])
    job["metadata"].update({"uid": job_uid, "resourceVersion": "2"})
    template = job["spec"]["template"]
    pod = {"apiVersion": "v1", "kind": "Pod",
           "metadata": {"name": pod_name, "namespace": spec["namespace"], "uid": pod_uid, "resourceVersion": "3", "labels": dict(template["metadata"]["labels"]),
                        "ownerReferences": [{"apiVersion": "batch/v1", "kind": "Job", "name": spec["jobName"], "uid": job_uid, "controller": True}]},
           "spec": copy.deepcopy(template["spec"]),
           "status": {"phase": "Running", "containerStatuses": [{"name": spec["containerName"], "ready": True, "state": {"running": {"startedAt": "x"}},
                                                                  "imageID": "docker-pullable://" + spec["image"]}]}}
    # an API read-back omits false defaults
    for field in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace"):
        pod["spec"].pop(field, None)
        template["spec"].pop(field, None)
    return {"namespace": ns, "job": job, "pod": pod}


def reference_spec(*, image, wheel_sha256, command, client_pod_labels, api_server_targets, litellm_pod_labels):
    """The decided parameters (ORCH-DECISION-P2-COMPOSITION) with the caller's environment facts: namespace dsh-a2a-qual, baseline Pod Security, no node pin,
    the engine node excluded, a 300 s Job, route A2. The caller supplies only what the decisions leave open."""
    return {"namespace": DECIDED_NAMESPACE, "jobName": "sdk-qualification", "containerName": "broker", "image": image, "command": list(command),
            "identityRoute": "secret-client-certificate", "observerSubject": "sdk-qualification-observer", "podSecurity": "baseline",
            "activeDeadlineSeconds": 300, "resources": {"cpu": 2, "memoryBytes": 4 * GIB, "ephemeralBytes": 2 * GIB}, "wheelSha256": wheel_sha256,
            "nodeName": None, "excludedNodes": [], "workspaceBytes": 256 * 1024 ** 2, "workspaceStorageClass": STORAGE_CLASS, "clientPodLabels": dict(client_pod_labels),
            "apiServerTargets": [dict(t) for t in api_server_targets], "litellmPodLabels": dict(litellm_pod_labels)}
