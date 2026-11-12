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
import uuid
import re
import socket
import time
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
                         "x-dsh-correlation-id", "x-dsh-task-id", "x-dsh-task-correlation-id"})
MAX_BODY = 8 * 1024 * 1024
APPROVED_UPSTREAM = "http://litellm-gateway.llm.svc.cluster.local:4000"
CORRELATION_HEADER = "x-dsh-correlation-id"
SERVER_IDENTITY_REQUEST_HEADERS = frozenset({"x-litellm-call-id"})


def canonical_model_path(value):
    if value in ALLOWED_PATHS:return value
    # Claude Code's Anthropic beta client emits this exact query flag. Accept
    # only that known form; arbitrary routing/auth queries remain forbidden.
    if value=='/v1/messages?beta=true':return '/v1/messages'
    raise ValueError('model path is not allowed')


def validate_proxy_origin(value):
    """The one plain-HTTP origin a proxying client may name in absolute-form requests.

    This is the pin the managed client policy already imposes. It is only a NAME the
    client sends; the guard still forwards to the single approved upstream.
    """
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid proxy origin") from exc
    if (parsed.scheme != "http" or not parsed.hostname or port is None or parsed.username
            or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("invalid proxy origin")
    return parsed.hostname.lower(), port


def proxy_request_target(raw, proxy_origin):
    """Origin-form target of an absolute-form proxy request for exactly proxy_origin.

    Origin-form targets (the normal reverse-proxy case) pass through unchanged. An
    absolute-form target is accepted only when a proxy origin is configured and the
    request names exactly that origin; anything else is refused, so the guard cannot
    be used as a general forward proxy.
    """
    if raw.startswith("/"):
        return raw
    if proxy_origin is None:
        raise ValueError("absolute-form target is not allowed")
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("absolute-form target is not allowed") from exc
    if (parsed.scheme != "http" or parsed.username or parsed.password or parsed.fragment
            or (parsed.hostname or "").lower() != proxy_origin[0] or port != proxy_origin[1]
            or not parsed.path.startswith("/")):
        raise ValueError("absolute-form target is not allowed")
    return parsed.path + ("?" + parsed.query if parsed.query else "")


def server_identity(response):
    """Retain only a typed, server-issued ID; never copy arbitrary headers."""
    value = response.getheader("x-litellm-call-id")
    if not isinstance(value, str) or len(value) not in {32, 36}:
        return {}
    try:
        uuid.UUID(value)
    except ValueError:
        return {}
    return {"litellm_call_id": value}


def sanitize_internal_request(path: str, body: bytes, operation_id: str | None = None,
                              *, task_id=None, task_correlation_id=None) -> bytes:
    """Remove provider-only extensions that the internal route cannot accept."""
    if path not in ALLOWED_PATHS:
        raise ValueError("model path is not allowed")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("request body must be JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    if "litellm_call_id" in value:
        raise ValueError("client-supplied LiteLLM call identity is forbidden")
    cleaned = {key: item for key, item in value.items()
               if not (isinstance(key, str) and key.startswith("dsh_"))}
    cleaned.pop("chat_template_kwargs", None)
    supplied_metadata = cleaned.get("metadata")
    if isinstance(supplied_metadata, dict) and any(
            key in supplied_metadata for key in ("dsh_correlation_id", "litellm_call_id",
                                                  'dsh_task_id','dsh_task_correlation_id')):
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
        if task_id is not None or task_correlation_id is not None:
            if not isinstance(task_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,200}',task_id):
                raise ValueError('server-owned task identity required')
            metadata['dsh_task_id']=task_id
            metadata['dsh_task_correlation_id']=validate_correlation_id(task_correlation_id)
        cleaned["metadata"] = metadata
    elif task_id is not None or task_correlation_id is not None:
        raise ValueError('reserved operation required before task metadata')
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
    def __init__(self, path: Path, task_id: str, maximum: int, *, task_correlation_id: str, banking_accounting_only=False):
        if not task_id or len(task_id) > 200 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in task_id):
            raise ValueError("safe bounded task id required")
        if not (maximum is None and banking_accounting_only is True) and (type(maximum) is not int or not 1 <= maximum <= 32):
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
                if any(r.get('task_id') == self.task_id and r.get('event') == 'task-fenced' for r in rows):
                    return False, 'task-fenced', 0, mark, ''
                starts = [r for r in rows if r.get("task_id") == self.task_id and r.get("event") == "upstream-start-reserved"]
                if any(r.get("fingerprint") == mark for r in starts):
                    prior = next(r for r in starts if r.get("fingerprint") == mark)
                    return False, "duplicate-or-uncertain", prior["sequence"], mark, prior["operation_correlation_id"]
                if self.maximum is not None and len(starts) >= self.maximum:
                    return False, "task-cap", len(starts), mark, ""
                sequence = len(starts) + 1
                operation_id = operation_correlation_id(self.task_correlation_id, sequence, mark)
                self._append(stream, {"event": "upstream-start-reserved", "task_id": self.task_id,
                                      "task_correlation_id": self.task_correlation_id,
                                      "operation_correlation_id": operation_id,
                                      "litellm_call_id": str(uuid.UUID(operation_id)),
                                      "sequence": sequence, "path": path, "fingerprint": mark,
                                      "utc": datetime.now(timezone.utc).isoformat()})
                return True, "reserved", sequence, mark, operation_id

    def fence(self, operation_id):
        operation_id = validate_correlation_id(operation_id)
        with self._locked():
            with self.path.open('a+', encoding='utf-8') as stream:
                stream.seek(0)
                rows = [json.loads(line) for line in stream if line.strip()]
                prior = [r for r in rows if r.get('task_id') == self.task_id and r.get('event') == 'task-fenced']
                if prior:
                    return False
                self._append(stream, {'event': 'task-fenced', 'task_id': self.task_id,
                    'task_correlation_id': self.task_correlation_id, 'operation_id': operation_id,
                    'utc': datetime.now(timezone.utc).isoformat()})
                return True

    def complete(self, sequence: int, mark: str, operation_id: str, status: int, outcome: str,
                 upstream_identity=None):
        with self._locked():
            with self.path.open("a+", encoding="utf-8") as stream:
                self._append(stream, {"event": "upstream-finished", "task_id": self.task_id,
                                      "task_correlation_id": self.task_correlation_id,
                                      "operation_correlation_id": validate_correlation_id(operation_id),
                                      "sequence": sequence, "fingerprint": mark,
                                      "status": int(status), "outcome": outcome,
                                      "upstream_identity": upstream_identity or {},
                                      "upstream_identity_confirmed": (upstream_identity or {}).get("litellm_call_id") == str(uuid.UUID(operation_id)),
                                      "utc": datetime.now(timezone.utc).isoformat()})


class GuardedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, upstream: str, token_file: Path, ledger: AdmissionLedger, *, allow_test_upstream=False, proxy_origin=None):
        parsed = urlsplit(upstream)
        if parsed.scheme != "http" or parsed.path not in ("", "/") or parsed.username or parsed.password:
            raise ValueError("plain approved in-cluster HTTP origin required")
        if not allow_test_upstream and upstream.rstrip("/") != APPROVED_UPSTREAM:
            raise ValueError("unexpected upstream")
        self.upstream = parsed
        self.proxy_origin = validate_proxy_origin(proxy_origin) if proxy_origin is not None else None
        self.token_file = token_file
        self.ledger = ledger
        self.activity=threading.Condition()
        self.active={}
        self.fencing=False
        self.drain_errors=[]
        super().__init__(address, GuardedHandler)

    def begin_upstream(self,connection,handler,path,body,headers):
        # TCP establishment sends no model request. If fencing races this
        # bounded connect, the subsequent check refuses before request bytes.
        with self.activity:
            if self.fencing:raise RuntimeError('GUARD_FENCED_BEFORE_UPSTREAM_CONNECT')
            self.active[id(handler)]=(connection,None,handler.connection)
        connection.connect()
        with self.activity:
            if self.fencing:raise RuntimeError('GUARD_FENCED_BEFORE_UPSTREAM_SEND')
            # Keep the actual socket even if HTTPConnection detaches it after
            # HTTP/1.0 response headers while the response body still blocks.
            self.active[id(handler)]=(connection,connection.sock,handler.connection)
            # Serialize initial request bytes with the fence. The socket has
            # a finite send timeout; response streaming does not hold this lock.
            connection.request('POST',path,body=body,headers=headers)

    def end_upstream(self,handler,error=None):
        with self.activity:
            if error is not None:self.drain_errors.append('GUARD_COMPLETION_PERSISTENCE_FAILED')
            self.active.pop(id(handler),None)
            self.activity.notify_all()

    def fence_and_drain(self,operation_id,*,timeout=5):
        if type(timeout) not in (int,float) or not 0<timeout<=5:
            raise ValueError('BOUNDED_GUARD_DRAIN_REQUIRED')
        deadline=time.monotonic()+timeout
        with self.activity:
            self.fencing=True
            fence_error=False
            try:self.ledger.fence(operation_id)
            except Exception:
                # A persistence failure cannot leave local transports running
                # or become an accepted drain receipt.
                fence_error=True
            for upstream,captured,downstream in list(self.active.values()):
                upstream_socket=captured if captured is not None else (upstream.sock if upstream is not None else None)
                for stream in (upstream_socket,downstream):
                    if stream is not None:
                        try:stream.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
            while self.active:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('GUARD_INFLIGHT_DRAIN_UNVERIFIED')
                self.activity.wait(remaining)
            if fence_error:raise RuntimeError('GUARD_FENCE_PERSISTENCE_FAILED')
            if self.drain_errors:raise RuntimeError('GUARD_COMPLETION_PERSISTENCE_FAILED')
        # No claim that a disconnected provider has stopped computation. Its
        # authoritative request record still requires separate reconciliation.
        return {'localInflightDrained':True,'providerExecutionStoppedVerified':False}


class GuardedHandler(BaseHTTPRequestHandler):
    server: GuardedServer

    def log_message(self, *_):
        return

    def do_GET(self):
        # Loopback-only task identity probe. Does not read a provider token,
        # reserve a model start, or expose request/response content.
        if self.path != '/_dsh/task-identity':
            return self._reject('invalid-identity-path', 404)
        data = json.dumps({'taskId': self.server.ledger.task_id,
            'correlationId': self.server.ledger.task_correlation_id,
            'maximum': self.server.ledger.maximum,
            'upstream': self.server.upstream.geturl().rstrip('/')}).encode()
        self.send_response(200)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
            target=proxy_request_target(self.path,self.server.proxy_origin)
            path=canonical_model_path(target)
        except ValueError:
            # Consume the (bounded) body first so a refused request is answered
            # instead of being reset by the unread bytes.
            try:self.rfile.read(max(0,min(int(self.headers.get("content-length","0")),MAX_BODY)))
            except (ValueError,OSError):pass
            return self._reject('invalid-model-path',400)
        try:
            length = int(self.headers.get("content-length", "-1"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self._reject("invalid-body-size", 413)
        body = self.rfile.read(length)
        try:
            body = sanitize_internal_request(path, body)
        except ValueError:
            return self._reject('invalid-request',400)
        if 'safeguards' in json.loads(body):
            # This internal custom-OpenAI route has no Anthropic classifier
            # capability. Refuse locally rather than stripping a requested
            # safeguard or spending an upstream turn on a known TypeError.
            # The client may negotiate its supported custom-endpoint shape;
            # that local exchange never reserves or retries an upstream call.
            return self._reject('unsupported-provider-safeguards',400)
        try:
            token = self.server.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            return self._reject("credential-unavailable", 503)
        try:
            with self.server.activity:
                if self.server.fencing:
                    return self._reject('task-fenced')
                accepted, reason, sequence, mark, operation_id = self.server.ledger.reserve(path, body)
                if accepted:self.server.active[id(self)]=(None,None,self.connection)
        except ValueError:
            return self._reject("invalid-request", 400)
        if not accepted:
            return self._reject(reason)

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_HEADERS | SERVER_IDENTITY_REQUEST_HEADERS}
        headers["authorization"] = "Bearer " + token
        headers[CORRELATION_HEADER] = operation_id
        headers['x-dsh-task-id']=self.server.ledger.task_id
        headers['x-dsh-task-correlation-id']=self.server.ledger.task_correlation_id
        # The installed LiteLLM proxy explicitly accepts this request ID and
        # returns it in its response header. Derive it from our durable guard
        # operation, after discarding any caller-supplied value. Anthropic
        # request metadata alone is not persisted reliably by that proxy.
        headers["x-litellm-call-id"] = str(uuid.UUID(operation_id))
        body = sanitize_internal_request(path, body, operation_id,
            task_id=self.server.ledger.task_id,task_correlation_id=self.server.ledger.task_correlation_id)
        headers["content-length"] = str(len(body))
        connection = http.client.HTTPConnection(self.server.upstream.hostname, self.server.upstream.port, timeout=5)
        status = 502
        outcome = "transport-failed"
        response_started = False
        upstream_identity = {}
        try:
            self.server.begin_upstream(connection,self,target,body,headers)
            if connection.sock is not None:connection.sock.settimeout(3600)
            response = connection.getresponse(); status = response.status
            upstream_identity = server_identity(response)
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
            error=None
            try:
                self.server.ledger.complete(sequence, mark, operation_id, status, outcome,
                                            upstream_identity=upstream_identity)
            except BaseException as exc:
                error=exc
                raise
            finally:self.server.end_upstream(self,error)


@contextlib.contextmanager
def running_guard(upstream: str, token_file: Path, ledger: AdmissionLedger, *, allow_test_upstream=False, listen_port=0, yield_server=False, proxy_origin=None):
    if type(yield_server) is not bool:raise ValueError('EXPLICIT_GUARD_CONTROL_MODE_REQUIRED')
    if type(listen_port) is not int or not (listen_port==0 or 1024<=listen_port<=65535):
        raise ValueError('invalid loopback guard port')
    # Binding must succeed before the client starts. Never connect a client to
    # an occupied port or silently select another endpoint after bind failure.
    server = GuardedServer(("127.0.0.1", listen_port), upstream, token_file, ledger, allow_test_upstream=allow_test_upstream, proxy_origin=proxy_origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield server if yield_server else server.server_port
    finally:
        try:server.fence_and_drain(uuid.uuid4().hex)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
