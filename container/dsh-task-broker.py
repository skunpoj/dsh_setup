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
RUNTIMES = {"sdk", "claude", "deepagents"}
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


def command_for(runtime, prompt, writes, project):
    if runtime == "sdk":
        return ["/usr/local/bin/dsh-unattended", "sdk", "--cwd", str(project), "--", prompt]
    if runtime == "deepagents":
        return ["/usr/local/bin/dsh-unattended", "deepagents", "--cwd", str(project), "--", "-n", prompt]
    mode = "acceptEdits" if writes else "plan"
    return ["/usr/local/bin/dsh-unattended", "claude", "--cwd", str(project), "--", "-p", prompt,
            "--output-format", "stream-json", "--verbose", "--permission-mode", mode]


class Task:
    def __init__(self, task_id, request):
        self.id = task_id
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
        task=cls.__new__(cls);task.id=value["id"];task.request={"runtime":value["runtime"],"project":value["project"],"writes":value.get("writes",False)}
        task.directory=directory;task.events=directory/"events.jsonl";task.process=None;task.lock=threading.Lock()
        task.sequence=int(value.get("sequence",0));task.state=value["state"];task.created=float(value.get("created",time.time()));return task

    def save(self):
        atomic_json(self.directory / "task.json", {
            "id": self.id, "runtime": self.request["runtime"], "project": self.request["project"],
            "writes": self.request["writes"], "state": self.state, "created": self.created,
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

    def run(self):
        self.state = "running"; self.emit("state", {"state": self.state}); self.save()
        project = confined_project(self.request["project"])
        command = command_for(self.request["runtime"], self.request["prompt"], self.request["writes"], project)
        env = dict(os.environ)
        env["DSH_UNATTENDED_TASK"] = self.id
        try:
            self.process = subprocess.Popen(command, cwd=project, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                start_new_session=True, bufsize=1)
            for line in self.process.stdout:
                self.emit("output", {"text": line[:16384]})
            code = self.process.wait()
            self.state = "cancelled" if self.state in {"cancelling","cancelled"} else ("completed" if code == 0 else "failed")
            self.emit("state", {"state": self.state, "exitCode": code})
        except Exception as error:
            self.state = "failed"; self.emit("state", {"state": self.state, "error": type(error).__name__})
        finally:
            self.process = None; self.save()

    def cancel(self):
        if self.state not in {"queued", "running"}: return False
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


class Registry:
    def __init__(self):
        self.tasks = {}; self.lock = threading.Lock(); ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        for file in ROOT.glob("*/task.json"):
            try:
                value = json.loads(file.read_text(encoding="utf-8"))
                if value.get("state") in {"queued", "running", "cancelling"}:
                    value["state"] = "interrupted"; atomic_json(file, value)
                if TASK_ID.fullmatch(value.get("id","")) and value.get("state") in {"completed","failed","cancelled","interrupted"}:
                    self.tasks[value["id"]]=Task.recover(value,file.parent)
            except Exception: pass

    def create(self, request):
        with self.lock:
            if any(t.state in {"queued", "running", "cancelling"} for t in self.tasks.values()):
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
        if urlparse(self.path).path != "/v1/tasks": return self.reply(404,{"error":"NOT_FOUND"})
        try:
            value=self.body()
            if not isinstance(value,dict) or set(value)!={"runtime","backend","project","prompt","writes","approved"}: raise ValueError("INVALID_REQUEST")
            if value["runtime"] not in RUNTIMES or value["backend"]!="private": raise ValueError("UNAVAILABLE_SELECTION")
            if value["approved"] is not True or not isinstance(value["writes"],bool): raise ValueError("APPROVAL_REQUIRED")
            if not isinstance(value["prompt"],str) or not 1<=len(value["prompt"])<=65536: raise ValueError("INVALID_PROMPT")
            confined_project(value["project"])
            task=REGISTRY.create(value); return self.reply(202,{"taskId":task.id,"state":task.state})
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
