import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

from scripts.unattended_model_guard import (AdmissionLedger, GuardedServer,
    canonical_fingerprint, sanitize_internal_request)


class Upstream(BaseHTTPRequestHandler):
    calls = 0
    bodies = []
    barrier = None
    delay = 0
    payload = b'part-one\npart-two\n'
    received_headers = None
    def log_message(self, *_): pass
    def do_POST(self):
        type(self).calls += 1
        type(self).received_headers = {k.lower():v for k,v in self.headers.items()}
        body = self.rfile.read(int(self.headers["content-length"]))
        type(self).bodies.append(body)
        if type(self).barrier: type(self).barrier.wait(timeout=3)
        if type(self).delay: time.sleep(type(self).delay)
        payload = type(self).payload
        self.send_response(200); self.send_header("content-length", str(len(payload))); self.end_headers()
        self.wfile.write(payload[:7]); self.wfile.flush(); self.wfile.write(payload[7:])


class GuardCase(unittest.TestCase):
    CORRELATION = "a" * 32
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.token = root / "token"; self.token.write_text("synthetic-only")
        self.ledger_path = root / "ledger.jsonl"
        Upstream.calls = 0; Upstream.bodies = []; Upstream.barrier = None; Upstream.delay = 0; Upstream.received_headers = None
        Upstream.payload = b'part-one\npart-two\n'
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True); self.upstream_thread.start()

    def tearDown(self):
        self.upstream.shutdown(); self.upstream.server_close(); self.upstream_thread.join(timeout=2); self.tmp.cleanup()

    def guard(self, task="task-a", cap=3):
        server = GuardedServer(("127.0.0.1", 0), f"http://127.0.0.1:{self.upstream.server_port}", self.token,
                               AdmissionLedger(self.ledger_path, task, cap,
                                               task_correlation_id=self.CORRELATION), allow_test_upstream=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        return server, thread

    @staticmethod
    def send(port, body, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            supplied={"content-type":"application/json"}; supplied.update(headers or {})
            c.request("POST", "/v1/messages", body=body, headers=supplied)
            r = c.getresponse(); data = r.read(); return r.status, data
        finally:
            c.close()

    def test_stream_and_completion_ledger(self):
        server, thread = self.guard()
        try:
            status, data = self.send(server.server_port, b'{"messages":[1]}')
            self.assertEqual((status, data), (200, b"part-one\npart-two\n"))
            rows = [json.loads(x) for x in self.ledger_path.read_text().splitlines()]
            self.assertEqual([x["event"] for x in rows], ["upstream-start-reserved", "upstream-finished"])
            self.assertEqual(rows[1]["outcome"], "response-complete")
            self.assertEqual(rows[0]["task_correlation_id"], self.CORRELATION)
            self.assertEqual(rows[0]["operation_correlation_id"], rows[1]["operation_correlation_id"])
            self.assertEqual(Upstream.received_headers["x-dsh-correlation-id"], rows[0]["operation_correlation_id"])
            forwarded = json.loads(Upstream.bodies[0])
            self.assertEqual(forwarded["metadata"]["dsh_correlation_id"], rows[0]["operation_correlation_id"])
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_client_credentials_are_replaced_not_forwarded(self):
        server, thread = self.guard()
        try:
            self.assertEqual(self.send(server.server_port,b'{}',{"authorization":"Bearer client-value","x-api-key":"client-key"})[0],200)
            self.assertEqual(Upstream.received_headers["authorization"],"Bearer synthetic-only")
            self.assertNotIn("x-api-key",Upstream.received_headers)
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_provider_extensions_are_removed_from_internal_request(self):
        server, thread = self.guard()
        body = json.dumps({"model":"deepseek-v4.1-flash", "messages":[],
                           "dsh_session_log":{"events":[1]},
                           "dsh_plugin_packages":["one"],
                           "chat_template_kwargs":{"enable_thinking":False},
                           "metadata":{"keep":True}}).encode()
        try:
            self.assertEqual(self.send(server.server_port, body)[0], 200)
            forwarded = json.loads(Upstream.bodies[0])
            self.assertEqual(forwarded["model"],"deepseek-v4.1-flash")
            self.assertEqual(forwarded["messages"],[])
            self.assertTrue(forwarded["metadata"]["keep"])
            self.assertRegex(forwarded["metadata"]["dsh_correlation_id"],r"^[a-f0-9]{32}$")
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_sanitization_rejects_non_object_and_preserves_standard_fields(self):
        with self.assertRaises(ValueError):
            sanitize_internal_request("/v1/messages", b"[]")
        original = b'{"messages":[{"content":"dsh_text","role":"user"}],"stream":true}'
        self.assertEqual(json.loads(sanitize_internal_request("/v1/messages", original)),
                         json.loads(original))

    def test_duplicate_and_crash_reservation_never_replay(self):
        ledger = AdmissionLedger(self.ledger_path, "task-a", 3, task_correlation_id=self.CORRELATION)
        self.assertTrue(ledger.reserve("/v1/messages", b'{"a":1,"b":2}')[0])
        self.assertEqual(ledger.reserve("/v1/messages", b'{"b":2,"a":1}')[1], "duplicate-or-uncertain")

    def test_caller_disconnect_is_finished_and_never_replayed(self):
        Upstream.delay = .15; Upstream.payload = b'x' * (1024 * 1024)
        server, thread = self.guard()
        body=b'{"cancel":true}'
        try:
            client=socket.create_connection(("127.0.0.1",server.server_port),timeout=3)
            client.sendall(b"POST /v1/messages HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: "+str(len(body)).encode()+b"\r\n\r\n"+body)
            client.shutdown(socket.SHUT_RDWR); client.close()
            deadline=time.time()+4; rows=[]
            while time.time()<deadline:
                if self.ledger_path.exists(): rows=[json.loads(x) for x in self.ledger_path.read_text().splitlines()]
                if len(rows)>=2: break
                time.sleep(.05)
            self.assertEqual(rows[0]["event"],"upstream-start-reserved")
            self.assertEqual(rows[-1]["event"],"upstream-finished")
            self.assertIn(rows[-1]["outcome"],{"caller-cancelled-or-disconnected","response-complete"})
            self.assertEqual(AdmissionLedger(self.ledger_path,"task-a",3,task_correlation_id=self.CORRELATION).reserve("/v1/messages",body)[1],"duplicate-or-uncertain")
            self.assertEqual(Upstream.calls,1)
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_concurrent_duplicate_has_one_upstream_start(self):
        server, thread = self.guard(); results=[]; failures=[]; result_lock=threading.Lock()
        try:
            def send():
                try:
                    value=self.send(server.server_port,b'{"same":true}')[0]
                    with result_lock: results.append(value)
                except Exception as error:
                    with result_lock: failures.append(repr(error))
            workers=[threading.Thread(target=send) for _ in range(8)]
            [w.start() for w in workers]; [w.join() for w in workers]
            self.assertEqual(failures, [])
            self.assertEqual(results.count(200), 1); self.assertEqual(results.count(422), 7); self.assertEqual(Upstream.calls, 1)
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_cap_and_task_isolation(self):
        one=AdmissionLedger(self.ledger_path,"one",1,task_correlation_id="1"*32)
        two=AdmissionLedger(self.ledger_path,"two",1,task_correlation_id="2"*32)
        self.assertTrue(one.reserve("/v1/responses",b'{"input":1}')[0])
        self.assertEqual(one.reserve("/v1/responses",b'{"input":2}')[1],"task-cap")
        self.assertTrue(two.reserve("/v1/responses",b'{"input":1}')[0])

    def test_no_credential_reserves_nothing(self):
        self.token.unlink(); server,thread=self.guard()
        try:
            self.assertEqual(self.send(server.server_port,b'{}')[0],503)
            self.assertFalse(self.ledger_path.exists())
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_validation(self):
        with self.assertRaises(ValueError): canonical_fingerprint("/bad",b'{}')
        with self.assertRaises(ValueError): AdmissionLedger(self.ledger_path,"../bad",1,task_correlation_id=self.CORRELATION)
        with self.assertRaises(ValueError): GuardedServer(("127.0.0.1",0),"http://example.com",self.token,AdmissionLedger(self.ledger_path,"ok",1,task_correlation_id=self.CORRELATION))

    def test_client_cannot_forge_correlation(self):
        server, thread = self.guard()
        try:
            body=json.dumps({"messages":[],"metadata":{"dsh_correlation_id":"b"*32}}).encode()
            self.assertEqual(self.send(server.server_port,body)[0],400)
            self.assertEqual(Upstream.calls,0)
        finally: server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__": unittest.main()
