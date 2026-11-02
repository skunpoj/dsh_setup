#!/usr/bin/env python3
"""Private-runtime broker for bounded, authenticated managed-agent tasks."""
import hmac
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from scripts.agent_runtime_commands import command_for
from scripts.official_sdk_approval import verified_terminal_stop

HOST = "0.0.0.0"
PORT = int(os.environ.get("DSH_TASK_BROKER_PORT", "7682"))
ROOT = Path(os.environ.get("DSH_TASK_STATE_ROOT", "/state/web-tasks"))
WORKSPACE = Path(os.environ.get("DSH_TASK_WORKSPACE_ROOT", "/workspace")).resolve()
TOKEN = Path(os.environ.get("DSH_TASK_TOKEN_FILE", str(Path("/runtime-tokens") / os.environ.get("DSH_ENVIRONMENT", "secure"))))
MAX_BODY = 131072
MAX_EVENT_BYTES = 8 * 1024 * 1024
RUNTIMES = {"sdk", "claude", "deepagents", "kilo"}
TASK_ID = re.compile(r"^[a-f0-9]{32}$")


def atomic_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
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
    def __init__(self, task_id, request):
        self.id = task_id
        self.correlation_id = uuid.uuid4().hex
        self.request = request
        self.directory = ROOT / task_id
        self.events = self.directory / "events.jsonl"
        self.process = None
        self.openshell = None
        self.execution_service = None
        self.execution_stage = None
        self.native_stages = []
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
        task.openshell=value.get("openshell")
        task.execution_service=None
        task.execution_stage=value.get("executionStage")
        task.native_stages=value.get("nativeStages",[])
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
        if task.native_sdk is not None: task.save()
        return task

    def save(self):
        with self.persistence_lock:
            atomic_json(self.directory / "task.json", {
                "id": self.id, "runtime": self.request["runtime"], "project": self.request["project"],
                "correlationId": self.correlation_id,
                "openshell": self.openshell,
                "executionStage": self.execution_stage,
                "nativeStages": self.native_stages,
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
        env = dict(os.environ)
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
        for file in ROOT.glob("*/task.json"):
            try:
                value = json.loads(file.read_text(encoding="utf-8"))
                if value.get("state") in {"queued", "running", "handoff", "finalizing", "cancelling"}:
                    value["state"] = "interrupted"; atomic_json(file, value)
                if TASK_ID.fullmatch(value.get("id","")) and value.get("state") in {"completed","failed","cancelled","interrupted","awaiting_approval"}:
                    self.tasks[value["id"]]=Task.recover(value,file.parent)
            except Exception: pass

    def create(self, request, execution_service=None, sdk_service=None):
        with self.lock:
            if any(t.state in {"queued", "running", "handoff", "finalizing", "cancelling", "awaiting_approval"}
                   or (t.native_sdk and t.native_sdk.get("phase")!="stopped")
                   or (t.native_sdk and t.native_sdk.get("managedSession") and not t.finished.is_set())
                   or (t.request.get("backend")=="openshell" and t.openshell and t.openshell.get("phase")!="stopped")
                   for t in self.tasks.values()):
                raise RuntimeError("TASK_ALREADY_ACTIVE")
            if (request.get("backend","private")=="private" and request["runtime"]=="sdk"
                    and (sdk_service is None or sdk_service.qualified is not True)):
                raise RuntimeError("OFFICIAL_SDK_NOT_QUALIFIED")
            task = Task(uuid.uuid4().hex, request); self.tasks[task.id] = task
            if request.get("backend")=="openshell":
                if execution_service is None:
                    self.tasks.pop(task.id);raise RuntimeError("OPENSHELL_NOT_QUALIFIED")
                task.execution_service=execution_service
                threading.Thread(target=execution_service.run_task,args=(execution_service.subject,task),daemon=True).start()
            elif request["runtime"]=="sdk":
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
            return self.reply(200, {"runtimes":sorted(RUNTIMES),
                "runtimeDetails":{"sdk":{"enabled":sdk_enabled,"implementation":"official-native",
                    "handoffEnabled":False,"reason":"Qualified native runner configured" if sdk_enabled else "Official SDK native runtime qualification pending"}},
                "backends":[{"id":"private","enabled":True},{"id":"openshell","enabled":enabled,"reason":"Qualified native transport" if enabled else "OpenShell requires 25-gate Test and rollback qualification"}]})
        match = re.fullmatch(r"/v1/tasks/([a-f0-9]{32})/events", path)
        if match:
            task = REGISTRY.get(match.group(1))
            if not task: return self.reply(404, {"error":"TASK_NOT_FOUND"})
            if task.native_sdk and self.headers.get("X-DSH-Subject","")!=task.native_sdk["subject"]:
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
            return self.reply(200, {"taskId":task.id,"state":task.state,"events":rows[-200:],"next":task.sequence,"nativeApproval":ticket})
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
            if value["runtime"] not in RUNTIMES or value["backend"] not in {"private","openshell"}: raise ValueError("UNAVAILABLE_SELECTION")
            if value["runtime"]=="sdk" and value["backend"]=="openshell":
                raise ValueError("OFFICIAL_SDK_NATIVE_WORKER_NOT_QUALIFIED")
            if value["backend"]=="openshell":
                service=getattr(self.server,"openshell_service",None)
                if service is None or not service.qualified:raise ValueError("UNAVAILABLE_SELECTION")
                if self.headers.get("X-DSH-Subject","")!=service.subject:raise ValueError("FOREIGN_SUBJECT")
            elif value["runtime"]=="sdk":
                sdk_service=getattr(self.server,"sdk_service",None)
                if sdk_service is None or sdk_service.qualified is not True:
                    return self.reply(503,{"error":"OFFICIAL_SDK_NOT_QUALIFIED"})
                if self.headers.get("X-DSH-Subject","")!=sdk_service.subject:
                    raise ValueError("FOREIGN_NATIVE_SDK_SUBJECT")
                if value.get("handoffRuntime"):
                    raise ValueError("NATIVE_SDK_HANDOFF_NOT_YET_QUALIFIED")
            if value.get("handoffRuntime") is not None:
                if value["handoffRuntime"]=="sdk":raise ValueError("NATIVE_SDK_HANDOFF_NOT_YET_QUALIFIED")
                if value["handoffRuntime"] not in RUNTIMES or value["handoffRuntime"]==value["runtime"]: raise ValueError("INVALID_HANDOFF_RUNTIME")
                if not isinstance(value.get("handoffPrompt",""),str) or len(value.get("handoffPrompt",""))>65536: raise ValueError("INVALID_HANDOFF_PROMPT")
            if value["approved"] is not True or not isinstance(value["writes"],bool): raise ValueError("APPROVAL_REQUIRED")
            if not isinstance(value["prompt"],str) or not 1<=len(value["prompt"])<=65536: raise ValueError("INVALID_PROMPT")
            confined_project(value["project"])
            task=REGISTRY.create(value,execution_service=service,sdk_service=sdk_service); return self.reply(202,{"taskId":task.id,"state":task.state,"correlationId":task.correlation_id})
        except (ValueError, json.JSONDecodeError) as error: return self.reply(400,{"error":str(error)})
        except RuntimeError as error: return self.reply(409,{"error":str(error)})
    def do_DELETE(self):
        if not self.authorized(): return self.reply(401,{"error":"UNAUTHORIZED"})
        match=re.fullmatch(r"/v1/tasks/([a-f0-9]{32})",urlparse(self.path).path)
        if not match: return self.reply(404,{"error":"NOT_FOUND"})
        task=REGISTRY.get(match.group(1))
        if not task: return self.reply(404,{"error":"TASK_NOT_FOUND"})
        if task.native_sdk and self.headers.get("X-DSH-Subject","")!=task.native_sdk["subject"]:
            return self.reply(403,{"error":"FOREIGN_NATIVE_SDK_SUBJECT"})
        return self.reply(202 if task.cancel() else 409,{"taskId":task.id,"state":task.state})


if __name__ == "__main__":
    os.umask(0o077)
    from scripts.openshell_bootstrap import configure
    server=ThreadingHTTPServer((HOST, PORT), Handler)
    configure(server,REGISTRY,os.environ.get('DSH_OPENSHELL_ADMISSION_FILE'))
    from scripts.official_sdk_bootstrap import configure as configure_official_sdk
    configure_official_sdk(server, REGISTRY, os.environ.get('DSH_OFFICIAL_SDK_ADMISSION_FILE'),
        qualification_allowed=os.environ.get('DSH_NATIVE_QUALIFICATION_MODE') == '1',
        workspace_root=WORKSPACE)
    server.serve_forever()
