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
    temp.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def confined_project(value):
    if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
        raise ValueError("INVALID_PROJECT")
    candidate = (WORKSPACE / value).resolve()
    if candidate != WORKSPACE and WORKSPACE not in candidate.parents:
        raise ValueError("INVALID_PROJECT")
    if not candidate.is_dir():
        raise ValueError("PROJECT_NOT_FOUND")
    return candidate


def command_for(runtime, prompt, writes, project, task_id, resume=False):
    if runtime == "sdk":
        control = ["/usr/local/bin/dsh-unattended", "sdk", "--task-id", task_id,
                   "--max-model-starts", "1", "--cwd", str(project)]
        if resume: control.append("--resume")
        return [*control, "--", "--resume"] if resume else [*control, "--", "--prompt", prompt]
    if runtime == "deepagents":
        return ["/usr/local/bin/dsh-unattended", "deepagents", "--task-id", task_id,
                "--max-model-starts", "1", "--cwd", str(project), "--", "-n", prompt]
    if runtime == "kilo":
        return ["/usr/local/bin/dsh-unattended", "kilo", "--task-id", task_id,
                "--max-model-starts", "1", "--cwd", str(project), "--", "--pure", "run", prompt]
    mode = "acceptEdits" if writes else "plan"
    return ["/usr/local/bin/dsh-unattended", "claude", "--task-id", task_id,
            "--max-model-starts", "1", "--cwd", str(project), "--", "-p", prompt,
            "--output-format", "stream-json", "--verbose", "--permission-mode", mode]


class Task:
    def __init__(self, task_id, request):
        self.id = task_id
        self.correlation_id = uuid.uuid4().hex
        self.request = request
        self.directory = ROOT / task_id
        self.events = self.directory / "events.jsonl"
        self.process = None
        self.lock = threading.Lock()
        self.sequence = 0
        self.state = "queued"
        self.created = time.time()
        self.emit("queued", {"runtime": request["runtime"], "project": request["project"]})
        self.save()

    @classmethod
    def recover(cls, value, directory):
        task=cls.__new__(cls);task.id=value["id"];task.request={"runtime":value["runtime"],"project":value["project"],"writes":value.get("writes",False),"handoffRuntime":value.get("handoffRuntime")}
        task.correlation_id=value.get("correlationId", value["id"])
        task.directory=directory;task.events=directory/"events.jsonl";task.process=None;task.lock=threading.Lock()
        task.sequence=int(value.get("sequence",0));task.state=value["state"];task.created=float(value.get("created",time.time()));return task

    def save(self):
        atomic_json(self.directory / "task.json", {
            "id": self.id, "runtime": self.request["runtime"], "project": self.request["project"],
            "correlationId": self.correlation_id,
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
                code=self.process.wait();self.state="completed" if code==0 else "failed"
                self.emit("state",{"state":self.state,"exitCode":code,"runtime":handoff_runtime})
        except Exception as error:
            self.state = "failed"; self.emit("state", {"state": self.state, "error": type(error).__name__})
        finally:
            self.process = None; self.save()

    def cancel(self):
        if self.state not in {"queued", "running", "handoff", "awaiting_approval"}: return False
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
        if self.state != "awaiting_approval" or self.request["runtime"] != "sdk": return False
        self.state = "queued"; self.emit("state", {"state": self.state, "resuming": True}); self.save()
        threading.Thread(target=self.run, kwargs={"resume": True}, daemon=True).start(); return True


class Registry:
    def __init__(self):
        self.tasks = {}; self.lock = threading.Lock(); ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        for file in ROOT.glob("*/task.json"):
            try:
                value = json.loads(file.read_text(encoding="utf-8"))
                if value.get("state") in {"queued", "running", "cancelling"}:
                    value["state"] = "interrupted"; atomic_json(file, value)
                if TASK_ID.fullmatch(value.get("id","")) and value.get("state") in {"completed","failed","cancelled","interrupted","awaiting_approval"}:
                    self.tasks[value["id"]]=Task.recover(value,file.parent)
            except Exception: pass

    def create(self, request):
        with self.lock:
            if any(t.state in {"queued", "running", "cancelling", "awaiting_approval"} for t in self.tasks.values()):
                raise RuntimeError("TASK_ALREADY_ACTIVE")
            task = Task(uuid.uuid4().hex, request); self.tasks[task.id] = task
            threading.Thread(target=task.run, daemon=True).start(); return task

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
        if path == "/v1/capabilities": return self.reply(200, {"runtimes":sorted(RUNTIMES),"backends":[{"id":"private","enabled":True},{"id":"openshell","enabled":False,"reason":"OpenShell requires 25-gate Test and rollback qualification"}]})
        match = re.fullmatch(r"/v1/tasks/([a-f0-9]{32})/events", path)
        if match:
            task = REGISTRY.get(match.group(1))
            if not task: return self.reply(404, {"error":"TASK_NOT_FOUND"})
            try: after = max(0, int(dict(x.split("=",1) for x in urlparse(self.path).query.split("&") if "=" in x).get("after","0")))
            except ValueError: return self.reply(400, {"error":"INVALID_CURSOR"})
            rows=[]
            if task.events.exists():
                for line in task.events.read_text(encoding="utf-8").splitlines():
                    row=json.loads(line)
                    if row["sequence"] > after: rows.append(row)
            return self.reply(200, {"taskId":task.id,"state":task.state,"events":rows[-200:],"next":task.sequence})
        return self.reply(404, {"error":"NOT_FOUND"})
    def do_POST(self):
        if not self.authorized(): return self.reply(401, {"error":"UNAUTHORIZED"})
        path=urlparse(self.path).path
        approval=re.fullmatch(r"/v1/tasks/([a-f0-9]{32})/approve",path)
        if approval:
            try:
                value=self.body()
                if value != {"approved": True}: raise ValueError("APPROVAL_REQUIRED")
            except (ValueError,json.JSONDecodeError) as error:return self.reply(400,{"error":str(error)})
            task=REGISTRY.get(approval.group(1))
            if not task:return self.reply(404,{"error":"TASK_NOT_FOUND"})
            return self.reply(202 if task.approve() else 409,{"taskId":task.id,"state":task.state})
        if path != "/v1/tasks": return self.reply(404,{"error":"NOT_FOUND"})
        try:
            value=self.body()
            required={"runtime","backend","project","prompt","writes","approved"};optional={"handoffRuntime","handoffPrompt"}
            if not isinstance(value,dict) or not required.issubset(value) or not set(value).issubset(required|optional): raise ValueError("INVALID_REQUEST")
            if value["runtime"] not in RUNTIMES or value["backend"]!="private": raise ValueError("UNAVAILABLE_SELECTION")
            if value.get("handoffRuntime") is not None:
                if value["handoffRuntime"] not in RUNTIMES or value["handoffRuntime"]==value["runtime"]: raise ValueError("INVALID_HANDOFF_RUNTIME")
                if not isinstance(value.get("handoffPrompt",""),str) or len(value.get("handoffPrompt",""))>65536: raise ValueError("INVALID_HANDOFF_PROMPT")
            if value["approved"] is not True or not isinstance(value["writes"],bool): raise ValueError("APPROVAL_REQUIRED")
            if not isinstance(value["prompt"],str) or not 1<=len(value["prompt"])<=65536: raise ValueError("INVALID_PROMPT")
            confined_project(value["project"])
            task=REGISTRY.create(value); return self.reply(202,{"taskId":task.id,"state":task.state,"correlationId":task.correlation_id})
        except (ValueError, json.JSONDecodeError) as error: return self.reply(400,{"error":str(error)})
        except RuntimeError as error: return self.reply(409,{"error":str(error)})
    def do_DELETE(self):
        if not self.authorized(): return self.reply(401,{"error":"UNAUTHORIZED"})
        match=re.fullmatch(r"/v1/tasks/([a-f0-9]{32})",urlparse(self.path).path)
        if not match: return self.reply(404,{"error":"NOT_FOUND"})
        task=REGISTRY.get(match.group(1))
        if not task: return self.reply(404,{"error":"TASK_NOT_FOUND"})
        return self.reply(202 if task.cancel() else 409,{"taskId":task.id,"state":task.state})


if __name__ == "__main__":
    os.umask(0o077)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
