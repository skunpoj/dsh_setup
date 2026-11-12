"""Root-protected named banking admission with retained original accounting.

Explicit standingAuthority plus null total/per-task/budget/expiry removes the
human-lifted limits for these three named routes. Native/ordinary tasks retain
cap one. Numeric legacy policies remain readable for historical compatibility;
they are never converted to standing authority or silently extended.

Every task keeps its original reservation, binding, exact request starts/finishes,
terminal settlement and fence evidence. Unbounded unsettled reservations are
UNKNOWN, never reported as zero actual usage. No reset or imported-row rewrite.
"""
import json
from scripts.banking_standing_authority import AUTHORITY, standing
import hashlib
import re
import os
import tempfile
import threading
import time
from pathlib import Path

try:  # POSIX file lock between broker threads and processes; the Windows test host falls back to the thread lock
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

ALLOWANCE_FILE = Path("/etc/dsh/banking-allowance.json")
LEDGER_FILE = Path("/state/banking-guard-protected/global/allowance-ledger.json")
KIND = "DSH_BANKING_ALLOWANCE_V1"
ORDINARY_CAP = 1
MAX_PER_TASK = 32      # the guard's hard limit: AdmissionLedger refuses a model-start cap above 32 (scripts/unattended_model_guard.py)
RUNTIMES = {"claude", "deepagents", "sdk"}
REQUIRED_GRANT_KEYS = {"project", "runtime", "maxRequestsPerTask", "budgetRequests"}
OPTIONAL_GRANT_KEYS = {"subject", "expiresAt", "runId", "runner", "generation", "alreadySpentRequests"}
_THREAD_LOCK = threading.Lock()


def load_allowance(path=None, *, owner_check=None, stat=os.stat):
    """The trusted allowance document, or None (ordinary cap) when absent, untrusted, disabled or malformed."""
    path = Path(path or ALLOWANCE_FILE)
    if owner_check is None:
        owner_check = os.name == "posix"
    try:
        info = stat(path)
        import stat as stat_module
        if not stat_module.S_ISREG(info.st_mode):
            return None
        if owner_check and (info.st_uid != 0 or info.st_mode & 0o022):
            return None
        document = _unique_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(document, dict) or document.get("kind") != KIND or document.get("enabled") is not True
            or not (document.get("totalRequests") is None and standing(document) or _int(document.get("totalRequests"), 1, 100000)) or not _int(document.get("alreadySpentRequests", 0), 0, 100000)
            or not isinstance(document.get("grants"), list) or not document["grants"]):
        return None
    if "standingAuthority" in document and (not standing(document) or document["totalRequests"] is not None or any(not isinstance(g,dict) or any(g.get(k,"missing") is not None for k in ("maxRequestsPerTask","budgetRequests","expiresAt")) for g in document["grants"])):return None
    baseline=document.get("actualsBaselineSha256")
    if baseline is not None and (not isinstance(baseline,str) or not re.fullmatch(r"[a-f0-9]{64}",baseline)):
        return None
    if standing(document) and (len(document["grants"])!=3 or {g.get("runtime") for g in document["grants"] if isinstance(g,dict)}!=RUNTIMES or any(not isinstance(g,dict) or not {"subject","runId","runner","expiresAt"}<=set(g) for g in document["grants"])):return None
    for grant in document["grants"]:
        if (not isinstance(grant, dict) or not REQUIRED_GRANT_KEYS <= set(grant) <= REQUIRED_GRANT_KEYS | OPTIONAL_GRANT_KEYS
                or not isinstance(grant.get("subject", ""), str) or not grant.get("subject", "x")
                or not (standing(document) and grant.get("expiresAt", "missing") is None or _int(grant.get("expiresAt", 1), 1, 10 ** 11))
                or not isinstance(grant["project"], str) or not grant["project"] or grant["runtime"] not in RUNTIMES
                or not _int(grant.get("alreadySpentRequests",0),0,100000)
                or not (standing(document) and grant["maxRequestsPerTask"] is None and grant["budgetRequests"] is None or _int(grant["maxRequestsPerTask"], 2, MAX_PER_TASK) and _int(grant["budgetRequests"], grant["maxRequestsPerTask"], 100000))):
            return None
    for grant in document["grants"]:
        if grant["runtime"] == "sdk":
            if (not {"subject", "expiresAt", "runId", "runner"} <= set(grant)
                    or grant["runner"] != "official-native-sdk"
                    or not isinstance(grant["runId"], str) or not grant["runId"]
                    or len(grant["runId"]) > 128):
                return None
        else:
            if "runner" in grant and grant["runner"]!={"claude":"managed-claude-code","deepagents":"managed-deepagents"}[grant["runtime"]]:return None
            for key in ("runId","generation"):
                if key in grant and (not isinstance(grant[key],str) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}",grant[key])):return None
    return document


def _int(value, low, high):
    return type(value) is int and low <= value and (high is None or value <= high)


def request_cap(runtime, project, task_id, *, subject=None, run_id=None, runner=None, sdk_binding=None, sdk_receipt=None, task_binding=None, now=None, allowance_file=None, ledger_file=None, owner_check=None):
    """The model-request cap for this task: the ordinary 1, or the admitted bound after an atomic reservation.

    Raises ValueError('BANKING_TASK_REPLAY_REFUSED') for a task id already admitted and ValueError('BANKING_ALLOWANCE_EXHAUSTED') when the grant or the total has no room;
    both refuse before any upstream request."""
    allowance = load_allowance(allowance_file, owner_check=owner_check)
    if allowance is None or runtime not in RUNTIMES or not isinstance(project, str):
        return ORDINARY_CAP
    grant = next((g for g in allowance["grants"] if g["runtime"] == runtime and g["project"] == project), None)
    if grant is None:
        return ORDINARY_CAP
    if runtime == "sdk" and (runner != "official-native-sdk" or runner != grant["runner"] or run_id != grant["runId"]):
        return ORDINARY_CAP
    if runtime == "sdk":
        expected = dict(subject=subject, runId=run_id, runtime=runtime, project=project, runner=runner)
        if not _valid_sdk_binding(sdk_binding, task_id, expected):
            raise ValueError("EXACT_BANKING_SDK_BINDING_REQUIRED")
    if "subject" in grant and subject != grant["subject"]:        # bound to the authenticated owner (X-DSH-Subject); no subject or another one = ordinary cap
        return ORDINARY_CAP
    if not standing(allowance) and "expiresAt" in grant and (time.time() if now is None else now) > grant["expiresAt"]:
        return ORDINARY_CAP
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("BANKING_TASK_ID_REQUIRED")
    ledger_path = Path(ledger_file or LEDGER_FILE)
    _verify_global_store(allowance,ledger_path,owner_check=owner_check)
    with _THREAD_LOCK:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = open(str(ledger_path) + ".lock", "a+")
        try:
            if fcntl is not None:
                fcntl.flock(lock_handle, fcntl.LOCK_EX)
            elif os.name == "nt":
                import msvcrt
                lock_handle.seek(0, os.SEEK_END)
                if lock_handle.tell()==0:lock_handle.write("0");lock_handle.flush()
                lock_handle.seek(0);msvcrt.locking(lock_handle.fileno(),msvcrt.LK_LOCK,1)
            else:
                raise ValueError("BANKING_GLOBAL_LOCK_UNSUPPORTED")
            tasks = _read(ledger_path)
            if not standing(allowance) and any(v.get("cap","missing") is None for v in tasks.values()):raise ValueError("STANDING_RESERVATIONS_REQUIRE_EXPLICIT_POLICY_RECONCILIATION")
            if task_id in tasks:
                raise ValueError("BANKING_TASK_REPLAY_REFUSED")
            baseline=allowance.get("actualsBaselineSha256")
            relevant=[t for t in tasks.values() if t["runtime"]==runtime and t["project"]==project]
            covered_total=sum(_used(t) for t in tasks.values() if _covered(t,baseline))
            if covered_total>allowance["alreadySpentRequests"]:raise ValueError("BANKING_BASELINE_COVERAGE_EXCEEDS_ACTUALS")
            if "alreadySpentRequests" in grant:
                covered_grant=sum(_used(t) for t in relevant if _covered(t,baseline))
                if covered_grant>grant["alreadySpentRequests"]:raise ValueError("BANKING_GRANT_BASELINE_COVERAGE_EXCEEDS_ACTUALS")
                spent_grant=grant["alreadySpentRequests"]+sum(_used(t) for t in relevant if not _covered(t,baseline))
            else:spent_grant=sum(_used(t) for t in relevant)
            spent_total = allowance["alreadySpentRequests"] + sum(_used(t) for t in tasks.values() if not _covered(t,baseline))
            cap = grant["maxRequestsPerTask"]
            if not standing(allowance) and (spent_grant + cap > grant["budgetRequests"] or spent_total + cap > allowance["totalRequests"]):
                raise ValueError("BANKING_ALLOWANCE_EXHAUSTED")
            tasks[task_id] = {"runtime": runtime, "project": project, "cap": cap}
            if standing(allowance):tasks[task_id]["accountingOnlyAuthority"]=AUTHORITY
            if runtime!="sdk" and task_binding is not None:
                if not isinstance(task_binding,dict) or set(task_binding)!={"subject","taskId","correlationId","runtime","project","writes","promptSha256"} or task_binding["subject"]!=subject or task_binding["taskId"]!=task_id or task_binding["runtime"]!=runtime or task_binding["project"]!=project:
                    raise ValueError("EXACT_BANKING_TASK_BINDING_REQUIRED")
                grant_generation="grant-"+_digest(allowance)[:32]
                binding=dict(task_binding,runId=grant.get("runId",grant_generation),generation=grant.get("generation",grant_generation),runner={"claude":"managed-claude-code","deepagents":"managed-deepagents"}[runtime])
                if not _terminal_binding(binding,task_id,tasks[task_id]):raise ValueError("EXACT_BANKING_TASK_BINDING_REQUIRED")
                tasks[task_id]["binding"]=binding
            if runtime == "sdk":
                tasks[task_id].update(subject=subject, runId=run_id, runner=runner, binding=dict(sdk_binding), grantSha256=hashlib.sha256(json.dumps(allowance,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest())
            reservation_raw=json.dumps(dict(kind="DSH_BANKING_REQUEST_RESERVATION_V1",taskId=task_id,reservation=tasks[task_id]),sort_keys=True,separators=(",",":"),allow_nan=False).encode()
            reservation_path=_reservation_path(ledger_path,task_id)
            if reservation_path.exists():raise ValueError("BANKING_TASK_REPLAY_REFUSED")
            _retain_evidence(reservation_path,reservation_raw)
            tasks[task_id]["reservationSha256"]=hashlib.sha256(reservation_raw).hexdigest()
            _write(ledger_path, tasks)
            if runtime == "sdk" and sdk_receipt is not None:
                sdk_receipt.update(tasks[task_id])
            return cap
        finally:
            if fcntl is not None:
                fcntl.flock(lock_handle, fcntl.LOCK_UN)
            elif os.name == "nt":
                lock_handle.seek(0);msvcrt.locking(lock_handle.fileno(),msvcrt.LK_UNLCK,1)
            lock_handle.close()


def _valid_sdk_binding(binding, task_id, record):
    keys = {"subject", "generation", "runId", "taskId", "correlationId", "project", "runtime", "runner", "writes", "promptSha256"}
    if not isinstance(binding, dict) or set(binding) != keys:
        return False
    if (binding["taskId"] != task_id or binding["runtime"] != "sdk"
            or binding["runner"] != "official-native-sdk" or type(binding["writes"]) is not bool
            or any(binding.get(k) != record.get(k) for k in ("subject", "runId", "runtime", "runner", "project"))):
        return False
    for key in ("subject", "generation", "runId"):
        if not isinstance(binding[key], str) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", binding[key]):
            return False
    for key, size in (("taskId", 32), ("correlationId", 32), ("promptSha256", 64)):
        if not isinstance(binding[key], str) or not re.fullmatch(r"[a-f0-9]{%d}" % size, binding[key]):
            return False
    return isinstance(binding["project"], str) and bool(binding["project"]) and len(binding["project"]) <= 4096


def _read(path):
    path=Path(path)
    anchor=path.with_name(path.name+'.import.original.json')
    imported=None
    if anchor.exists():
        if anchor.is_symlink():raise ValueError('BANKING_IMPORT_ANCHOR_REFUSED')
        imported=_unique_json(anchor.read_bytes())
        if not isinstance(imported,dict) or not isinstance(imported.get('tasks'),dict):raise ValueError('BANKING_IMPORT_ANCHOR_REFUSED')
        if not path.is_file():raise ValueError('BANKING_INITIALIZED_LEDGER_MISSING_REFUSED')
    try:
        document = _unique_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        document={"tasks":{}}
    except ValueError as error:
        raise ValueError("BANKING_LEDGER_UNREADABLE_REFUSED") from error      # a damaged ledger refuses; it is never reset
    tasks = document.get("tasks") if isinstance(document, dict) else None
    if (not isinstance(tasks, dict) or any(not isinstance(v, dict) or not _valid_row_cap(v)
                                           or v.get("runtime") not in RUNTIMES or not isinstance(v.get("project"), str) for v in tasks.values())):
        raise ValueError("BANKING_LEDGER_UNREADABLE_REFUSED")
    if imported is not None:
        for task_id,original_row in imported['tasks'].items():
            row=tasks.get(task_id)
            if not isinstance(row,dict) or any(row.get(k)!=v for k,v in original_row.items()):
                raise ValueError('BANKING_IMPORTED_RESERVATION_CHANGED')
    path=Path(path)
    for original in path.parent.glob(path.name+".reservation-*.json"):
        raw=original.read_bytes();envelope=_unique_json(raw);sha=hashlib.sha256(raw).hexdigest()
        if original.is_symlink() or not isinstance(envelope,dict) or set(envelope)!={"kind","taskId","reservation"} or envelope["kind"]!="DSH_BANKING_REQUEST_RESERVATION_V1" or not isinstance(envelope["taskId"],str) or not envelope["taskId"] or original!=_reservation_path(path,envelope["taskId"]):raise ValueError("BANKING_RESERVATION_ORIGINAL_REFUSED")
        task_id=envelope["taskId"];base=envelope["reservation"]
        if not isinstance(base,dict):raise ValueError("BANKING_RESERVATION_ORIGINAL_REFUSED")
        if task_id not in tasks:tasks[task_id]=dict(base,reservationSha256=sha)  # Conservatively held, never replayed.
        row=tasks[task_id]
        if row.get("reservationSha256")!=sha or {k:v for k,v in row.items() if k not in {"settlement","reservationSha256"}}!=base:
            raise ValueError("BANKING_ORIGINAL_RESERVATION_BINDING_CHANGED")
    for task_id, row in tasks.items():
        if "actual" in row:raise ValueError("BANKING_UNVERIFIED_LEGACY_ACTUAL_REFUSED")
        if not isinstance(row,dict) or not _valid_row_cap(row) or row.get("runtime") not in RUNTIMES or not isinstance(row.get("project"),str):raise ValueError("BANKING_LEDGER_UNREADABLE_REFUSED")
        if row.get("reservationSha256") is not None and not _reservation_path(path,task_id).is_file():raise ValueError("BANKING_RESERVATION_ORIGINAL_MISSING")
        if row["runtime"]!="sdk" and "binding" in row and not _terminal_binding(row["binding"],task_id,row):raise ValueError("BANKING_LEDGER_UNREADABLE_REFUSED")
        settlement=row.get("settlement")
        if settlement is not None:
            if not _valid_settlement(row,settlement,task_id):raise ValueError("BANKING_SETTLEMENT_UNREADABLE_REFUSED")
            _verify_settlement_evidence(Path(path),task_id,row,settlement)
        if row["runtime"] == "sdk" and (not _valid_sdk_binding(row.get("binding"), task_id, row)
                or not isinstance(row.get("grantSha256"), str) or not re.fullmatch(r"[a-f0-9]{64}",row["grantSha256"])):
            raise ValueError("BANKING_LEDGER_UNREADABLE_REFUSED")
    return tasks


def _write(path, tasks):
    handle, temporary = tempfile.mkstemp(prefix=".banking-ledger.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"kind": "DSH_BANKING_ALLOWANCE_LEDGER_V1", "tasks": tasks}, stream, indent=1, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sync_directory(directory):
    # Deployed banking scope is POSIX-only. Windows fixture tests prove logical
    # locking, not power-loss durability; they never admit a production scope.
    if os.name == "posix":
        fd = os.open(directory, os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def _used(row):
    settlement=row.get("settlement")
    return settlement["actualRequests"] if settlement is not None else (row["cap"] if row["cap"] is not None else 0) # Unsettled unbounded rows are UNKNOWN, exposed separately by usage.


def _valid_row_cap(row):
    return _int(row.get("cap"),1,MAX_PER_TASK) or row.get("cap","missing") is None and row.get("accountingOnlyAuthority")==AUTHORITY

def require_standing_cli_reservation(task,correlation,*,ledger_file=None,owner_check=None):
    allowance=load_allowance(owner_check=owner_check)
    if not standing(allowance):raise ValueError("STANDING_BANKING_AUTHORITY_REQUIRED")
    path=Path(ledger_file or LEDGER_FILE);_verify_global_store(allowance,path,owner_check=owner_check)
    row=_read(path).get(task,{})
    if row.get("cap","missing") is not None or row.get("accountingOnlyAuthority")!=AUTHORITY or row.get("runtime") not in {"claude","deepagents"} or row.get("binding",{}).get("correlationId")!=correlation:raise ValueError("EXACT_STANDING_CLI_RESERVATION_REQUIRED")
    return True

def _covered(row,baseline):
    return bool(baseline and row.get("settlement") and baseline in row["settlement"]["baselineCoverage"])


def _valid_settlement(row,value,task_id):
    keys={"kind","taskId","originalReservationSha256","actualRequests","guardLedgerSha256","terminalProofSha256","baselineCoverage","binding","ledgerIdentity","evidenceProofSha256s"}
    if (not isinstance(value,dict) or set(value)!=keys or value["kind"]!="DSH_BANKING_TERMINAL_SETTLEMENT_V1"
            or value["taskId"]!=task_id or not _terminal_binding(value["binding"],task_id,row) or not _ledger_identity(value["ledgerIdentity"]) or not _sha_list(value["evidenceProofSha256s"]) or not _int(value["actualRequests"],0,row["cap"])
            or value["originalReservationSha256"]!=_digest({k:v for k,v in row.items() if k!="settlement"})
            or not isinstance(value["baselineCoverage"],list) or any(not isinstance(v,str) or not re.fullmatch(r"[a-f0-9]{64}",v) for v in value["baselineCoverage"])
            or len(value["baselineCoverage"])!=len(set(value["baselineCoverage"]))):
        return False
    return all(isinstance(value[k],str) and re.fullmatch(r"[a-f0-9]{64}",value[k]) for k in ("originalReservationSha256","guardLedgerSha256","terminalProofSha256"))


def settle_terminal_reservation(task_id,proof,guard_ledger,*,verifier,allowance_file=None,ledger_file=None,owner_check=None):
    """One protected terminal settlement, never a caller/API/prompt operation.

    verifier MUST attest exact original task/runtime/image/true exit and baseline
    coverage from retained authoritative evidence. Counts alone or task state
    cannot release a reservation. Original cap/binding retained; no reset/refund
    of used/unknown calls. Repeated identical settlement is idempotent.
    """
    required={"kind","taskId","runtime","project","correlationId","originalReservationSha256",
        "actualRequests","guardLedgerSha256","fenceOperationId","terminalState","trueExitCode","binding","ledgerIdentity",
        "runtimeStopped","runtimeIdentity","ownerEvidenceReference","actualsBaselineSha256","actualsTotalRequests","grantActualsRequests"}
    if (not callable(verifier) or not _terminal_proof_shape(proof) or not isinstance(proof,dict) or set(proof)!=required
            or proof.get("kind")!="DSH_BANKING_TERMINAL_PROOF_V1" or proof.get("taskId")!=task_id
            or proof.get("runtimeStopped") is not True or proof.get("terminalState") not in {"completed","failed","cancelled"}
            or not _int(proof.get("trueExitCode"),0,255) or not isinstance(proof.get("runtimeIdentity"),dict) or not proof["runtimeIdentity"]
            or not isinstance(proof.get("ownerEvidenceReference"),str) or not proof["ownerEvidenceReference"]
            or not isinstance(guard_ledger,bytes) or len(guard_ledger)>262144):
        raise ValueError("VERIFIED_BANKING_TERMINAL_PROOF_REQUIRED")
    if verifier(proof) is not True:raise ValueError("BANKING_TERMINAL_EVIDENCE_NOT_VERIFIED")
    allowance=load_allowance(allowance_file,owner_check=owner_check)
    if allowance is None:raise ValueError("CURRENT_BANKING_ALLOWANCE_REQUIRED")
    path=Path(ledger_file or LEDGER_FILE)
    _verify_global_store(allowance,path,owner_check=owner_check)
    # The same lock domain as reservation; no per-task/global budget fork.
    with _THREAD_LOCK:
        with open(str(path)+".lock","a+") as handle:
            if fcntl is not None:fcntl.flock(handle,fcntl.LOCK_EX)
            elif os.name=="nt":
                import msvcrt
                handle.seek(0,os.SEEK_END)
                if handle.tell()==0:handle.write("0");handle.flush()
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
            else:raise ValueError("BANKING_GLOBAL_LOCK_UNSUPPORTED")
            try:
                tasks=_read(path);row=tasks.get(task_id)
                if row is None or proof["runtime"]!=row["runtime"] or proof["project"]!=row["project"] or proof["originalReservationSha256"]!=_digest({k:v for k,v in row.items() if k!="settlement"}):
                    raise ValueError("BANKING_ORIGINAL_RESERVATION_CHANGED")
                if not _terminal_binding(proof["binding"],task_id,row) or proof["binding"]["correlationId"]!=proof["correlationId"] or not _ledger_identity(proof["ledgerIdentity"]) or proof["ledgerIdentity"]["canonicalLedgerPath"]!=str(path.resolve()):
                    raise ValueError("COMPLETE_ORIGINAL_BANKING_TERMINAL_BINDING_REQUIRED")
                original_sha=proof["ledgerIdentity"]["originalExportSha256"]
                current_raw=path.read_bytes()
                original_raw=current_raw if hashlib.sha256(current_raw).hexdigest()==original_sha else path.with_name(path.name+".pre-settlement-"+original_sha+".json").read_bytes()
                if hashlib.sha256(original_raw).hexdigest()!=original_sha:raise ValueError("BANKING_ORIGINAL_LEDGER_EXPORT_CHANGED")
                old_row=_unique_json(original_raw).get("tasks",{}).get(task_id)
                if old_row is None or {k:v for k,v in old_row.items() if k!="settlement"}!={k:v for k,v in row.items() if k!="settlement"}:
                    raise ValueError("BANKING_ORIGINAL_EXPORTED_RESERVATION_CHANGED")
                from types import SimpleNamespace
                from scripts.banking_sdk_guard_ledger import validate_banking_guard_ledger
                if not re.fullmatch(r"[a-f0-9]{32}",str(proof["correlationId"])) or not re.fullmatch(r"[a-f0-9]{32}",str(proof["fenceOperationId"])):
                    raise ValueError("BANKING_TERMINAL_TASK_FENCE_BINDING_REQUIRED")
                rows=validate_banking_guard_ledger(SimpleNamespace(id=task_id,correlation_id=proof["correlationId"]),guard_ledger,cap=row["cap"],fence_operation=proof["fenceOperationId"])
                count=sum(v["event"]=="upstream-start-reserved" for v in rows)
                if proof["actualRequests"]!=count or type(proof["actualRequests"]) is not int or proof["guardLedgerSha256"]!=hashlib.sha256(guard_ledger).hexdigest():
                    raise ValueError("BANKING_TERMINAL_ACTUALS_MISMATCH")
                if row["runtime"]=="sdk" and row["binding"]["correlationId"]!=proof["correlationId"]:
                    raise ValueError("BANKING_TERMINAL_SDK_BINDING_MISMATCH")
                baseline=proof["actualsBaselineSha256"]
                if baseline is not None:
                    if not re.fullmatch(r"[a-f0-9]{64}",str(baseline)) or baseline!=allowance.get("actualsBaselineSha256") or proof["actualsTotalRequests"]!=allowance["alreadySpentRequests"] or not _int(proof["grantActualsRequests"],count,100000):
                        raise ValueError("BANKING_TERMINAL_BASELINE_NOT_BOUND")
                    grant=next((g for g in allowance["grants"] if g["runtime"]==row["runtime"] and g["project"]==row["project"]),None)
                    if grant and "alreadySpentRequests" in grant and grant["alreadySpentRequests"]!=proof["grantActualsRequests"]:raise ValueError("BANKING_TERMINAL_GRANT_ACTUALS_MISMATCH")
                core={k:v for k,v in proof.items() if k not in {"actualsBaselineSha256","actualsTotalRequests","grantActualsRequests"}}
                record=dict(kind="DSH_BANKING_TERMINAL_SETTLEMENT_V1",taskId=task_id,originalReservationSha256=proof["originalReservationSha256"],actualRequests=count,guardLedgerSha256=proof["guardLedgerSha256"],terminalProofSha256=_digest(core),baselineCoverage=[],binding=dict(proof["binding"]),ledgerIdentity=dict(proof["ledgerIdentity"]),evidenceProofSha256s=[])
                existing=row.get("settlement")
                if existing:
                    if any(existing[k]!=record[k] for k in record if k not in {"baselineCoverage","evidenceProofSha256s"}):raise ValueError("BANKING_SETTLEMENT_REWRITE_REFUSED")
                    record["baselineCoverage"]=list(existing["baselineCoverage"]);record["evidenceProofSha256s"]=list(existing["evidenceProofSha256s"])
                if baseline is not None and baseline not in record["baselineCoverage"]:record["baselineCoverage"].append(baseline)
                proof_sha=_digest(proof)
                if proof_sha not in record["evidenceProofSha256s"]:record["evidenceProofSha256s"].append(proof_sha)
                if existing==record:return False
                original_bytes=path.read_bytes()
                original_sha=hashlib.sha256(original_bytes).hexdigest()
                _retain_evidence(path.with_name(path.name+".pre-settlement-"+original_sha+".json"),original_bytes)
                _retain_evidence(path.with_name(path.name+".proof-"+_digest(proof)+".json"),json.dumps(proof,sort_keys=True,separators=(",",":"),allow_nan=False).encode())
                _retain_evidence(path.with_name(path.name+".guard-"+proof["guardLedgerSha256"]+".jsonl"),guard_ledger)
                row["settlement"]=record;_write(path,tasks);return True
            finally:
                if fcntl is not None:fcntl.flock(handle,fcntl.LOCK_UN)
                elif os.name=="nt":handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)


def _verify_global_store(allowance,path,*,owner_check):
    check=(os.name=="posix") if owner_check is None else owner_check
    if not check:return  # explicit offline fixture only; deployed banking scope is POSIX/root.
    identity=allowance.get("ledgerIdentity")
    keys={"namespace","claimName","claimUID","ledgerPath","lockDomainSha256"}
    if (not isinstance(identity,dict) or set(identity)!=keys or identity["namespace"]!="llm"
            or identity["claimName"]!="dsh-banking-protected-guard-state"
            or identity["ledgerPath"]!=str(LEDGER_FILE) or Path(path)!=LEDGER_FILE
            or not re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}",str(identity["claimUID"]))
            or not re.fullmatch(r"[a-f0-9]{64}",str(identity["lockDomainSha256"]))
            or not os.path.ismount('/state/banking-guard-protected')):
        raise ValueError("ONE_BOUND_PROTECTED_GLOBAL_BANKING_LEDGER_REQUIRED")
    if not path.is_file() or not path.with_name(path.name+'.import.original.json').is_file():
        raise ValueError('BANKING_INITIALIZED_ORIGINAL_IMPORT_REQUIRED')
    info=path.parent.stat()
    if path.parent.is_symlink() or info.st_uid!=0 or info.st_mode&0o077:
        raise ValueError("PROTECTED_GLOBAL_BANKING_LEDGER_OWNER_REQUIRED")


def _retain_evidence(path,data):
    path=Path(path)
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes()!=data:raise ValueError("BANKING_ORIGINAL_EVIDENCE_CHANGED")
        return
    with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
    _sync_directory(path.parent)


def import_original_reservations(raw,expected_sha256,*,ledger_file=None):
    """Protected provisioner-only exact-byte migration; no overwrite/merge/reset.

    Caller must attest source/target authority and bind all three runners to this
    same store before admission. Old workspace stores cannot remain active.
    """
    if not isinstance(raw,bytes) or hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError("BANKING_ORIGINAL_LEDGER_HASH_REQUIRED")
    value=_unique_json(raw)
    if not isinstance(value,dict) or not isinstance(value.get("tasks"),dict):raise ValueError("BANKING_ORIGINAL_LEDGER_SCHEMA_REQUIRED")
    path=Path(ledger_file or LEDGER_FILE)
    anchor=path.with_name(path.name+'.import.original.json')
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError("BANKING_GLOBAL_STORE_ALREADY_BOUND_RECONCILE_ONLY")
        _retain_evidence(anchor,raw)
        _read(path)
        return False
    _retain_evidence(anchor,raw)
    _retain_evidence(path,raw)
    _read(path)  # malformed original refuses; never delete it to retry.
    return True


def _unique_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError("DUPLICATE_BANKING_JSON_FIELD")
            result[key]=value
        return result
    def constant(value):raise ValueError("NONFINITE_BANKING_JSON_REFUSED")
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


def _sha_list(value):
    return isinstance(value,list) and bool(value) and all(isinstance(v,str) and re.fullmatch(r"[a-f0-9]{64}",v) for v in value) and len(value)==len(set(value))


def _ledger_identity(value):
    return isinstance(value,dict) and set(value)=={"canonicalLedgerPath","originalExportSha256"} and isinstance(value["canonicalLedgerPath"],str) and bool(value["canonicalLedgerPath"]) and isinstance(value["originalExportSha256"],str) and re.fullmatch(r"[a-f0-9]{64}",value["originalExportSha256"])


def _terminal_binding(value,task_id,row):
    keys={"subject","generation","runId","taskId","correlationId","runtime","runner","project","writes","promptSha256"}
    runners={"sdk":"official-native-sdk","claude":"managed-claude-code","deepagents":"managed-deepagents"}
    if (not isinstance(value,dict) or set(value)!=keys or value["taskId"]!=task_id
            or value["runtime"]!=row["runtime"] or value["project"]!=row["project"]
            or value["runner"]!=runners.get(row["runtime"]) or type(value["writes"]) is not bool):return False
    if any(not isinstance(value[k],str) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}",value[k]) for k in ("subject","generation","runId")):return False
    if any(not isinstance(value[k],str) or not re.fullmatch(r"[a-f0-9]{%d}"%size,value[k]) for k,size in (("taskId",32),("correlationId",32),("promptSha256",64))):return False
    if "binding" in row and value!=row["binding"]:return False
    return True


def _terminal_proof_shape(value):
    fields={"kind","taskId","runtime","project","correlationId","originalReservationSha256","actualRequests",
        "guardLedgerSha256","fenceOperationId","terminalState","trueExitCode","binding","ledgerIdentity",
        "runtimeStopped","runtimeIdentity","ownerEvidenceReference","actualsBaselineSha256","actualsTotalRequests","grantActualsRequests"}
    if not isinstance(value,dict) or set(value)!=fields:return False
    identity=value.get("runtimeIdentity")
    if (not isinstance(identity,dict) or set(identity)!={"kind","scopeUID","imageDigest","sourceCommit","taskId","correlationId"}
            or identity.get("kind") not in {"workspace-guard","sdk-worker"} or identity.get("taskId")!=value["taskId"]
            or identity.get("correlationId")!=value["correlationId"] or value["runtimeStopped"] is not True
            or value["terminalState"] not in {"completed","failed","cancelled"} or not _int(value["trueExitCode"],0,255)):
        return False
    for key,pattern in (("scopeUID",r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"),("imageDigest",r"[a-f0-9]{64}"),("sourceCommit",r"[a-f0-9]{40}")):
        if not isinstance(identity[key],str) or not re.fullmatch(pattern,identity[key]):return False
    return isinstance(value["ownerEvidenceReference"],str) and re.fullmatch(r"sha256:[a-f0-9]{64}",value["ownerEvidenceReference"])


def _verify_settlement_evidence(path,task_id,row,record):
    try:
        guard_path=path.with_name(path.name+".guard-"+record["guardLedgerSha256"]+".jsonl")
        raw=guard_path.read_bytes()
        if guard_path.is_symlink() or hashlib.sha256(raw).hexdigest()!=record["guardLedgerSha256"]:raise ValueError()
        baselines=set()
        for sha in record["evidenceProofSha256s"]:
            proof_path=path.with_name(path.name+".proof-"+sha+".json");data=proof_path.read_bytes()
            if proof_path.is_symlink() or hashlib.sha256(data).hexdigest()!=sha:raise ValueError()
            proof=_unique_json(data)
            if not _terminal_proof_shape(proof):raise ValueError()
            core={k:v for k,v in proof.items() if k not in {"actualsBaselineSha256","actualsTotalRequests","grantActualsRequests"}}
            if (_digest(core)!=record["terminalProofSha256"] or proof["taskId"]!=task_id or proof["binding"]!=record["binding"]
                    or proof["ledgerIdentity"]!=record["ledgerIdentity"] or proof["actualRequests"]!=record["actualRequests"]
                    or proof["guardLedgerSha256"]!=record["guardLedgerSha256"] or proof["originalReservationSha256"]!=record["originalReservationSha256"]):raise ValueError()
            from types import SimpleNamespace
            from scripts.banking_sdk_guard_ledger import validate_banking_guard_ledger
            rows=validate_banking_guard_ledger(SimpleNamespace(id=task_id,correlation_id=proof["correlationId"]),raw,cap=row["cap"],fence_operation=proof["fenceOperationId"])
            if sum(v["event"]=="upstream-start-reserved" for v in rows)!=record["actualRequests"]:raise ValueError()
            if proof["actualsBaselineSha256"] is not None:baselines.add(proof["actualsBaselineSha256"])
        if baselines!=set(record["baselineCoverage"]):raise ValueError()
    except (OSError,KeyError,TypeError,ValueError) as error:
        raise ValueError("BANKING_SETTLEMENT_EVIDENCE_UNVERIFIED") from None


def _reservation_path(path,task_id):
    path=Path(path)
    return path.with_name(path.name+".reservation-"+hashlib.sha256(task_id.encode()).hexdigest()+".json")


def actual_starts(task_id,*,task_root=None,guard_root=None):
    """Legacy count-only probes are not terminal proof; preserve full charge."""
    return None


def charge(entry):
    if "actual" in entry:raise ValueError("BANKING_UNVERIFIED_LEGACY_ACTUAL_REFUSED")
    return _used(entry)


def settle(tasks,*,task_root=None,guard_root=None):
    raise ValueError("EXPLICIT_VERIFIED_TERMINAL_SETTLEMENT_REQUIRED")


def usage(allowance_file=None,ledger_file=None,*,task_root=None,guard_root=None,owner_check=None):
    """Read-only committed capacity, NOT an actual-spend or grant report."""
    allowance=load_allowance(allowance_file,owner_check=owner_check)
    if allowance is None:return None
    tasks=_read(Path(ledger_file or LEDGER_FILE));baseline=allowance.get("actualsBaselineSha256")
    ledger_charge=sum(_used(v) for v in tasks.values() if not _covered(v,baseline))
    committed=allowance["alreadySpentRequests"]+ledger_charge
    per_grant={}
    for row in tasks.values():
        key=row['runtime']+'/'+row['project'];per_grant[key]=per_grant.get(key,0)+_used(row)
    return dict(accountingMode='CONSERVATIVE_COMMITTED_CAPACITY_NOT_ACTUAL_USAGE',totalRequests=allowance['totalRequests'],alreadySpentRequests=allowance['alreadySpentRequests'],ledgerCharged=ledger_charge,totalCommitted=committed,totalSpent=committed,totalRemaining=None if standing(allowance) else max(0,allowance['totalRequests']-committed),unsettledUnboundedTasks=[k for k,v in tasks.items() if v["cap"] is None and not v.get("settlement")],committedCapacityExcludesUnknownUnbounded=True,perGrantSpent=per_grant,actualSpendNotInferred=True)
