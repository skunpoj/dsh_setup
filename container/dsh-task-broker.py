#!/usr/bin/env python3
"""Private-runtime broker for bounded, authenticated managed-agent tasks."""
import hmac
import copy
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from scripts.agent_runtime_commands import command_for
from scripts.unattended_env import minimal_environment
from scripts.official_sdk_approval import verified_terminal_stop
from scripts import a2a_stage_journal
from scripts.a2a_factory_budget import recover_allowance,WAL_NAME

HOST = "0.0.0.0"
PORT = int(os.environ.get("DSH_TASK_BROKER_PORT", "7682"))
ROOT = Path(os.environ.get("DSH_TASK_STATE_ROOT", "/state/web-tasks"))
WORKSPACE = Path(os.environ.get("DSH_TASK_WORKSPACE_ROOT", "/workspace")).resolve()
TOKEN = Path(os.environ.get("DSH_TASK_TOKEN_FILE", str(Path("/runtime-tokens") / os.environ.get("DSH_ENVIRONMENT", "secure"))))
MAX_BODY = 131072
MAX_EVENT_BYTES = 8 * 1024 * 1024
RUNTIMES = {"sdk", "claude", "deepagents", "kilo"}
# Workspace-local DSH Python SDK tasks (the resumable dsh-sdk-task path behind the per-task guard). OFF unless a root-owned flag file baked
# into the image enables it; never in qualification mode (the qualification broker allows only native sdk tasks and chains).
LOCAL_SDK_FLAG = Path("/opt/dsh/config/local-sdk-tasks.json")
LOCAL_SDK_STAT = os.lstat
LOCAL_SDK_OWNER_CHECK = os.name == "posix"


def local_sdk_enabled():
    if os.environ.get("DSH_NATIVE_QUALIFICATION_MODE") == "1": return False
    try:
        info = LOCAL_SDK_STAT(LOCAL_SDK_FLAG)
        import stat as stat_module
        if not stat_module.S_ISREG(info.st_mode): return False
        if LOCAL_SDK_OWNER_CHECK and (info.st_uid != 0 or info.st_mode & 0o022): return False
        value = json.loads(Path(LOCAL_SDK_FLAG).read_text(encoding="utf-8"))
    except (OSError, ValueError): return False
    return isinstance(value, dict) and set(value) == {"kind", "enabled"} and value["kind"] == "DSH_LOCAL_SDK_TASKS_V1" and value["enabled"] is True
TASK_ID = re.compile(r"^[a-f0-9]{32}$")


def replace_task_journal(temp, path):
    """Bounded local-file replacement only; never repeats a task/model request.

    Windows can deny rename while an ordinary reader briefly holds the old
    file. Keep the already fsynced temp intact and retry only that same rename.
    No permission change, delete-first fallback or security bypass is allowed.
    Persistent denial and every other error propagate before external dispatch.
    """
    delays = (0.01, 0.02, 0.04, 0.08)
    for attempt in range(len(delays) + 1):
        try:
            os.replace(temp, path)
            return
        except PermissionError as error:
            if (sys.platform != "win32" or getattr(error, "winerror", None) not in {5, 32}
                    or attempt == len(delays)):
                raise
            time.sleep(delays[attempt])


def atomic_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        replace_task_journal(temp, path)
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)


def confined_project(value):
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
        raise ValueError("INVALID_PROJECT")
    candidate = (WORKSPACE / value).resolve()
    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError("INVALID_PROJECT")
    if not candidate.is_dir():
        raise ValueError("PROJECT_NOT_FOUND")
    return candidate


class Task:
    def __init__(self, task_id, request, authenticated_subject=None):
        self.id = task_id
        self.authenticated_subject = authenticated_subject
        self.correlation_id = uuid.uuid4().hex
        self.request = request
        self.directory = ROOT / task_id
        self.events = self.directory / "events.jsonl"
        self.process = None
        self.openshell = None
        self.execution_service = None
        self.execution_stage = None
        self.native_stages = []
        self.a2a_stages = []
        self.active_a2a_child = None
        self.a2a_cli_context = None
        self.a2a_cli_worker = None
        self.a2a_cli_cancel = None
        self.a2a_terminal_receipt = None
        self.a2a_factory_allowance = None
        self.factory_budget_fault = False
        self.cli_service = None
        self.native_sdk = None
        self.official_sdk_bridge = None
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.persistence_lock = threading.RLock()
        self.sequence = 0
        self.state = "queued"
        self.created = time.time()
        self.emit("queued", {"runtime": request["runtime"], "project": request["project"]})
        self.save()

    @classmethod
    def recover(cls, value, directory):
        task=cls.__new__(cls);task.id=value["id"];task.request={"runtime":value["runtime"],"project":value["project"],"writes":value.get("writes",False),"handoffRuntime":value.get("handoffRuntime")}
        task.correlation_id=value.get("correlationId", value["id"])
        task.authenticated_subject = value.get("authenticatedSubject")
        task.openshell=value.get("openshell")
        task.execution_service=None
        task.execution_stage=value.get("executionStage")
        task.native_stages=value.get("nativeStages",[])
        task.a2a_stages=a2a_stage_journal.fence(value.get("a2aStages",[]))
        task.active_a2a_child = None  # A recovered reservation is never reattached/replayed.
        task.a2a_cli_context = value.get("a2aCliContext")
        task.a2a_cli_worker = value.get("a2aCliWorker")
        task.a2a_cli_cancel = value.get("a2aCliCancel")
        task.a2a_terminal_receipt = value.get("a2aCliTerminal")
        task.a2a_factory_allowance = value.get("a2aFactoryAllowance")
        task.factory_budget_fault = value.get('factoryBudgetFault',False) is not False
        if task.a2a_factory_allowance is not None and value['state'] not in {'completed','failed','cancelled'}:
            value['state']='interrupted'  # Reserved allowance cannot be replayed after restart.
        task.cli_service = None
        if task.a2a_cli_context and value["state"] not in {"completed", "cancelled"}:
            value["state"] = "interrupted"
        if any(s.get("status") == "fenced" for s in task.a2a_stages):
            value["state"] = "interrupted"
        task.native_sdk=value.get("nativeSdk")
        task.official_sdk_bridge=None
        if task.native_sdk is not None and not verified_terminal_stop(value):
            # Native request IDs belong to the lost client process. Recovery
            # fences them rather than forwarding a saved approval or prompt.
            task.native_sdk["phase"]="fenced-after-recovery"
            if value["state"] not in {"completed","failed","cancelled"}:
                value["state"]="interrupted"
        task.request["backend"]=value.get("backend","private")
        task.finished=threading.Event();task.finished.set()
        task.persistence_lock=threading.RLock()
        task.directory=directory;task.events=directory/"events.jsonl";task.process=None;task.lock=threading.Lock()
        task.sequence=int(value.get("sequence",0));task.state=value["state"];task.created=float(value.get("created",time.time()))
        recover_allowance(task,value.get('a2aFactoryAllowance'))
        if task.factory_budget_fault or task.a2a_factory_allowance is not None and task.state not in {'completed','failed','cancelled'}:
            task.state='interrupted'
        if task.native_sdk is not None or task.a2a_stages or task.a2a_factory_allowance is not None or task.factory_budget_fault: task.save()
        return task

    def reserve_a2a_stage(self, runtime, stage_id, correlation_id):
        with self.persistence_lock:
            if self.state in {"cancelling", "cancelled", "interrupted", "failed"}:
                raise ValueError("A2A_TASK_FENCED")
            stages = a2a_stage_journal.reserve(self.a2a_stages, runtime=runtime,
                stage_id=stage_id, correlation_id=correlation_id)
            self.a2a_stages = stages
            try:
                self.save()  # The caller may dispatch only after this returns.
            except BaseException:
                # Persistence may have committed before reporting failure.
                # Fence in memory and prohibit dispatch or another reservation.
                self.a2a_stages = a2a_stage_journal.fence(stages)
                self.state = "interrupted"
                raise

    def attach_a2a_child(self, child):
        with self.persistence_lock:
            if (not isinstance(child, Task) or child is self or self.active_a2a_child is not None
                    or self.state in {"cancelled", "cancelling", "failed", "interrupted"}
                    or child.request["project"] != self.request["project"]
                    or child.request.get("backend", "private") != "private"
                    or (child.request["writes"] and not self.request["writes"])
                    or not self.a2a_stages):
                raise ValueError("A2A_CHILD_BINDING_REFUSED")
            stage = self.a2a_stages[-1]
            if (stage["status"] != "reserved" or stage["stageId"] != child.id
                    or stage["correlationId"] != child.correlation_id
                    or stage["runtime"] != child.request["runtime"] or child.state != "queued"):
                raise ValueError("A2A_CHILD_BINDING_REFUSED")
            self.active_a2a_child = child

    def run_a2a_chain(self, execute_stage):
        """Broker-configured executor only; not a client-provided callable.

        Executor returns private output after persisting exact terminal proof
        on its child Task. No retry, replay or unguarded subprocess fallback.
        """
        runtimes = [self.request["runtime"], self.request.get("handoffRuntime")]
        if (any(r not in a2a_stage_journal.RUNTIMES for r in runtimes)
                or runtimes[0] == runtimes[1] or self.a2a_stages):
            raise ValueError("A2A_CHAIN_REQUEST_REFUSED")
        self.finished.clear()
        try:
            with self.persistence_lock:
                if self.state != "queued":
                    raise ValueError("A2A_TASK_FENCED")
                self.state = "running"; self.save()
            prompt = self.request["prompt"]
            for index, runtime in enumerate(runtimes):
                child = Task(uuid.uuid4().hex, dict(runtime=runtime, backend="private",
                    project=self.request["project"], writes=self.request["writes"], prompt=prompt),
                    authenticated_subject=self.authenticated_subject)
                self.reserve_a2a_stage(runtime, child.id, child.correlation_id)
                self.attach_a2a_child(child)
                output = execute_stage(child)
                if runtime == "sdk":
                    self.complete_native_a2a_stage(child, output)
                else:
                    with child.persistence_lock:
                        proof = getattr(child, "a2a_terminal_receipt", None)
                        if child.state != "completed" or not child.finished.is_set():
                            raise ValueError("A2A_CHILD_NOT_RETIRED_OR_FOREIGN_PROJECT")
                    with self.persistence_lock:
                        if self.state != "running": raise ValueError("A2A_TASK_FENCED")
                        self.a2a_stages = a2a_stage_journal.complete(self.a2a_stages,
                            stage_id=child.id, output=output, terminal_receipt=proof)
                        self.save()
                with self.persistence_lock:
                    if self.state != "running": raise ValueError("A2A_TASK_FENCED")
                    self.active_a2a_child = None
                if index == 0:
                    prompt = (self.request.get("handoffPrompt") or "Review the previous result.") + "\n\nPrevious agent result:\n" + output
                    if len(prompt) > 65536: raise ValueError("A2A_HANDOFF_PROMPT_TOO_LARGE")
                else:
                    self.emit("output", dict(runtime=runtime, text=output[:16384]))
            with self.persistence_lock:
                if self.state != "running": raise ValueError("A2A_TASK_FENCED")
                self.state = "completed"; self.save()
        except BaseException:
            with self.persistence_lock:
                self.a2a_stages = a2a_stage_journal.fence(self.a2a_stages)
                if self.state != "cancelled": self.state = "interrupted"
                self.save()
        finally:
            self.finished.set()

    def a2a_approval_ticket(self, subject):
        with self.persistence_lock:
            child = self.active_a2a_child
            if child is None:
                return None
            with child.persistence_lock:
                native = child.native_sdk
                if native and subject != native["subject"]:
                    raise ValueError("FOREIGN_NATIVE_SDK_SUBJECT")
                if (self.state in {"cancelling", "cancelled", "interrupted", "failed"}
                        or not self.a2a_stages or not native):
                    return None
                stage = self.a2a_stages[-1]
                if (stage["status"] != "reserved" or stage["stageId"] != child.id
                        or stage["correlationId"] != child.correlation_id
                        or native["phase"] != "awaiting-approval"
                        or child.state != "awaiting_approval" or not native.get("pending")):
                    return None
                pending = native["pending"]
                return dict(approvalId=pending["approvalId"], generation=native["generation"],
                    toolName=pending["toolName"], callId=pending["callId"],
                    allowOnceAdmitted=child.request["writes"] is True,
                    stageId=child.id, correlationId=child.correlation_id)

    def decide_a2a(self, *, subject, generation, approval_id, outcome):
        with self.persistence_lock:
            child = self.active_a2a_child
            if (self.state in {"cancelling", "cancelled", "interrupted", "failed"}
                    or child is None or not self.a2a_stages):
                raise ValueError("A2A_APPROVAL_STAGE_UNAVAILABLE")
            stage = self.a2a_stages[-1]
            if (stage["status"] != "reserved" or stage["runtime"] != "sdk"
                    or child.id != stage["stageId"]
                    or child.correlation_id != stage["correlationId"]
                    or child.official_sdk_bridge is None):
                raise ValueError("A2A_APPROVAL_STAGE_UNAVAILABLE")
            # The child's existing bridge checks authenticated subject, exact
            # generation and decision ID and persists its one-shot reservation.
            return child.official_sdk_bridge.decide(subject=subject,
                generation=generation, approval_id=approval_id, outcome=outcome)

    def complete_native_a2a_stage(self, native_task, output):
        if not isinstance(native_task, Task) or native_task is self:
            raise ValueError("A2A_CHILD_TASK_REQUIRED")
        # Snapshot only a broker-owned Task; no HTTP-supplied receipt is accepted.
        with native_task.persistence_lock:
            if (not native_task.finished.is_set() or
                    native_task.request["project"] != self.request["project"]):
                raise ValueError("A2A_CHILD_NOT_RETIRED_OR_FOREIGN_PROJECT")
            record = dict(id=native_task.id, project=native_task.request["project"],
                correlationId=native_task.correlation_id, state=native_task.state,
                nativeSdk=copy.deepcopy(native_task.native_sdk))
        with self.persistence_lock:
                if self.state in {"cancelling", "cancelled", "interrupted", "failed"}:
                    raise ValueError("A2A_TASK_FENCED")
                stages = a2a_stage_journal.complete_native(self.a2a_stages,
                    record=record, output=output)
                self.a2a_stages = stages
                try:
                    self.save()
                except BaseException:
                    self.state = "interrupted"
                    raise

    def save(self):
        with self.persistence_lock:
            atomic_json(self.directory / "task.json", {
                "id": self.id, "runtime": self.request["runtime"], "project": self.request["project"],
                "authenticatedSubject": self.authenticated_subject,
                "correlationId": self.correlation_id,
                "openshell": self.openshell,
                "executionStage": self.execution_stage,
                "nativeStages": self.native_stages,
                "a2aStages": self.a2a_stages,
                "a2aCliContext": self.a2a_cli_context,
                "a2aCliWorker": self.a2a_cli_worker,
                "a2aCliCancel": self.a2a_cli_cancel,
                "a2aCliTerminal": self.a2a_terminal_receipt,
                "a2aFactoryAllowance": self.a2a_factory_allowance,
                "factoryBudgetFault": self.factory_budget_fault,
                "nativeSdk": self.native_sdk,
                "backend": self.request.get("backend","private"),
                "writes": self.request["writes"], "handoffRuntime": self.request.get("handoffRuntime"),
                "state": self.state, "created": self.created,
                "updated": time.time(), "sequence": self.sequence,
            })

    def emit(self, kind, data):
        with self.lock:
            if kind == "output" and self.events.exists() and self.events.stat().st_size >= MAX_EVENT_BYTES:
                return
            self.sequence += 1
            record = {"sequence": self.sequence, "at": time.time(), "type": kind, "data": data}
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with self.events.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.chmod(self.events, 0o600)

    def run(self, resume=False):
        self.finished.clear()
        self.state = "running"; self.emit("state", {"state": self.state}); self.save()
        project = confined_project(self.request["project"])
        env = minimal_environment(os.environ)  # explicit allowlist: no provider keys, no Kerberos cache, no node preloads
        env["DSH_UNATTENDED_TASK"] = self.id
        env["DSH_CORRELATION_ID"] = self.correlation_id
        try:
            runtime = self.request["runtime"]
            command = command_for(runtime, self.request.get("prompt", ""), self.request["writes"], project, self.id, resume)
            self.process = subprocess.Popen(command, cwd=project, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True, bufsize=1)
            captured=[];captured_bytes=0
            for line in self.process.stdout:
                self.emit("output", {"text": line[:16384], "runtime": runtime})
                if captured_bytes < 262144:
                    piece=line.encode("utf-8",errors="replace")[:262144-captured_bytes].decode("utf-8",errors="replace")
                    captured.append(piece);captured_bytes += len(piece.encode("utf-8"))
            code=self.process.wait()
            handoff_runtime=self.request.get("handoffRuntime")
            if self.official_sdk_bridge is not None:
                if self.state != "cancelled":
                    self.official_sdk_bridge.finalize("completed" if code == 0 else "failed")
                if self.state != "completed" or not handoff_runtime:
                    return  # Never overwrite interrupted/unverified native cleanup.
                # The first native session has exact exit proof before handoff.
                # Keep its proof in Task metadata, detach only its live adapter.
                self.official_sdk_bridge = None
            if self.state in {"cancelling", "cancelled"}: self.state = "cancelled"
            elif code == 75 and runtime == "sdk": self.state = "awaiting_approval"
            elif code != 0: self.state = "failed"
            elif handoff_runtime and not resume: self.state = "handoff"
            else: self.state = "completed"
            self.emit("state", {"state": self.state, "exitCode": code, "runtime": runtime})
            if self.state == "handoff":
                instruction=self.request.get("handoffPrompt") or "Review the previous agent result and produce the final checked answer."
                handoff_prompt=instruction+"\n\nPrevious agent result:\n"+"".join(captured)
                handoff_correlation_id=uuid.uuid4().hex
                self.emit("handoff", {"from":runtime,"to":handoff_runtime,
                                      "correlationId":handoff_correlation_id})
                if self.state != "handoff":
                    return
                self.state="running";self.save()
                handoff_id=self.id+"-handoff";env=dict(env);env["DSH_UNATTENDED_TASK"]=handoff_id
                env["DSH_CORRELATION_ID"] = handoff_correlation_id
                command=command_for(handoff_runtime,handoff_prompt,self.request["writes"],project,handoff_id)
                self.process=subprocess.Popen(command,cwd=project,env=env,stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,text=True,errors="replace",start_new_session=True,bufsize=1)
                for line in self.process.stdout:self.emit("output",{"text":line[:16384],"runtime":handoff_runtime})
                code=self.process.wait()
                if self.state in {"cancelling", "cancelled"}:
                    self.state="cancelled"
                elif code == 75 and handoff_runtime == "sdk":
                    # Until stage-specific checkpoint resume is implemented, fail
                    # closed rather than resume the first agent's checkpoint.
                    self.state="interrupted"
                else:
                    self.state="completed" if code==0 else "failed"
                self.emit("state",{"state":self.state,"exitCode":code,"runtime":handoff_runtime})
        except Exception as error:
            if self.official_sdk_bridge is not None:
                self.official_sdk_bridge.finalize("failed")
            else:
                self.state = "failed"
            self.emit("state", {"state": self.state, "error": type(error).__name__})
        finally:
            self.process = None
            try: self.save()
            finally: self.finished.set()

    def cancel(self):
        with self.persistence_lock:
            child = self.active_a2a_child
            if child is not None:
                self.state = "cancelling"
                self.a2a_stages = a2a_stage_journal.fence(self.a2a_stages)
                self.save()  # Fence parent before invoking any child transport.
        if child is not None:
            try:
                stopped = child.cancel()
                with child.persistence_lock:
                    proof = dict(id=child.id, project=child.request["project"],
                        correlationId=child.correlation_id, state=child.state, nativeSdk=child.native_sdk)
                    cli_proof = getattr(child, "a2a_terminal_receipt", None)
                    cli_verified = (isinstance(cli_proof, dict)
                        and cli_proof.get("stageId") == child.id
                        and cli_proof.get("correlationId") == child.correlation_id
                        and cli_proof.get("descendantAbsenceVerified") is True
                        and cli_proof.get("stopped") is True
                        and cli_proof.get("processExitVerified") is True)
                    verified = (stopped is True and child.finished.is_set()
                        and child.state == "cancelled" and (verified_terminal_stop(proof) or cli_verified))
            except Exception:
                verified = False
            with self.persistence_lock:
                self.state = "cancelled" if verified else "interrupted"
                if verified and self.a2a_stages:
                    self.a2a_stages[-1]["terminalVerified"] = True
                self.save()
            return verified
        if self.cli_service is not None:
            return self.cli_service.cancel_task(self.cli_service.subject, self)
        if self.official_sdk_bridge is not None:
            return self.official_sdk_bridge.cancel()
        if self.state not in {"queued", "running", "handoff", "finalizing", "awaiting_approval"}: return False
        if self.request.get("backend")=="openshell":
            if self.execution_service is None:return False
            return self.execution_service.cancel_task(self.execution_service.subject,self)
        self.state = "cancelling"; self.emit("state", {"state": self.state}); self.save()
        process = self.process
        if process and process.poll() is None:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        self.state = "cancelled"; self.emit("state", {"state": self.state}); self.save(); return True

    def approve(self):
        if self.native_sdk is not None:
            # Native approvals require the exact decision ID and generation;
            # the old checkpoint-resume action must never restart this client.
            return False
        if self.state != "awaiting_approval" or self.request["runtime"] != "sdk": return False
        self.finished.clear()
        self.state = "queued"; self.emit("state", {"state": self.state, "resuming": True}); self.save()
        threading.Thread(target=self.run, kwargs={"resume": True}, daemon=True).start(); return True


class Registry:
    def __init__(self):
        self.tasks = {}; self.lock = threading.Lock(); ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.factory_budget_faults=[]
        for file in ROOT.glob("*/task.json"):
            try:
                value = json.loads(file.read_text(encoding="utf-8"))
                if value.get("state") in {"queued", "running", "handoff", "finalizing", "cancelling"}:
                    value["state"] = "interrupted"; atomic_json(file, value)
                if TASK_ID.fullmatch(value.get("id","")) and value.get("state") in {"completed","failed","cancelled","interrupted","awaiting_approval"}:
                    self.tasks[value["id"]]=Task.recover(value,file.parent)
                    if self.tasks[value['id']].factory_budget_fault:self.factory_budget_faults.append(value['id'])
            except Exception: pass
        for marker in ROOT.glob('*/'+WAL_NAME):
            task=self.tasks.get(marker.parent.name)
            if task is None or getattr(task,'factory_budget_fault',False):
                self.factory_budget_faults.append(marker.parent.name)

    def create(self, request, execution_service=None, sdk_service=None, a2a_executor=None, authenticated_subject=None):
        with self.lock:
            if self.factory_budget_faults:raise RuntimeError('FACTORY_GRANT_DURABILITY_UNRESOLVED')
            if any(t.state in {"queued", "running", "handoff", "finalizing", "cancelling", "awaiting_approval"}
                   or any(s.get("status") in {"reserved", "fenced"}
                       and s.get("terminalVerified") is not True for s in t.a2a_stages)
                   or (t.a2a_cli_context and not (t.a2a_terminal_receipt
                       and t.a2a_terminal_receipt.get("descendantAbsenceVerified") is True))
                   or (t.a2a_cli_worker and t.a2a_cli_worker.get('phase') != 'retired')
                   or (t.native_sdk and t.native_sdk.get("phase")!="stopped")
                   or (t.native_sdk and t.native_sdk.get("managedSession") and not t.finished.is_set())
                   or (t.request.get("backend")=="openshell" and t.openshell and t.openshell.get("phase")!="stopped")
                   for t in self.tasks.values()):
                raise RuntimeError("TASK_ALREADY_ACTIVE")
            local_sdk = (sdk_service is None and request["runtime"]=="sdk" and request.get("handoffRuntime") is None
                         and request.get("backend","private")=="private" and local_sdk_enabled())
            if (request.get("backend","private")=="private" and request["runtime"]=="sdk" and not local_sdk
                    and (sdk_service is None or sdk_service.qualified is not True)):
                raise RuntimeError("OFFICIAL_SDK_NOT_QUALIFIED")
            native_chain = (request.get("backend", "private") == "private"
                and request.get("handoffRuntime") is not None
                and "sdk" in {request["runtime"], request["handoffRuntime"]})
            if native_chain and (a2a_executor is None or a2a_executor.qualified is not True):
                raise RuntimeError("NATIVE_SDK_HANDOFF_NOT_YET_QUALIFIED")
            task = Task(uuid.uuid4().hex, request, authenticated_subject=authenticated_subject); self.tasks[task.id] = task
            if native_chain:
                threading.Thread(target=task.run_a2a_chain,args=(a2a_executor,),daemon=True).start()
            elif request.get("backend")=="openshell":
                if execution_service is None:
                    self.tasks.pop(task.id);raise RuntimeError("OPENSHELL_NOT_QUALIFIED")
                task.execution_service=execution_service
                threading.Thread(target=execution_service.run_task,args=(execution_service.subject,task),daemon=True).start()
            elif request["runtime"]=="sdk" and not local_sdk:
                threading.Thread(target=sdk_service.run_task,args=(sdk_service.subject,task),daemon=True).start()
            else:
                threading.Thread(target=task.run, daemon=True).start()
            return task

    def get(self, task_id):
        if not TASK_ID.fullmatch(task_id): return None
        return self.tasks.get(task_id)


REGISTRY = Registry()


class Handler(BaseHTTPRequestHandler):
    server_version = "DSHTaskBroker/1"
    def log_message(self, *_): pass
    def reply(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def authorized(self):
        try: expected = TOKEN.read_text(encoding="utf-8").strip()
        except OSError: return False
        supplied = self.headers.get("Authorization", "")
        return len(expected) >= 20 and hmac.compare_digest(supplied, "Bearer " + expected)
    def body(self):
        try: size = int(self.headers.get("Content-Length", "0"))
        except ValueError: raise ValueError("INVALID_LENGTH")
        if size < 2 or size > MAX_BODY: raise ValueError("INVALID_LENGTH")
        return json.loads(self.rfile.read(size))
    def do_GET(self):
        if not self.authorized(): return self.reply(401, {"error":"UNAUTHORIZED"})
        path = urlparse(self.path).path
        if path == "/health": return self.reply(200, {"status":"ok"})
        if path == "/v1/capabilities":
            service=getattr(self.server,"openshell_service",None)
            enabled=service is not None and service.qualified is True
            sdk=getattr(self.server,"sdk_service",None)
            sdk_enabled=sdk is not None and sdk.qualified is True
            a2a=getattr(self.server,"a2a_executor",None)
            a2a_enabled=a2a is not None and a2a.qualified is True
            return self.reply(200, {"runtimes":sorted(RUNTIMES),
                "runtimeDetails":{"sdk":{"enabled":sdk_enabled,"implementation":"official-native",
                    "handoffEnabled":a2a_enabled,"reason":"Qualified native runner configured" if sdk_enabled else "Official SDK native runtime qualification pending"}},
                "backends":[{"id":"private","enabled":True},{"id":"openshell","enabled":enabled,"reason":"Qualified native transport" if enabled else "OpenShell requires 25-gate Test and rollback qualification"}]})
        match = re.fullmatch(r"/v1/tasks/([a-f0-9]{32})/events", path)
        if match:
            task = REGISTRY.get(match.group(1))
            if not task: return self.reply(404, {"error":"TASK_NOT_FOUND"})
            if task.authenticated_subject is not None and self.headers.get("X-DSH-Subject", "") != task.authenticated_subject:
                return self.reply(403,{"error":"FOREIGN_TASK_SUBJECT"})
            if task.native_sdk and self.headers.get("X-DSH-Subject","")!=task.native_sdk["subject"]:
                return self.reply(403,{"error":"FOREIGN_NATIVE_SDK_SUBJECT"})
            try:
                a2a_ticket = task.a2a_approval_ticket(self.headers.get("X-DSH-Subject", ""))
            except ValueError:
                return self.reply(403,{"error":"FOREIGN_NATIVE_SDK_SUBJECT"})
            try: after = max(0, int(dict(x.split("=",1) for x in urlparse(self.path).query.split("&") if "=" in x).get("after","0")))
            except ValueError: return self.reply(400, {"error":"INVALID_CURSOR"})
            rows=[]
            if task.events.exists():
                for line in task.events.read_text(encoding="utf-8").splitlines():
                    row=json.loads(line)
                    if row["sequence"] > after: rows.append(row)
            ticket=None
            with task.persistence_lock:
                native=task.native_sdk
                if (native and native["phase"]=="awaiting-approval"
                        and task.state=="awaiting_approval" and native["pending"]):
                    pending=native["pending"]
                    ticket={"approvalId":pending["approvalId"],"generation":native["generation"],
                            "toolName":pending["toolName"],"callId":pending["callId"],
                            "allowOnceAdmitted":task.request["writes"] is True}
            ticket = a2a_ticket or ticket
            return self.reply(200, {"taskId":task.id,"state":"awaiting_approval" if a2a_ticket else task.state,"events":rows[:200],"next":(rows[:200][-1]["sequence"] if rows else after),"nativeApproval":ticket})  # first page after the cursor: a client that advances with `next` never skips events
        return self.reply(404, {"error":"NOT_FOUND"})
    def do_POST(self):
        if not self.authorized(): return self.reply(401, {"error":"UNAUTHORIZED"})
        path=urlparse(self.path).path
        openshell=re.fullmatch(r"/v1/tasks/([a-f0-9]{32})/openshell/(bind|resolve|dispatch|revoke|stop)",path)
        if openshell:
            service=getattr(self.server,"openshell_service",None)
            if service is None:
                return self.reply(503,{"error":"OPENSHELL_NOT_QUALIFIED"})
            try:
                value=service.operate(self.headers.get("X-DSH-Subject",""),
                                      openshell.group(1),openshell.group(2),self.body())
                return self.reply(200,value)
            except (ValueError,json.JSONDecodeError) as error:
                return self.reply(400,{"error":str(error)})
            except Exception:
                return self.reply(503,{"error":"OPENSHELL_OPERATION_UNCERTAIN"})
        approval=re.fullmatch(r"/v1/tasks/([a-f0-9]{32})/approve",path)
        if approval:
            try:
                value=self.body()
                if not isinstance(value,dict): raise ValueError("APPROVAL_REQUIRED")
            except (ValueError,json.JSONDecodeError) as error:return self.reply(400,{"error":str(error)})
            task=REGISTRY.get(approval.group(1))
            if not task:return self.reply(404,{"error":"TASK_NOT_FOUND"})
            if task.authenticated_subject is not None and self.headers.get("X-DSH-Subject", "") != task.authenticated_subject:
                return self.reply(403,{"error":"FOREIGN_TASK_SUBJECT"})
            if task.active_a2a_child is not None:
                if set(value)!={"approvalId","generation","outcome"}:
                    return self.reply(409,{"error":"NATIVE_APPROVAL_TICKET_REQUIRED"})
                try:
                    task.decide_a2a(subject=self.headers.get("X-DSH-Subject",""),
                        generation=value["generation"], approval_id=value["approvalId"], outcome=value["outcome"])
                    return self.reply(202,{"taskId":task.id,"state":task.state})
                except ValueError as error:return self.reply(409,{"error":str(error)})
                except Exception:return self.reply(503,{"error":"NATIVE_APPROVAL_UNCERTAIN"})
            if task.native_sdk is not None:
                if (set(value)!={"approvalId","generation","outcome"}
                        or task.official_sdk_bridge is None):
                    return self.reply(409,{"error":"NATIVE_APPROVAL_TICKET_REQUIRED"})
                try:
                    task.official_sdk_bridge.decide(subject=self.headers.get("X-DSH-Subject",""),
                        generation=value["generation"],approval_id=value["approvalId"],outcome=value["outcome"])
                    return self.reply(202,{"taskId":task.id,"state":task.state})
                except ValueError as error:return self.reply(409,{"error":str(error)})
                except Exception:return self.reply(503,{"error":"NATIVE_APPROVAL_UNCERTAIN"})
            if value != {"approved":True}:return self.reply(400,{"error":"APPROVAL_REQUIRED"})
            return self.reply(202 if task.approve() else 409,{"taskId":task.id,"state":task.state})
        if path != "/v1/tasks": return self.reply(404,{"error":"NOT_FOUND"})
        try:
            value=self.body()
            required={"runtime","backend","project","prompt","writes","approved"};optional={"handoffRuntime","handoffPrompt"}
            if not isinstance(value,dict) or not required.issubset(value) or not set(value).issubset(required|optional): raise ValueError("INVALID_REQUEST")
            service=None;sdk_service=None
            a2a_executor=getattr(self.server,"a2a_executor",None)
            a2a_enabled=a2a_executor is not None and a2a_executor.qualified is True
            if value["runtime"] not in RUNTIMES or value["backend"] not in {"private","openshell"}: raise ValueError("UNAVAILABLE_SELECTION")
            if value["runtime"]=="sdk" and value["backend"]=="openshell":
                raise ValueError("OFFICIAL_SDK_NATIVE_WORKER_NOT_QUALIFIED")
            if value["backend"]=="openshell":
                service=getattr(self.server,"openshell_service",None)
                if service is None or not service.qualified:raise ValueError("UNAVAILABLE_SELECTION")
                if self.headers.get("X-DSH-Subject","")!=service.subject:raise ValueError("FOREIGN_SUBJECT")
            elif value["runtime"]=="sdk" and value["backend"]=="private" and value.get("handoffRuntime") is None and local_sdk_enabled():
                sdk_service=None  # workspace-local resumable SDK task; the per-task guard still wraps it
            elif value["runtime"]=="sdk":
                sdk_service=getattr(self.server,"sdk_service",None)
                if sdk_service is None or sdk_service.qualified is not True:
                    return self.reply(503,{"error":"OFFICIAL_SDK_NOT_QUALIFIED"})
                if self.headers.get("X-DSH-Subject","")!=sdk_service.subject:
                    raise ValueError("FOREIGN_NATIVE_SDK_SUBJECT")
                if value.get("handoffRuntime") and not a2a_enabled:
                    raise ValueError("NATIVE_SDK_HANDOFF_NOT_YET_QUALIFIED")
            if value.get("handoffRuntime") is not None:
                if "sdk" in {value["runtime"],value["handoffRuntime"]} and value["backend"] != "private":
                    raise ValueError("NATIVE_SDK_HANDOFF_PRIVATE_ONLY")
                if value["handoffRuntime"]=="sdk" and not a2a_enabled:raise ValueError("NATIVE_SDK_HANDOFF_NOT_YET_QUALIFIED")
                if value["handoffRuntime"] not in RUNTIMES or value["handoffRuntime"]==value["runtime"]: raise ValueError("INVALID_HANDOFF_RUNTIME")
                if not isinstance(value.get("handoffPrompt",""),str) or len(value.get("handoffPrompt",""))>65536: raise ValueError("INVALID_HANDOFF_PROMPT")
            if value["approved"] is not True or not isinstance(value["writes"],bool): raise ValueError("APPROVAL_REQUIRED")
            if not isinstance(value["prompt"],str) or not 1<=len(value["prompt"])<=65536: raise ValueError("INVALID_PROMPT")
            confined_project(value["project"])
            if (value.get("handoffRuntime") and "sdk" in {value["runtime"],value["handoffRuntime"]}
                    and (not a2a_enabled or self.headers.get("X-DSH-Subject", "") != a2a_executor.subject)):
                raise ValueError("FOREIGN_NATIVE_SDK_SUBJECT")
            task=REGISTRY.create(value,execution_service=service,sdk_service=sdk_service,a2a_executor=a2a_executor,authenticated_subject=self.headers.get("X-DSH-Subject") or None); return self.reply(202,{"taskId":task.id,"state":task.state,"correlationId":task.correlation_id})
        except (ValueError, json.JSONDecodeError) as error: return self.reply(400,{"error":str(error)})
        except RuntimeError as error: return self.reply(409,{"error":str(error)})
    def do_DELETE(self):
        if not self.authorized(): return self.reply(401,{"error":"UNAUTHORIZED"})
        match=re.fullmatch(r"/v1/tasks/([a-f0-9]{32})",urlparse(self.path).path)
        if not match: return self.reply(404,{"error":"NOT_FOUND"})
        task=REGISTRY.get(match.group(1))
        if not task: return self.reply(404,{"error":"TASK_NOT_FOUND"})
        if task.authenticated_subject is not None and self.headers.get("X-DSH-Subject", "") != task.authenticated_subject:
            return self.reply(403,{"error":"FOREIGN_TASK_SUBJECT"})
        if task.native_sdk and self.headers.get("X-DSH-Subject","")!=task.native_sdk["subject"]:
            return self.reply(403,{"error":"FOREIGN_NATIVE_SDK_SUBJECT"})
        return self.reply(202 if task.cancel() else 409,{"taskId":task.id,"state":task.state})


if __name__ == "__main__":
    os.umask(0o077)
    try:
        from scripts.openshell_bootstrap import configure
    except ModuleNotFoundError as error:
        # The OpenShell bootstrap lives on the OpenShell lane's branch. Without it the OpenShell backend stays DISABLED
        # (fail closed): no openshell_service is installed, so /v1/capabilities reports it disabled and create refuses it.
        if error.name not in ('scripts.openshell_bootstrap', 'scripts.openshell_broker_transport'):
            raise
        configure = None
        print('OpenShell bootstrap module absent: OpenShell backend disabled', file=sys.stderr, flush=True)
    server=ThreadingHTTPServer((HOST, PORT), Handler)
    if configure is not None:
        configure(server,REGISTRY,os.environ.get('DSH_OPENSHELL_ADMISSION_FILE'))
    from scripts.official_sdk_bootstrap import configure as configure_official_sdk
    configure_official_sdk(server, REGISTRY, os.environ.get('DSH_OFFICIAL_SDK_ADMISSION_FILE'),
        qualification_allowed=os.environ.get('DSH_NATIVE_QUALIFICATION_MODE') == '1',
        workspace_root=WORKSPACE)
    server.serve_forever()
