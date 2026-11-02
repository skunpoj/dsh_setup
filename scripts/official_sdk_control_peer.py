"""Broker-side authenticated pipe proxy. Only stdlib/core; NO SDK imports."""
import base64
import hashlib
import hmac
import json
import queue
import secrets
import threading
import uuid
from types import SimpleNamespace

COMMAND = ("/opt/dsh/deepagents/bin/python", "-I", "-S", "/opt/dsh/container/dsh-sdk-control.py")
MAX_FRAME = 1024 * 1024


class SDKFrameCodec:
    def __init__(self, key, binding):
        if not isinstance(key, bytes) or len(key) != 32: raise ValueError("INVALID_SDK_IPC_KEY")
        self.key, self.binding = key, dict(binding)
        self.sent = self.received = 0
        self.write_lock = threading.Lock()
    def encode(self, payload):
        with self.write_lock:
            self.sent += 1
            frame = {"v": 1, "seq": self.sent, "binding": self.binding, "payload": payload}
            raw = json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()
            frame["mac"] = hmac.new(self.key, raw, hashlib.sha256).hexdigest()
            result = json.dumps(frame, separators=(",", ":"))
            if len(result.encode()) > MAX_FRAME: raise ValueError("SDK_IPC_FRAME_TOO_LARGE")
            return result
    def decode(self, raw):
        if len(raw.encode()) > MAX_FRAME: raise ValueError("SDK_IPC_FRAME_TOO_LARGE")
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value: raise ValueError("DUPLICATE_SDK_IPC_FIELD")
                value[key] = item
            return value
        frame = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(frame, dict) or set(frame) != {"v", "seq", "binding", "payload", "mac"}:
            raise ValueError("INVALID_SDK_IPC_FRAME")
        mac = frame.pop("mac")
        encoded = json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()
        expected = hmac.new(self.key, encoded, hashlib.sha256).hexdigest()
        if (not isinstance(mac, str) or not hmac.compare_digest(mac, expected)
                or type(frame["v"]) is not int or frame["v"] != 1
                or type(frame["seq"]) is not int or frame["seq"] != self.received + 1
                or frame["binding"] != self.binding):
            raise ValueError("FOREIGN_REPLAYED_OR_UNAUTHENTICATED_SDK_IPC")
        self.received = frame["seq"]
        return frame["payload"]


class _Subscription:
    def __init__(self): self.queue = queue.Queue()
    def next(self):
        value = self.queue.get()
        if value is None: raise RuntimeError("SDK_CONTROL_CLOSED")
        return value
    def close(self): self.queue.put(None)


class SDKControlPeer:
    def __init__(self, *, runtime_scope, binding, options):
        factory = getattr(runtime_scope, "control_transport", None)
        if not callable(factory): raise ValueError("ISOLATED_SDK_CONTROL_TRANSPORT_REQUIRED")
        self.binding, self.options = dict(binding), dict(options)
        self.key = secrets.token_bytes(32)  # Ephemeral pipe capability; never logged/persisted/env/argv.
        self.codec = SDKFrameCodec(self.key, self.binding)
        # Creation must be inert. The protected scope starts this isolated
        # child only after the Task's durable launch reservation.
        self.transport = factory(binding=dict(binding), command=COMMAND)
        self.client = self
        self.pending = {}; self.requests = queue.Queue(); self.subscriptions = []
        self.lock = threading.Lock(); self.send_lock = threading.Lock()
        self.closed = threading.Event(); self.started = False

    def start(self):
        with self.lock:
            if self.started: raise ValueError("SDK_CONTROL_START_REPLAY")
            self.started = True
        # The scope must use private stdin/stdout pipes in an admitted worker
        # with no broker credential mounts. No default broker Popen is allowed.
        bootstrap = {"key": base64.b64encode(self.key).decode(), "binding": self.binding,
                     "options": self.options}
        self.transport.start(bootstrap)
        self.reader = threading.Thread(target=self._read, daemon=True); self.reader.start()
        self._rpc("start", {})

    def _read(self):
        try:
            while not self.closed.is_set():
                payload = self.codec.decode(self.transport.receive())
                if not isinstance(payload, dict): raise ValueError("INVALID_SDK_CONTROL_PAYLOAD")
                if payload.get("kind") == "response":
                    with self.lock: target = self.pending.get(payload.get("id"))
                    if target is None: raise ValueError("UNKNOWN_SDK_CONTROL_RESPONSE")
                    target.put(payload)
                elif payload.get("kind") == "request":
                    self.requests.put(SimpleNamespace(id=payload["id"], method=payload["method"], payload=payload["payload"]))
                elif payload.get("kind") == "notification":
                    notification = SimpleNamespace(method=payload["method"], payload=payload["payload"])
                    for subscription in self.subscriptions: subscription.queue.put(notification)
                else: raise ValueError("UNSUPPORTED_SDK_CONTROL_PAYLOAD")
        except BaseException:
            self._closed()

    def _closed(self):
        self.closed.set(); self.requests.put(None)
        for subscription in self.subscriptions: subscription.close()
        with self.lock:
            for target in self.pending.values(): target.put({"ok": False})

    def _rpc(self, method, params, timeout=120):
        if self.closed.is_set(): raise RuntimeError("SDK_CONTROL_CLOSED")
        operation = uuid.uuid4().hex; target = queue.Queue()
        with self.lock: self.pending[operation] = target
        try:
            with self.send_lock:
                self.transport.send(self.codec.encode({"kind": "call", "id": operation,
                    "method": method, "params": params}))
            response = target.get(timeout=timeout)
            if response.get("ok") is not True: raise RuntimeError("SDK_CONTROL_OPERATION_FAILED")
            return response.get("result")
        finally:
            with self.lock: self.pending.pop(operation, None)

    def run(self, prompt, *, session_id):
        value = self._rpc("run", {"prompt": prompt, "sessionId": session_id})
        if not isinstance(value, dict): raise ValueError("INVALID_SDK_CONTROL_RESULT")
        return SimpleNamespace(finish_reason=value.get("finishReason"), final_response=value.get("finalResponse"))
    def next_request(self):
        value = self.requests.get()
        if value is None: raise RuntimeError("SDK_CONTROL_CLOSED")
        return value
    def respond(self, request_id, result):
        self._rpc("respond", {"requestId": request_id, "result": result})
    def subscribe_session_notifications(self, session):
        if session != self.binding["sessionId"]: raise ValueError("FOREIGN_SDK_SUBSCRIPTION")
        value = _Subscription(); self.subscriptions.append(value); return value
    def close(self):
        # Protected scope owns exact process/descendant stop; pipe close alone
        # never produces a processExitVerified receipt.
        self.transport.close(); self._closed()
