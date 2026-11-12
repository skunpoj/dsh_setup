#!/opt/dsh/deepagents/bin/python -I -S
"""Private scoped child only. No SDK code executes inside the broker.

The protected supervisor must supply isolated pipes, no broker credential mounts,
an allowlisted environment and exact descendant fencing. This file is NOT a
standalone local-process fallback or a qualification of that supervisor.
"""
import base64
import json
import os
from pathlib import Path
import sys
import threading


class Controller:
    def __init__(self, harness, codec, send, *, capture_visible=False):
        self.harness, self.codec, self.send = harness, codec, send
        self.capture_visible=capture_visible
        self.pending = set(); self.calls = set()
        self.lock = threading.Lock(); self.write_lock = threading.Lock()
        self.started = False; self.running = False
        self.closed = threading.Event()

    def emit(self, payload):
        with self.write_lock: self.send(self.codec.encode(payload))

    def approvals(self):
        try:
            while not self.closed.is_set():
                request = self.harness.client.next_request()
                if request.method != "approval/request": raise ValueError("UNSUPPORTED_NATIVE_REQUEST")
                with self.lock:
                    if request.id in self.pending: raise ValueError("DUPLICATE_NATIVE_REQUEST")
                    self.pending.add(request.id)
                self.emit({"kind": "request", "id": request.id,
                    "method": request.method, "payload": request.payload})
        except Exception:
            self.closed.set()
            # Close the private output to wake the parent; scope must prove
            # process/descendant termination, not infer it from this EOF.
            self.emit({"kind": "fault"})

    def captured_run(self,prompt,session):
        from scripts.banking_private_capture import visible_notification
        subscription=self.harness.client.subscribe_session_notifications(session)
        done=threading.Event();faults=[]
        def forward(event):
            if event.payload.get('sessionId')!=session:raise ValueError('FOREIGN_VISIBLE_CAPTURE_SESSION')
            value=visible_notification(event.method,event.payload)
            if value is not None:
                payload={'sessionId':session,'event':{'seq':value['sequence'],'type':value['type'],'data':value['data']}}
                self.emit(dict(kind='notification',method=event.method,payload=payload))
        def pump():
            try:
                while not done.is_set():
                    try:event=subscription.next(timeout_seconds=.1)
                    except TimeoutError:continue
                    forward(event)
                subscription.drain(forward)
            except BaseException as error:faults.append(type(error).__name__)
        reader=threading.Thread(target=pump,daemon=True);reader.start()
        try:result=self.harness.run(prompt,session_id=session)
        finally:
            done.set();reader.join(timeout=2);subscription.close()
        if reader.is_alive() or faults:raise ValueError('SDK_VISIBLE_NOTIFICATION_DRAIN_FAILED')
        # Native SDK wait response follows all session notifications. Joining
        # and draining its subscription orders this barrier before run reply.
        self.emit(dict(kind='notification',method='banking.capture.complete',payload={'sessionId':session,'complete':True}))
        return result

    def dispatch(self, frame):
        if (not isinstance(frame, dict) or set(frame) != {"kind", "id", "method", "params"}
                or frame["kind"] != "call" or not isinstance(frame["id"], str)
                or not isinstance(frame["params"], dict)):
            raise ValueError("INVALID_SDK_CONTROL_CALL")
        operation = frame["id"]
        with self.lock:
            if operation in self.calls: raise ValueError("SDK_CONTROL_CALL_REPLAY")
            self.calls.add(operation)
        method, params = frame["method"], frame["params"]
        def respond(value=None, ok=True):
            self.emit({"kind": "response", "id": operation, "ok": ok, "result": value})
        if method == "start":
            if self.started or params: raise ValueError("SDK_CONTROL_START_REPLAY")
            self.started = True
            self.harness.start()
            threading.Thread(target=self.approvals, daemon=True).start()
            respond()
        elif method == "run":
            if not self.started or self.running or set(params) != {"prompt", "sessionId"}:
                raise ValueError("SDK_CONTROL_RUN_REFUSED")
            if (params["sessionId"] != self.codec.binding["sessionId"]
                    or not isinstance(params["prompt"], str) or not 1 <= len(params["prompt"]) <= 65536):
                raise ValueError("FOREIGN_SDK_CONTROL_RUN")
            self.running = True  # One run per child; no replay or retry.
            def run():
                try:
                    result = self.captured_run(params['prompt'],params['sessionId']) if self.capture_visible else self.harness.run(params["prompt"], session_id=params["sessionId"])
                    respond({"finishReason": result.finish_reason, "finalResponse": result.final_response})
                except Exception: respond(ok=False)
            threading.Thread(target=run, daemon=True).start()
        elif method == "respond":
            if set(params) != {"requestId", "result"}: raise ValueError("INVALID_NATIVE_RESPONSE")
            with self.lock:
                if params["requestId"] not in self.pending: raise ValueError("UNKNOWN_NATIVE_RESPONSE")
                self.pending.remove(params["requestId"])
            self.harness.client.respond(params["requestId"], params["result"])
            respond()
        else:
            raise ValueError("UNSUPPORTED_SDK_CONTROL_CALL")


def main():
    if sys.platform != "linux": raise ValueError("ISOLATED_LINUX_SDK_CHILD_REQUIRED")
    # -I -S prevents caller PYTHONPATH, sitecustomize and executable .pth files.
    import stat
    for directory in (Path("/opt/dsh"), Path("/opt/dsh/scripts")):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("UNPROTECTED_SDK_CONTROL_SOURCE")
    sys.path.insert(0, "/opt/dsh")
    from scripts.official_sdk_package_admission import verify_sdk_admission, install_verified_sdk_imports, unique_json
    from scripts.official_sdk_control_peer import SDKFrameCodec, MAX_FRAME
    from scripts.official_sdk_task import guarded_endpoint
    bootstrap = unique_json(sys.stdin.buffer.readline(MAX_FRAME + 1))
    if not isinstance(bootstrap, dict) or set(bootstrap) != {"key", "binding", "options"}:
        raise ValueError("INVALID_SDK_CONTROL_BOOTSTRAP")
    codec = SDKFrameCodec(base64.b64decode(bootstrap["key"], validate=True), bootstrap["binding"])
    options = bootstrap["options"]
    if not isinstance(options, dict): raise ValueError("INVALID_SDK_OPTIONS")
    env = options.get("env", {})
    endpoint = guarded_endpoint(options.get("base_url", ""))
    if (options.get("api_key") != "local-guard-placeholder" or options.get("approval_requests") is not True
            or options.get("dsh_bin") != "/usr/local/bin/dsh-official-sdk-runtime"
            or env.get("DSH_UNATTENDED_TASK") != codec.binding["taskId"]
            or env.get("DSH_CORRELATION_ID") != codec.binding["correlationId"]
            or env.get("DSH_GUARDED_MODEL_BASE_URL") != endpoint):
        raise ValueError("SDK_CHILD_BINDING_MISMATCH")
    allowed = {k: env[k] for k in ("PATH", "LANG", "HOME", "PYTHONDONTWRITEBYTECODE",
        "OTEL_SDK_DISABLED", "DO_NOT_TRACK", "LANGSMITH_TRACING", "DSH_UNATTENDED_TASK",
        "DSH_CORRELATION_ID", "DSH_GUARDED_MODEL_BASE_URL")}
    if options.get('max_tokens')==8192:
        if env.get('TMPDIR')!='/tmp/user':raise ValueError('FIXED_BANKING_TEMP_ROOT_REQUIRED')
        allowed['TMPDIR']='/tmp/user'
    os.environ.clear(); os.environ.update(allowed); options["env"] = allowed
    admitted = verify_sdk_admission()
    if admitted["admissionSha256"] != codec.binding.get("packageAdmissionSha256"):
        raise ValueError("SDK_CHILD_PACKAGE_ADMISSION_CHANGED")
    install_verified_sdk_imports(admitted)
    # Same interpreter's protected site directory; never execute its .pth files.
    sys.path.append(admitted["installedRoot"])
    from deepseek_harness import DeepSeekHarness  # Only in isolated, content-admitted child.
    harness = DeepSeekHarness(**options)
    def send(raw):
        sys.stdout.write(raw + "\n"); sys.stdout.flush()
    controller = Controller(harness, codec, send,capture_visible=options.get("max_tokens")==8192)
    try:
        while not controller.closed.is_set():
            line = sys.stdin.buffer.readline(MAX_FRAME + 1)
            if not line: break
            controller.dispatch(codec.decode(line.decode("utf-8")))
    finally:
        controller.closed.set(); harness.close()


if __name__ == "__main__":
    try: main()
    except Exception:
        print("Official SDK isolated control refused", file=sys.stderr)
        raise SystemExit(70)
