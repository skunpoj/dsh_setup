"""Synthetic package and pipe checks. No real SDK/native process/provider."""
import ast
import base64
import csv
import hashlib
import importlib.util
import io
import json
import queue
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import zipfile

from scripts.official_sdk_control_peer import SDKFrameCodec, SDKControlPeer
from scripts.official_sdk_package_admission import verify_sdk_admission, VERSION, SOURCE


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.installed = self.root / "site"
        self.wheel = self.root / "sdk.whl"; self.manifest = self.root / "admission.json"
        # Importing this would fail. Verification must only read its bytes.
        self.payload = {"deepseek_harness/__init__.py": b'raise RuntimeError("MUST_NOT_EXECUTE")\n',
            f"deepseek_harness_sdk-{VERSION}.dist-info/METADATA": b"synthetic metadata"}
        rows = []
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, data in self.payload.items():
                archive.writestr(name, data)
                file = self.installed / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_bytes(data)
                digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                rows.append([name, "sha256=" + digest, str(len(data))])
        record = io.StringIO(); csv.writer(record).writerows(rows)
        self.record = self.installed / f"deepseek_harness_sdk-{VERSION}.dist-info/RECORD"
        self.record.write_bytes(record.getvalue().encode())
        self.manifest.write_text(json.dumps({"kind": "DSH_OFFICIAL_SDK_PACKAGE_V1", "sourceCommit": SOURCE,
            "sdkVersion": VERSION, "runtimeVersion": VERSION,
            "sdkWheelSha256": hashlib.sha256(self.wheel.read_bytes()).hexdigest(),
            "installedRecordSha256": hashlib.sha256(self.record.read_bytes()).hexdigest()}))
    def check(self):
        def reader(path, limit):
            data = Path(path).read_bytes()
            if len(data) > limit: raise ValueError("oversize")
            return data
        return verify_sdk_admission(admission_path=self.manifest, installed=self.installed,
            wheel=self.wheel, reader=reader)
    def test_verification_reads_exact_package_without_execution(self):
        self.assertEqual(self.check()["sdkVersion"], VERSION)
    def test_same_version_repacked_wheel_refused(self):
        with zipfile.ZipFile(self.wheel, "a") as archive: archive.writestr("extra.txt", "repacked")
        with self.assertRaisesRegex(ValueError, "WHEEL_ADMISSION_HASH"): self.check()
    def test_installed_tamper_refused(self):
        (self.installed / "deepseek_harness/__init__.py").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "CONTENT_MISMATCH"): self.check()
    def test_record_tamper_refused(self):
        self.record.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "RECORD_HASH"): self.check()
    def test_unadmitted_module_refused(self):
        (self.installed / "deepseek_harness/extra.py").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "UNADMITTED"): self.check()
    def test_codec_accepts_only_authenticated_ordered_bound_frames(self):
        a = SDKFrameCodec(b"a" * 32, {"taskId": "synthetic"})
        b = SDKFrameCodec(b"a" * 32, {"taskId": "synthetic"})
        frame = a.encode({"kind": "call"}); self.assertEqual(b.decode(frame), {"kind": "call"})
        with self.assertRaises(ValueError): b.decode(frame)
        with self.assertRaises(ValueError): SDKFrameCodec(b"b" * 32, a.binding).decode(frame)
        with self.assertRaises(ValueError): SDKFrameCodec(b"a" * 32, {"taskId": "foreign"}).decode(frame)
    def test_codec_rejects_duplicate_fields_and_tamper(self):
        codec = SDKFrameCodec(b"a" * 32, {})
        with self.assertRaises(ValueError): codec.decode('{"v":1,"v":1}')
        frame = codec.encode({"ok": True}).replace('true', 'false')
        with self.assertRaises(ValueError): SDKFrameCodec(b"a" * 32, {}).decode(frame)
    def test_parent_modules_do_not_import_sdk_or_spawn_process(self):
        root = Path(__file__).resolve().parents[1]
        for file in ("official_sdk_session.py", "official_sdk_control_peer.py", "official_sdk_package_admission.py"):
            tree = ast.parse((root / "scripts" / file).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom): self.assertNotIn("deepseek_harness", node.module or "")
                if isinstance(node, ast.Import):
                    self.assertFalse(any(n.name.startswith(("deepseek_harness", "subprocess")) for n in node.names))
    def test_transport_is_not_started_during_construction(self):
        class Scope:
            def control_transport(self, **kwargs):
                self.arguments = kwargs
                return object()
        scope = Scope(); peer = SDKControlPeer(runtime_scope=scope, binding={}, options={})
        self.assertFalse(peer.started)
        self.assertIn("-S", scope.arguments["command"])
    def test_child_duplicate_start_and_run_refused(self):
        path = Path(__file__).resolve().parents[1] / "container/dsh-sdk-control.py"
        spec = importlib.util.spec_from_file_location("synthetic_sdk_control", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        class Harness:
            def start(self): pass
        controller = module.Controller(Harness(), SDKFrameCodec(b"a" * 32, {}), lambda raw: None)
        controller.started = True
        with self.assertRaises(ValueError):
            controller.dispatch({"kind": "call", "id": "first", "method": "start", "params": {}})

    def test_authenticated_pipe_roundtrip_with_native_approval(self):
        path = Path(__file__).resolve().parents[1] / "container/dsh-sdk-control.py"
        spec = importlib.util.spec_from_file_location("synthetic_sdk_roundtrip", path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        binding = {"sessionId": "a" * 32, "taskId": "a" * 32}
        class Harness:
            def __init__(self):
                self.client = self; self.requests = queue.Queue(); self.decision = threading.Event()
                self.starts = self.runs = 0; self.answer = None
            def start(self): self.starts += 1
            def next_request(self):
                value = self.requests.get(timeout=2)
                if value is None: raise RuntimeError("closed")
                return value
            def respond(self, operation, result):
                self.answer = (operation, result); self.decision.set()
            def run(self, prompt, *, session_id):
                self.runs += 1
                self.requests.put(SimpleNamespace(id="approval1", method="approval/request",
                    payload={"sessionId": session_id, "toolName": "synthetic"}))
                if not self.decision.wait(2): raise TimeoutError("synthetic approval")
                return SimpleNamespace(finish_reason="completed", final_response="synthetic checked output")
        harness = Harness()
        class Transport:
            def __init__(self): self.out = queue.Queue(); self.bootstraps = 0
            def start(self, bootstrap):
                self.bootstraps += 1
                self.codec = SDKFrameCodec(base64.b64decode(bootstrap["key"]), bootstrap["binding"])
                self.controller = module.Controller(harness, self.codec, self.out.put)
            def send(self, raw): self.controller.dispatch(self.codec.decode(raw))
            def receive(self):
                value = self.out.get(timeout=2)
                if value is None: raise RuntimeError("closed")
                return value
            def close(self):
                self.controller.closed.set(); harness.requests.put(None); self.out.put(None)
        transport = Transport()
        scope = SimpleNamespace(control_transport=lambda **kwargs: transport)
        peer = SDKControlPeer(runtime_scope=scope, binding=binding, options={})
        self.addCleanup(peer.close)
        peer.start()
        results = []
        run = threading.Thread(target=lambda: results.append(peer.run("synthetic", session_id=binding["sessionId"])))
        run.start()
        approval = peer.next_request(); self.assertEqual(approval.id, "approval1")
        peer.respond(approval.id, {"outcome": "allowed-once"})
        run.join(2); self.assertFalse(run.is_alive())
        self.assertEqual(results[0].final_response, "synthetic checked output")
        self.assertEqual(harness.answer, ("approval1", {"outcome": "allowed-once"}))
        self.assertEqual((transport.bootstraps, harness.starts, harness.runs), (1, 1, 1))
        with self.assertRaises(ValueError): peer.start()


if __name__ == "__main__": unittest.main()
