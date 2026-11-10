"""The worker Pod's model-guard sidecar: real guard, real drain contract, fake upstream, no cluster."""
import base64
import hashlib
import http.client
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from scripts.a2a_worker_journal import validate_guard_ledger
from types import SimpleNamespace

MODULE = Path(__file__).parents[1] / "container" / "dsh-task-guard-sidecar.py"
spec = importlib.util.spec_from_file_location("task_guard_sidecar", MODULE)
sidecar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecar)

TASK = "a" * 32
CORRELATION = "b" * 32
POD_UID = "22222222-2222-4222-8222-222222222222"


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["content-length"]))
        data = b"ok"
        self.send_response(200)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.state, self.token, self.uid = root / "state", root / "api-key", root / "pod-uid"
        self.token.write_text("synthetic-task-key")
        self.uid.write_text(POD_UID + "\n")
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.upstream.shutdown(), self.upstream.server_close()))

    def request(self, **over):
        value = dict(kind="fence-and-snapshot", taskId=TASK, correlationId=CORRELATION, podUID=POD_UID,
                     operationId="c" * 32)
        value.update(over)
        return json.dumps(value, separators=(",", ":")) + "\n"

    def run_sidecar(self, stdin_text, **over):
        out = io.StringIO()
        args = dict(task_id=TASK, correlation_id=CORRELATION, stdin=io.StringIO(stdin_text), stdout=out,
                    state_root=self.state, token_file=self.token, pod_uid_file=self.uid, listen_port=0,
                    upstream="http://127.0.0.1:%d" % self.upstream.server_port, allow_test_upstream=True)
        args.update(over)
        return sidecar.run(**args), out.getvalue()

    def test_drain_request_returns_one_validated_receipt_with_the_fenced_ledger(self):
        code, text = self.run_sidecar(self.request())
        self.assertEqual(code, 0)
        self.assertEqual(text.count("\n"), 1)
        receipt = json.loads(text)
        self.assertEqual(receipt["kind"], "DSH_GUARD_LOCAL_DRAIN_V1")
        raw = base64.b64decode(receipt["ledgerBase64"], validate=True)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt["ledgerSha256"])
        rows = validate_guard_ledger(SimpleNamespace(id=TASK, correlation_id=CORRELATION), raw)
        self.assertTrue(any(r["event"] == "task-fenced" and r["operation_id"] == "c" * 32 for r in rows))
        self.assertFalse(receipt["providerExecutionStoppedVerified"])

    def test_a_model_call_through_the_guard_is_in_the_snapshot_once(self):
        # The sidecar serves the guard while it waits for the command; drive one call from another thread by
        # sending the drain request only after the call has completed.
        port = free_port()
        gate, done = threading.Event(), threading.Event()
        out = io.StringIO()

        class Stdin:
            def readline(self_inner, _n=-1):
                gate.wait(10)
                return self.request()

        def worker():
            sidecar.run(task_id=TASK, correlation_id=CORRELATION, stdin=Stdin(), stdout=out, state_root=self.state,
                        token_file=self.token, pod_uid_file=self.uid, listen_port=port,
                        upstream="http://127.0.0.1:%d" % self.upstream.server_port, allow_test_upstream=True)
            done.set()

        threading.Thread(target=worker, daemon=True).start()
        for _ in range(100):
            try:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", "/_dsh/task-identity")
                identity = json.loads(c.getresponse().read())
                c.close()
                break
            except OSError:
                threading.Event().wait(0.05)
        self.assertEqual((identity["taskId"], identity["correlationId"], identity["maximum"]), (TASK, CORRELATION, 1))
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/v1/messages", body=b'{"messages":[]}', headers={"content-type": "application/json"})
        self.assertEqual(c.getresponse().status, 200)
        c.close()
        gate.set()
        self.assertTrue(done.wait(10))
        raw = base64.b64decode(json.loads(out.getvalue())["ledgerBase64"])
        events = [json.loads(line)["event"] for line in raw.decode().splitlines()]
        # The guard may record completion just before or just after the fence when the client has already read the
        # response (the existing guard tests show both orders); the ledger must hold exactly these three events.
        self.assertEqual(events[0], "upstream-start-reserved")
        self.assertEqual(sorted(events), ["task-fenced", "upstream-finished", "upstream-start-reserved"])
        validate_guard_ledger(SimpleNamespace(id=TASK, correlation_id=CORRELATION), raw)

    def test_foreign_requests_are_refused_and_print_nothing(self):
        for field, value in (("taskId", "f" * 32), ("correlationId", "d" * 32), ("podUID", "foreign"),
                             ("operationId", "bad"), ("kind", "restart")):
            with self.subTest(field=field):
                self.setUp()
                out = io.StringIO()
                with self.assertRaises(ValueError):
                    sidecar.run(task_id=TASK, correlation_id=CORRELATION, stdin=io.StringIO(self.request(**{field: value})),
                                stdout=out, state_root=self.state, token_file=self.token, pod_uid_file=self.uid,
                                listen_port=0, upstream="http://127.0.0.1:%d" % self.upstream.server_port,
                                allow_test_upstream=True)
                self.assertEqual(out.getvalue(), "")

    def test_missing_oversized_or_duplicate_key_requests_are_refused(self):
        for text in ("", "x" * 70000 + "\n", '{"kind":"fence-and-snapshot","kind":"x"}\n'):
            with self.subTest(size=len(text)):
                self.setUp()
                with self.assertRaises(ValueError):
                    self.run_sidecar(text)

    def test_identity_inputs_are_validated_before_the_guard_starts(self):
        for over in (dict(task_id="short"), dict(correlation_id="not-a-correlation")):
            with self.subTest(over=over), self.assertRaises(ValueError):
                self.run_sidecar(self.request(), **over)
        self.uid.write_text("not-a-uid\n")
        with self.assertRaisesRegex(ValueError, "INVALID_WORKER_POD_UID"):
            self.run_sidecar(self.request())
        self.assertFalse(self.state.exists())

    def test_the_task_state_directory_cannot_be_reused(self):
        self.run_sidecar(self.request())
        with self.assertRaises(FileExistsError):
            self.run_sidecar(self.request())

    def test_the_pod_arguments_match_what_the_sidecar_accepts(self):
        # scripts/a2a_private_worker_pod.py starts it with exactly these flags and probes loopback port 4001.
        source = (Path(__file__).parents[1] / "scripts" / "a2a_private_worker_pod.py").read_text(encoding="utf-8")
        for needle in ("'--task-id'", "'--correlation-id'", "'--drain-on-stdin'", "4001",
                       "/opt/dsh/container/dsh-task-guard-sidecar.py"):
            self.assertIn(needle, source)
        self.assertEqual(sidecar.GUARD_PORT, 4001)
        self.assertEqual(sidecar.MAX_MODEL_STARTS, 1)


if __name__ == "__main__":
    unittest.main()
