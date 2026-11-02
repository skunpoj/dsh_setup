"""Real Task journal + synthetic SDK/supervisor; no package/model/cluster use."""
from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib import request as http_request, error as http_error

from scripts.official_sdk_session import OfficialSDKSessionRunner, SDK_VERSION


class Subscription:
    def __init__(self): self.queue = queue.Queue()
    def next(self):
        value = self.queue.get()
        if value is None: raise RuntimeError("synthetic closed subscription")
        return value
    def close(self): self.queue.put(None)


class Client:
    def __init__(self):
        self.requests = queue.Queue(); self.decision = threading.Event()
        self.responses = []; self.subscription = Subscription()
    def next_request(self):
        value = self.requests.get()
        if value is None: raise RuntimeError("synthetic closed client")
        return value
    def subscribe_session_notifications(self, session): return self.subscription
    def respond(self, request_id, response):
        self.responses.append((request_id, response)); self.decision.set()
    def close(self):
        self.requests.put(None); self.subscription.close(); self.decision.set()


class Harness:
    def __init__(self):
        self.client = Client(); self.start_count = self.run_count = 0
        self.approval = None
        self.result_ready = threading.Event()
    def start(self): self.start_count += 1
    def run(self, prompt, *, session_id):
        self.run_count += 1
        if self.approval is not None:
            self.client.requests.put(SimpleNamespace(id=1, method=self.approval,
                payload={"sessionId": session_id, "toolName": "write", "callId": "native1"}))
            if not self.client.decision.wait(2): raise TimeoutError("synthetic decision")
        self.result_ready.set()
        return SimpleNamespace(finish_reason="completed", final_response="SYNTHETIC_NATIVE_RESULT")


class Scope:
    qualified = True
    def __init__(self):
        self.starts = self.stops = 0; self.started = False; self.fenced = False
        self.identity = {"ownedNativeHandle": "synthetic-handle-1"}
        self.start_hook = None; self.stop_identity = None
    def admission_state(self, subject, generation):
        return {"admitted": True, "subject": subject, "generation": generation,
            "packageAdmissionSha256": "a" * 64, "isolatedControl": True,
            "brokerCredentialMounts": False, "expiresAt": time.time() + 30}
    def preflight(self, context):
        return {**context, "admitted": True, "packageAdmissionSha256": "a" * 64}
    def inspect_exit(self, context):
        return {**context, "stopped": False, "processExitVerified": False, "launchFenced": self.fenced}
    def start(self, harness, context):
        self.starts += 1
        if self.start_hook: self.start_hook()
        if self.fenced: return {**context, "started": False}
        harness.start(); self.started = True
        return {**context, "started": True, "runtimeIdentity": self.identity}
    def stop_and_verify(self, harness, context):
        self.stops += 1; self.fenced = True; harness.client.close()
        return {**context, "stopped": True, "processExitVerified": True,
            "launchFenced": True, "neverStarted": not self.started,
            "runtimeIdentity": self.stop_identity or (self.identity if self.started else None)}


class SessionRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.workspace = root / "workspace"; self.workspace.mkdir()
        self.env = patch.dict(os.environ, {"DSH_TASK_STATE_ROOT": str(root / "state"),
            "DSH_TASK_WORKSPACE_ROOT": str(self.workspace)})
        self.env.start(); self.addCleanup(self.env.stop)
        spec = importlib.util.spec_from_file_location("native_session_broker",
            Path(__file__).resolve().parents[1] / "container/dsh-task-broker.py")
        self.broker = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.broker)
        self.task = self.broker.Task("a" * 32, {"runtime": "sdk", "backend": "private",
            "project": ".", "writes": False, "prompt": "synthetic input"})
        self.scope = Scope(); self.harness = Harness(); self.options = None
        self.addCleanup(self.harness.client.close)
        self.guard_temperature = 0; self.guard_correlation = None
        @contextmanager
        def guard(task):
            yield SimpleNamespace(base_url="http://127.0.0.1:7777/v1", task_id=task.id,
                correlation_id=self.guard_correlation or task.correlation_id, temperature=self.guard_temperature)
        self.guard_factory = guard
        self.runner = self.make_runner()
    def make_runner(self, version=lambda name: SDK_VERSION):
        def factory(**options): self.options = options; return self.harness
        return OfficialSDKSessionRunner(subject="owner", generation="g1",
            guard_factory=self.guard_factory, runtime_scope=self.scope, harness_factory=factory,
            admission_check=lambda: {"admissionSha256": "a" * 64},
            version=version, operation_timeout=.3, workspace_root=self.workspace)
    def run_task(self): self.runner.run_task("owner", self.task)
    def test_fresh_admission_revocation_disables_runtime(self):
        self.assertTrue(self.runner.qualified)
        self.runner.admission_check = lambda: {"admissionSha256": "b" * 64}
        self.assertFalse(self.runner.qualified)
        self.run_task()
        self.assertEqual(self.scope.starts, 0)
    def test_stale_scope_admission_disables_runtime(self):
        original = self.scope.admission_state
        self.scope.admission_state = lambda subject, generation: {
            **original(subject, generation), "expiresAt": time.time() - 1}
        self.assertFalse(self.runner.qualified)
    def saved(self): return json.loads((self.task.directory / "task.json").read_text())
    def wait_phase(self, phase):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.task.persistence_lock:
                if self.task.native_sdk and self.task.native_sdk["phase"] == phase: return
            time.sleep(.005)
        self.fail("Native synthetic phase not reached: " + phase)

    def test_normal_turn_uses_official_shape_guard_and_exact_retirement(self):
        self.run_task()
        self.assertEqual(self.task.state, "completed")
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "stopped")
        self.assertEqual(self.scope.starts, 1); self.assertEqual(self.scope.stops, 1)
        self.assertEqual(self.harness.run_count, 1)
        self.assertTrue(self.options["approval_requests"])
        self.assertEqual(self.options["base_url"], "http://127.0.0.1:7777/v1")
        self.assertIn("SYNTHETIC_NATIVE_RESULT", self.task.events.read_text())
        self.assertTrue(self.task.finished.is_set())

    def test_authenticated_http_dispatches_only_configured_native_runner(self):
        token = Path(self.temp.name) / "token"; token.write_text("x" * 32)
        self.broker.TOKEN = token
        server = self.broker.ThreadingHTTPServer(("127.0.0.1", 0), self.broker.Handler)
        server.sdk_service = self.runner
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def cleanup(): server.shutdown(); server.server_close()
        self.addCleanup(cleanup)
        body = {"runtime": "sdk", "backend": "private", "project": ".",
                "prompt": "synthetic HTTP input", "writes": False, "approved": True}
        def call(subject):
            headers = {"Authorization": "Bearer " + "x" * 32, "X-DSH-Subject": subject}
            url = "http://127.0.0.1:" + str(server.server_port) + "/v1/tasks"
            try:
                with http_request.urlopen(http_request.Request(url, data=json.dumps(body).encode(),
                    method="POST", headers=headers), timeout=3) as response:
                    return response.status, json.load(response)
            except http_error.HTTPError as response: return response.code, json.load(response)
        self.assertEqual(call("foreign")[0], 400)
        self.assertEqual(self.scope.starts, 0)
        status, value = call("owner"); self.assertEqual(status, 202)
        task = self.broker.REGISTRY.get(value["taskId"])
        self.assertTrue(task.finished.wait(3))
        self.assertEqual(task.state, "completed")
        self.assertEqual(self.scope.starts, 1); self.assertEqual(self.scope.stops, 1)
        self.assertEqual(task.native_sdk["subject"], "owner")

    def test_sdk_parent_environment_values_are_not_inherited(self):
        with patch.dict(os.environ, {"CUSTOM_PRIVATE_TOKEN": "SYNTHETIC_PRIVATE",
                                   "OPENAI_API_KEY": "SYNTHETIC_PROVIDER"}): self.run_task()
        self.assertNotIn("CUSTOM_PRIVATE_TOKEN", self.options["env"])
        self.assertNotIn("OPENAI_API_KEY", self.options["env"])
        self.assertNotIn("SYNTHETIC_PRIVATE", str(self.options))
        self.assertNotIn("SYNTHETIC_PROVIDER", str(self.options))
        self.assertEqual(self.options["env"]["DSH_CORRELATION_ID"], self.task.correlation_id)

    def test_old_pair_refuses_before_harness_or_native_start(self):
        self.runner = self.make_runner(version=lambda name: "0.2.1rc2")
        self.run_task()
        self.assertEqual(self.task.state, "failed")
        self.assertIsNone(self.options); self.assertEqual(self.scope.starts, 0)

    def test_foreign_subject_and_unsupported_handoff_refuse_without_start(self):
        with self.assertRaises(ValueError): self.runner.run_task("other", self.task)
        self.task.request["handoffRuntime"] = "claude"
        with self.assertRaises(ValueError): self.run_task()
        self.assertEqual(self.scope.starts, 0); self.assertIsNone(self.options)

    def test_project_escape_and_wrong_guard_identity_refuse_before_start(self):
        self.task.request["project"] = ".."
        self.run_task(); self.assertEqual(self.scope.starts, 0)
        self.assertIsNone(self.options)

    def test_wrong_guard_correlation_refuses_before_start(self):
        self.guard_correlation = "b" * 32
        self.run_task(); self.assertEqual(self.scope.starts, 0); self.assertIsNone(self.options)

    def test_temperature_policy_is_required(self):
        self.guard_temperature = False
        self.run_task(); self.assertEqual(self.scope.starts, 0); self.assertIsNone(self.options)

    def test_native_wire_request_pauses_for_bound_broker_decision(self):
        self.harness.approval = "approval/request"
        worker = threading.Thread(target=self.run_task); worker.start()
        self.wait_phase("awaiting-approval")
        pending = self.task.native_sdk["pending"]
        self.task.official_sdk_bridge.decide(subject="owner", generation="g1",
            approval_id=pending["approvalId"], outcome="rejected")
        worker.join(2); self.assertFalse(worker.is_alive())
        self.assertEqual(self.task.state, "completed")
        self.assertEqual(self.harness.client.responses, [(1, {"outcome": "rejected"})])
        self.assertEqual(self.scope.stops, 1)

    def test_result_waits_for_decision_journal_settlement_not_just_pipe_write(self):
        self.harness.approval = "approval/request"
        self.runner.operation_timeout = 1
        release = threading.Event(); self.addCleanup(release.set)
        original = self.harness.client.respond
        def delayed_response(*args):
            original(*args)  # Native peer can finish before this send returns.
            release.wait(3)
        self.harness.client.respond = delayed_response
        worker = threading.Thread(target=self.run_task); worker.start()
        self.wait_phase("awaiting-approval")
        pending = self.task.native_sdk["pending"]
        deciding = threading.Thread(target=lambda: self.task.official_sdk_bridge.decide(
            subject="owner", generation="g1", approval_id=pending["approvalId"], outcome="rejected"))
        deciding.start(); self.assertTrue(self.harness.result_ready.wait(1))
        self.assertEqual(self.task.native_sdk["phase"], "decision-reserved")
        self.assertEqual(self.scope.stops, 0)
        release.set(); deciding.join(2); worker.join(2)
        self.assertFalse(deciding.is_alive()); self.assertFalse(worker.is_alive())
        self.assertEqual(self.task.state, "completed")
        self.assertEqual(self.scope.stops, 1)

    def test_unknown_request_fails_and_retires_instead_of_granting(self):
        self.harness.approval = "unexpected/request"
        self.run_task()
        self.assertEqual(self.task.state, "failed")
        self.assertEqual(self.harness.client.responses, [])
        self.assertEqual(self.scope.stops, 1)

    def test_stop_identity_mismatch_cannot_claim_completed(self):
        self.scope.stop_identity = {"ownedNativeHandle": "other"}
        self.run_task()
        self.assertEqual(self.task.state, "interrupted")
        self.assertEqual(self.task.native_sdk["phase"], "stop-uncertain")

    def test_cancel_during_start_fences_late_start_without_running_prompt(self):
        self.scope.start_hook = lambda: self.task.cancel()
        self.run_task()
        self.assertEqual(self.task.state, "cancelled")
        self.assertEqual(self.harness.run_count, 0)
        self.assertEqual(self.scope.starts, 1); self.assertEqual(self.scope.stops, 1)

    def test_unqualified_scope_refused_at_construction(self):
        self.scope.qualified = False
        with self.assertRaises(ValueError): self.make_runner()

    def test_scope_revocation_refuses_before_start_and_changes_capability(self):
        self.scope.qualified = False
        self.assertFalse(self.runner.qualified)
        self.run_task()
        self.assertEqual(self.task.state, "failed")
        self.assertEqual(self.scope.starts, 0); self.assertIsNone(self.options)

    def test_managed_observer_cleanup_blocks_admission_and_live_recovery(self):
        self.run_task()
        self.task.finished.clear()
        self.broker.REGISTRY.tasks[self.task.id] = self.task
        with self.assertRaisesRegex(RuntimeError, "TASK_ALREADY_ACTIVE"):
            self.broker.REGISTRY.create({"runtime": "claude", "backend": "private",
                                        "project": ".", "writes": False, "prompt": "not executed"})
        self.task.native_sdk["phase"] = "observer-cleanup-uncertain"
        self.task.state = "interrupted"
        self.assertFalse(self.runner.recover_task("owner", self.task))

    def recovery_fixture(self):
        # Simulate a crash after native launch and before checked completion.
        self.task.state = "interrupted"
        self.task.native_sdk = {"subject": "owner", "generation": "old-g0",
            "taskId": self.task.id, "project": ".", "correlationId": self.task.correlation_id,
            "sessionId": self.task.id, "launchOperationId": "b" * 32,
            "runtimeIdentity": self.scope.identity, "phase": "fenced-after-recovery"}
        self.task.save()
        return {"subject": "owner", "generation": "old-g0", "taskId": self.task.id,
            "project": ".", "correlationId": self.task.correlation_id,
            "sessionId": self.task.id, "launchOperationId": "b" * 32,
            "runtimeIdentity": self.scope.identity}

    def test_recovery_uses_old_bound_identity_and_never_restarts_session(self):
        context = self.recovery_fixture(); seen = []
        def inspect(request):
            seen.append(request)
            return {**request, "operationId": "c" * 32, "stopped": True,
                    "processExitVerified": True, "launchFenced": True}
        self.scope.inspect_exit = inspect
        self.assertTrue(self.runner.recover_task("owner", self.task))
        self.assertEqual(seen, [context])
        self.assertEqual(self.task.state, "failed")  # No completed result was saved.
        self.assertEqual(self.task.native_sdk["phase"], "stopped")
        self.assertIsNone(self.options)
        self.assertEqual(self.scope.starts, 0); self.assertEqual(self.scope.stops, 0)
        self.assertEqual(self.harness.run_count, 0)

    def test_recovery_live_or_foreign_native_receipt_cannot_unfence(self):
        self.recovery_fixture()
        self.scope.inspect_exit = lambda context: {**context, "generation": "foreign",
            "operationId": "c" * 32, "stopped": True,
            "processExitVerified": True, "launchFenced": True}
        self.assertFalse(self.runner.recover_task("owner", self.task))
        self.assertEqual(self.task.state, "interrupted")
        self.assertEqual(self.scope.starts, 0)

    def test_recovery_timeout_observes_same_handle_without_second_lookup(self):
        self.recovery_fixture(); release = threading.Event(); self.addCleanup(release.set)
        seen = []; self.runner.operation_timeout = .03
        def inspect(context):
            seen.append(context); release.wait(2)
            return {**context, "operationId": "c" * 32, "stopped": True,
                    "processExitVerified": True, "launchFenced": True}
        self.scope.inspect_exit = inspect
        self.assertFalse(self.runner.recover_task("owner", self.task))
        self.assertEqual(self.task.native_sdk["phase"], "recovery-read-uncertain")
        release.set(); call, _ = self.runner.recovery_calls[self.task.id]
        self.assertTrue(call.done.wait(1))
        self.assertTrue(self.runner.recover_task("owner", self.task))
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.scope.starts, 0)


if __name__ == "__main__": unittest.main()
