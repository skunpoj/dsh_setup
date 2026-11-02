#!/usr/bin/env python3
"""Fail-closed model transport for one unattended DSH task.

The guard binds only to loopback, admits a finite number of distinct requests,
never retries upstream, and records reservation/completion without request or
response content. A reservation survives a crash so an uncertain request is
never replayed automatically.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit
try:
    from .dsh_correlation import operation_correlation_id, validate_correlation_id
except ImportError:  # Installed scripts directory is also a supported top-level import path.
    from dsh_correlation import operation_correlation_id, validate_correlation_id

if os.name == "nt":
    import msvcrt
else:
    import fcntl

ALLOWED_PATHS = frozenset({"/v1/chat/completions", "/v1/messages", "/v1/responses"})
HOP_HEADERS = frozenset({"api-key", "authorization", "connection", "content-length", "host",
                         "transfer-encoding", "x-api-key", "x-litellm-api-key",
                         "x-dsh-correlation-id"})
MAX_BODY = 8 * 1024 * 1024
APPROVED_UPSTREAM = "http://litellm.llm.svc.cluster.local:4000"
CORRELATION_HEADER = "x-dsh-correlation-id"


def sanitize_internal_request(path: str, body: bytes, operation_id: str | None = None) -> bytes:
    """Remove provider-only extensions that the internal route cannot accept."""
    if path not in ALLOWED_PATHS:
        raise ValueError("model path is not allowed")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    cleaned = {key: item for key, item in value.items()
               if not (isinstance(key, str) and key.startswith("dsh_"))}
    cleaned.pop("chat_template_kwargs", None)
    supplied_metadata = cleaned.get("metadata")
    if isinstance(supplied_metadata, dict) and "dsh_correlation_id" in supplied_metadata:
        raise ValueError("client-supplied DSH correlation is forbidden")
    if operation_id is not None:
        operation_id = validate_correlation_id(operation_id)
        metadata = cleaned.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise ValueError("request metadata must be a JSON object")
        metadata = dict(metadata)
        metadata["dsh_correlation_id"] = operation_id
        cleaned["metadata"] = metadata
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode()


def canonical_fingerprint(path: str, body: bytes) -> str:
    if path not in ALLOWED_PATHS:
        raise ValueError("model path is not allowed")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be JSON") from exc
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(path.encode() + b"\0" + canonical).hexdigest()


class AdmissionLedger:
    def __init__(self, path: Path, task_id: str, maximum: int, *, task_correlation_id: str):
        if not task_id or len(task_id) > 200 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in task_id):
            raise ValueError("safe bounded task id required")
        if not 1 <= maximum <= 32:
            raise ValueError("model-start cap must be 1..32")
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")
        self.task_id = task_id
        self.task_correlation_id = validate_correlation_id(task_correlation_id)
        self.maximum = maximum
        self.thread_lock = threading.Lock()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    @contextlib.contextmanager
    def _locked(self):
        with self.thread_lock:
            with self.lock_path.open("a+b") as lock:
                if os.name == "nt":
                    if lock.seek(0, os.SEEK_END) == 0:
                        lock.write(b"0"); lock.flush()
                    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == "nt":
                        lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _append(self, stream, entry):
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(entry, sort_keys=True) + "\n")
        stream.flush(); os.fsync(stream.fileno())

    def reserve(self, path: str, body: bytes):
        mark = canonical_fingerprint(path, body)
        with self._locked():
            with self.path.open("a+", encoding="utf-8") as stream:
                stream.seek(0)
                rows = [json.loads(line) for line in stream if line.strip()]
                starts = [r for r in rows if r.get("task_id") == self.task_id and r.get("event") == "upstream-start-reserved"]
                if any(r.get("fingerprint") == mark for r in starts):
                    prior = next(r for r in starts if r.get("fingerprint") == mark)
                    return False, "duplicate-or-uncertain", prior["sequence"], mark, prior["operation_correlation_id"]
                if len(starts) >= self.maximum:
                    return False, "task-cap", len(starts), mark, ""
                sequence = len(starts) + 1
                operation_id = operation_correlation_id(self.task_correlation_id, sequence, mark)
                self._append(stream, {"event": "upstream-start-reserved", "task_id": self.task_id,
                                      "task_correlation_id": self.task_correlation_id,
                                      "operation_correlation_id": operation_id,
                                      "sequence": sequence, "path": path, "fingerprint": mark,
                                      "utc": datetime.now(timezone.utc).isoformat()})
                return True, "reserved", sequence, mark, operation_id

    def complete(self, sequence: int, mark: str, operation_id: str, status: int, outcome: str):
        with self._locked():
            with self.path.open("a+", encoding="utf-8") as stream:
                self._append(stream, {"event": "upstream-finished", "task_id": self.task_id,
                                      "task_correlation_id": self.task_correlation_id,
                                      "operation_correlation_id": validate_correlation_id(operation_id),
                                      "sequence": sequence, "fingerprint": mark,
                                      "status": int(status), "outcome": outcome,
                                      "utc": datetime.now(timezone.utc).isoformat()})


class GuardedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, upstream: str, token_file: Path, ledger: AdmissionLedger, *, allow_test_upstream=False):
        parsed = urlsplit(upstream)
        if parsed.scheme != "http" or parsed.path not in ("", "/") or parsed.username or parsed.password:
            raise ValueError("plain approved in-cluster HTTP origin required")
        if not allow_test_upstream and upstream.rstrip("/") != APPROVED_UPSTREAM:
            raise ValueError("unexpected upstream")
        self.upstream = parsed
        self.token_file = token_file
        self.ledger = ledger
        super().__init__(address, GuardedHandler)


class GuardedHandler(BaseHTTPRequestHandler):
    server: GuardedServer

    def log_message(self, *_):
        return

    def _reject(self, reason: str, status=422):
        data = json.dumps({"error": {"type": "dsh_admission_refused", "reason": reason, "retryable": False}}).encode()
        try:
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.send_header("x-should-retry", "false")
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", "-1"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self._reject("invalid-body-size", 413)
        body = self.rfile.read(length)
        try:
            token = self.server.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            return self._reject("credential-unavailable", 503)
        try:
            body = sanitize_internal_request(self.path, body)
            accepted, reason, sequence, mark, operation_id = self.server.ledger.reserve(self.path, body)
        except ValueError:
            return self._reject("invalid-request", 400)
        if not accepted:
            return self._reject(reason)

        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        headers["authorization"] = "Bearer " + token
        headers[CORRELATION_HEADER] = operation_id
        body = sanitize_internal_request(self.path, body, operation_id)
        headers["content-length"] = str(len(body))
        connection = http.client.HTTPConnection(self.server.upstream.hostname, self.server.upstream.port, timeout=3600)
        status = 502
        outcome = "transport-failed"
        response_started = False
        try:
            connection.request("POST", self.path, body=body, headers=headers)
            response = connection.getresponse(); status = response.status
            self.send_response(status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.end_headers()
            response_started = True
            while chunk := response.read(64 * 1024):
                self.wfile.write(chunk); self.wfile.flush()
            outcome = "response-complete"
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            outcome = "caller-cancelled-or-disconnected"
        except Exception:
            outcome = "transport-failed"
            if not response_started and not self.wfile.closed:
                try: self._reject("upstream-transport-failed", 502)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError): pass
        finally:
            connection.close()
            self.server.ledger.complete(sequence, mark, operation_id, status, outcome)


@contextlib.contextmanager
def running_guard(upstream: str, token_file: Path, ledger: AdmissionLedger, *, allow_test_upstream=False):
    server = GuardedServer(("127.0.0.1", 0), upstream, token_file, ledger, allow_test_upstream=allow_test_upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
