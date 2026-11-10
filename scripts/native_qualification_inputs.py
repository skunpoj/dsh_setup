"""Inputs of the D10 (b) provider runtime for the native qualification broker (REDUCED ASSURANCE, first SDK proof only).

Pure pieces with an injected protected reader; nothing here opens a socket, reads the environment, mutates the cluster or starts
a process. They feed the protected A2A factory and the provider capture:

* workspace_policy_lookup: the static, non-secret workspace policy (D12) for `workspacePolicy`;
* lease_reader: the late-bound execution lease (D11) for the factory's `admission_reader`;
* RollbackRecorder: the `rollback` dependency as a RECORDER that mutates nothing (D13);
* RowsFileProviderQuery: the capture's `query_metadata` for D10 (b): instead of the protected TLS exporter and read-only spend
  store, the operator delivers the LiteLLM spend rows of the run as a late-bound root-owned file, and only the rows whose call id
  the guard ledger admitted are returned. The capture still reconciles them EXACTLY with the guard ledger. Every verdict that uses
  this route must be labelled "reduced assurance: provider rows delivered by the operator".
"""
import copy
import hashlib
from pathlib import Path
import re
import time
import uuid

ADMISSION_DIR = "/etc/dsh-native-admission"
LEASE_FILE = ADMISSION_DIR + "/a2a-factory-lease.json"
WORKSPACE_POLICY_FILE = ADMISSION_DIR + "/a2a-workspace-policy.json"
PROVIDER_ROWS_FILE = ADMISSION_DIR + "/a2a-provider-rows.json"
PROVIDER_ROWS_DIR = ADMISSION_DIR + "/a2a-provider-rows"
MODULE_FILE = "/opt/dsh/scripts/native_qualification_inputs.py"
LIMIT = 65536
POLICY_KEYS = frozenset({"claim", "subpath", "writes", "brokerPath", "credentialSecret"})
NAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")
SUBPATH = re.compile(r"[A-Za-z0-9._-]{1,64}")
RECORD_KIND = "DSH_ROLLBACK_RECORD_V1"
REDUCED_ASSURANCE = "reduced assurance: provider rows delivered by the operator"


def read_json(reader, path, unique_json):
    value = unique_json(reader(path, LIMIT))
    if not isinstance(value, (dict, list)):
        raise ValueError("JSON_OBJECT_OR_LIST_REQUIRED")
    return value


def _policy(entry):
    if not isinstance(entry, dict) or set(entry) != POLICY_KEYS:
        raise ValueError("EXACT_ADMITTED_WORKSPACE_POLICY_REQUIRED")
    for key in ("claim", "credentialSecret"):
        if not isinstance(entry[key], str) or not NAME.fullmatch(entry[key]):
            raise ValueError("EXACT_ADMITTED_WORKSPACE_POLICY_REQUIRED")
    broker = entry["brokerPath"]
    if (not isinstance(entry["subpath"], str) or not SUBPATH.fullmatch(entry["subpath"]) or entry["subpath"] in (".", "..")
            or type(entry["writes"]) is not bool or not isinstance(broker, str)
            or not (broker == "/workspace" or re.fullmatch(r"/workspace/[A-Za-z0-9._-]{1,64}", broker))
            or ".." in broker.split("/")):
        raise ValueError("EXACT_ADMITTED_WORKSPACE_POLICY_REQUIRED")
    return copy.deepcopy(entry)


def workspace_policy_lookup(*, reader, unique_json, path=WORKSPACE_POLICY_FILE):
    """workspacePolicy(subject, project): re-reads the protected file on every call; unknown projects are refused."""
    def lookup(subject, project):
        if not isinstance(subject, str) or not subject or not isinstance(project, str) or not project:
            raise ValueError("EXACT_ADMITTED_WORKSPACE_POLICY_REQUIRED")
        doc = read_json(reader, path, unique_json)
        if not isinstance(doc, dict) or set(doc) != {"policies"} or not isinstance(doc["policies"], dict):
            raise ValueError("EXACT_ADMITTED_WORKSPACE_POLICY_REQUIRED")
        if project not in doc["policies"]:
            raise ValueError("WORKSPACE_PROJECT_NOT_ADMITTED")
        return _policy(doc["policies"][project])
    return lookup


def lease_reader(*, reader, unique_json, path=LEASE_FILE):
    """admission_reader of the protected factory: the factory validates the content on every operation; this only reads."""
    def read():
        value = read_json(reader, path, unique_json)
        if not isinstance(value, dict):
            raise ValueError("EXECUTION_LEASE_OBJECT_REQUIRED")
        return value
    return read


class RollbackRecorder:
    """`rollback(task, binding)` dependency: records, claims nothing, mutates nothing (the operator rolls back by order)."""
    def __init__(self):
        self.records = []

    def __call__(self, task, binding, *args, **kwargs):
        if not isinstance(binding, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(binding.get("taskId"))):
            raise ValueError("EXACT_ROLLBACK_TASK_BINDING_REQUIRED")
        record = dict(kind=RECORD_KIND, taskId=binding["taskId"], correlationId=binding.get("correlationId"),
                      rollbackVerified=False, providerExecutionStoppedVerified=False, mutations=0)
        self.records.append(record)
        return copy.deepcopy(record)


def provider_source_binding(*, reader, source_commit, image_digest):
    """The capture's `source`: the route's identity is the hash of THIS module (the reduced-assurance 'exporter')."""
    digest = hashlib.sha256(reader(MODULE_FILE, 1024 * 1024)).hexdigest()
    return dict(sourceCommit=source_commit, imageDigest=image_digest, exporterSha256=digest)


class RowsFileProviderQuery:
    """`query_metadata(request)` for TaskProviderCapture: returns exactly {query, source, rows} with the delivered rows whose
    call id the guard admitted. Missing rows are NOT invented: the capture's exact reconciliation then refuses."""
    def __init__(self, *, reader, unique_json, source_observer, path=PROVIDER_ROWS_FILE):
        if not callable(source_observer):
            raise ValueError("PROVIDER_SOURCE_OBSERVER_REQUIRED")
        self.reader, self.unique_json, self.observe, self.path = reader, unique_json, source_observer, path

    @staticmethod
    def _valid_ids(ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 2 or len(set(map(str, ids))) != len(ids):
            raise ValueError("EXACT_ADMITTED_OPERATION_SELECTOR_REQUIRED")
        for i in ids:
            try:
                valid = isinstance(i, str) and str(uuid.UUID(i)) == i
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("EXACT_ADMITTED_OPERATION_SELECTOR_REQUIRED")

    def __call__(self, request):
        ids = request.get("operationIds") if isinstance(request, dict) else None
        self._valid_ids(ids)
        rows = read_json(self.reader, self.path, self.unique_json)
        if not isinstance(rows, list) or len(rows) > 64 or any(not isinstance(r, dict) for r in rows):
            raise ValueError("DELIVERED_PROVIDER_ROWS_LIST_REQUIRED")
        selected = [copy.deepcopy(r) for r in rows if r.get("litellm_call_id") in ids]
        return dict(query=copy.deepcopy(request), source=copy.deepcopy(self.observe()), rows=selected)


class RowsDirectoryProviderQuery(RowsFileProviderQuery):
    """Per-call variant (write-once friendly): row `<dir>/<litellm_call_id>.json` (one JSON object) is delivered by the operator as
    soon as that call's spend row exists, so a task can be captured INSIDE the lease window. A missing or unreadable file yields no
    row for that call, and the capture's exact reconciliation then refuses (never invented). A file whose call id differs from its
    name is dropped the same way."""
    def __init__(self, *, reader, unique_json, source_observer, directory=PROVIDER_ROWS_DIR):
        super().__init__(reader=reader, unique_json=unique_json, source_observer=source_observer, path=directory)

    def __call__(self, request):
        ids = request.get("operationIds") if isinstance(request, dict) else None
        self._valid_ids(ids)
        rows = []
        for call_id in ids:
            try:
                row = read_json(self.reader, self.path + "/" + call_id + ".json", self.unique_json)
            except (OSError, ValueError):
                continue
            if isinstance(row, dict) and row.get("litellm_call_id") == call_id:
                rows.append(copy.deepcopy(row))
        return dict(query=copy.deepcopy(request), source=copy.deepcopy(self.observe()), rows=rows)


LEASE_BOUND = ("subject", "namespace", "namespaceUID", "image", "sourceCommit", "nodeName")


def make_execution_admission(*, controller_values, lease_reader, clock=time.time):
    """`executionAdmission(subject, task_id, correlation, project, runtime, writes, prompt_sha)` for the controllers.

    The per-task admission cannot be minted ahead (task ids and prompt hashes do not exist yet), so it is PROJECTED from the
    operator-delivered lease at call time: the identity fields must equal the controllers' own values, the lease must be fresh
    (0 < expiresAt - now <= 300), and `modelStartsAllowed` becomes 1 when the lease allows at least one start, else 0. The factory
    wrapper has already bound the call to its exact task; the worker controller re-validates every field.
    """
    for key in LEASE_BOUND:
        if not isinstance(controller_values.get(key), str) or not controller_values[key]:
            raise ValueError("EXACT_CONTROLLER_VALUES_REQUIRED")

    def admit(subject, task_id, correlation, project, runtime, writes, prompt_sha):
        lease = lease_reader()
        if not isinstance(lease, dict) or any(lease.get(k) != controller_values[k] for k in LEASE_BOUND) or subject != lease.get("subject"):
            raise ValueError("EXECUTION_LEASE_FOREIGN_OR_STALE")
        expires, starts = lease.get("expiresAt"), lease.get("modelStartsAllowed")
        if type(expires) not in (int, float) or not 0 < expires - clock() <= 300:
            raise ValueError("EXECUTION_LEASE_EXPIRED_OR_TOO_LONG")
        if type(starts) is not int or not 0 <= starts <= 3:
            raise ValueError("EXECUTION_LEASE_MODEL_STARTS_INVALID")
        return dict(subject=subject, namespace=lease["namespace"], namespaceUID=lease["namespaceUID"], image=lease["image"],
                    sourceCommit=lease["sourceCommit"], nodeName=lease["nodeName"], mode="private-test", taskId=task_id,
                    correlationId=correlation, project=project, runtime=runtime, writes=writes, promptSha256=prompt_sha,
                    expiresAt=expires, modelStartsAllowed=1 if starts >= 1 else 0)
    return admit
