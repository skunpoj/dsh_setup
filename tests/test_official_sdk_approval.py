"""Existing Task journal + synthetic native transport; no SDK/model startup."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib import request as http_request, error as http_error

from scripts.official_sdk_approval import NativeSDKApprovalBridge, NativeOperationTimeout


class NativeApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"DSH_TASK_STATE_ROOT": str(root / "state"),
            "DSH_TASK_WORKSPACE_ROOT": str(root)})
        self.env.start(); self.addCleanup(self.env.stop)
        spec = importlib.util.spec_from_file_location("approval_test_broker",
            Path(__file__).resolve().parents[1] / "container/dsh-task-broker.py")
        self.broker = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.broker)
        self.task = self.broker.Task("a" * 32, {
            "runtime": "sdk", "project": ".", "writes": False, "backend": "private"})
        self.task.state = "running"; self.task.save()
        self.client = Mock()
        self.bridge = NativeSDKApprovalBridge(self.task, self.client,
            subject="owner@example.com", generation="g1", session_id="session1")

    def receive(self, call="call1", **changes):
        payload = {"sessionId": "session1", "toolName": "write", "callId": call}
        payload.update(changes)
        return self.bridge.receive(SimpleNamespace(id=1, method="approval/request", payload=payload))

    def decide(self, ticket, **changes):
        values = {"subject": "owner@example.com", "generation": "g1",
                  "approval_id": ticket["approvalId"], "outcome": "rejected"}
        values.update(changes); return self.bridge.decide(**values)

    def saved(self):
        return json.loads((self.task.directory / "task.json").read_text())

    def test_decision_reserved_in_same_task_before_one_native_response(self):
        ticket = self.receive(reason="synthetic untrusted reason")
        saved = self.saved()
        self.assertEqual(saved["nativeSdk"]["pending"]["approvalId"], ticket["approvalId"])
        self.assertNotIn("reason", saved["nativeSdk"]["pending"])
        self.assertFalse(self.task.approve())  # Never launches checkpoint helper.
        def observe(*args):
            self.assertEqual(self.saved()["nativeSdk"]["phase"], "decision-reserved")
        self.client.respond.side_effect = observe
        self.decide(ticket)
        self.client.respond.assert_called_once_with(1, {"outcome": "rejected"})
        self.assertEqual(self.saved()["nativeSdk"]["usedCallIds"], ["call1"])
        with self.assertRaises(ValueError): self.decide(ticket)
        with self.assertRaises(ValueError): self.receive()
        self.assertEqual(self.client.respond.call_count, 1)

    def test_foreign_owner_generation_and_ticket_cannot_decide(self):
        ticket = self.receive()
        for change in ({"subject": "other"}, {"generation": "g2"}, {"approval_id": "stale"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.decide(ticket, **change)
        self.client.respond.assert_not_called()

    def test_http_decision_binds_exact_owner_and_ticket(self):
        token = Path(self.temp.name) / "token"; token.write_text("x" * 32)
        self.broker.TOKEN = token
        self.broker.REGISTRY.tasks[self.task.id] = self.task
        server = self.broker.ThreadingHTTPServer(("127.0.0.1", 0), self.broker.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def cleanup(): server.shutdown(); server.server_close()
        self.addCleanup(cleanup)
        ticket = self.receive()
        def call(suffix, value=None, subject="owner@example.com"):
            headers = {"Authorization": "Bearer " + "x" * 32, "X-DSH-Subject": subject}
            data = json.dumps(value).encode() if value is not None else None
            method = "POST" if data is not None else "GET"
            url = "http://127.0.0.1:" + str(server.server_port) + "/v1/tasks/" + self.task.id + suffix
            try:
                with http_request.urlopen(http_request.Request(url, data=data, headers=headers,
                                                              method=method), timeout=3) as response:
                    return response.status, json.load(response)
            except http_error.HTTPError as response:
                return response.code, json.load(response)
        status, body = call("/events")
        self.assertEqual(status, 200)
        self.assertEqual(body["nativeApproval"]["approvalId"], ticket["approvalId"])
        self.assertNotIn("requestId", body["nativeApproval"])
        for foreign in ("foreign", ""):
            status, body = call("/events", subject=foreign)
            self.assertEqual(status, 403)
            self.assertEqual(body, {"error": "FOREIGN_NATIVE_SDK_SUBJECT"})
            self.assertNotIn("events", body)
            self.assertNotIn("nativeApproval", body)
        self.assertEqual(call("/approve", {"approved": True})[0], 409)
        decision = {**ticket, "outcome": "rejected"}
        self.assertEqual(call("/approve", decision, subject="foreign")[0], 409)
        self.client.respond.assert_not_called()
        self.assertEqual(call("/approve", decision)[0], 202)
        self.client.respond.assert_called_once_with(1, {"outcome": "rejected"})
        self.assertEqual(call("/approve", decision)[0], 409)

    def test_allow_once_requires_explicit_task_write_admission(self):
        ticket = self.receive()
        with self.assertRaises(ValueError): self.decide(ticket, outcome="allowed-once")
        self.client.respond.assert_not_called()
        self.task.request["writes"] = True
        self.decide(ticket, outcome="allowed-once")
        self.client.respond.assert_called_once_with(1, {"outcome": "allowed-once"})

    def test_cancel_fences_pending_decision(self):
        ticket = self.receive()
        self.assertFalse(self.task.cancel())  # No native process-exit verifier.
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "fenced")
        self.assertEqual(self.task.state, "interrupted")
        with self.assertRaises(ValueError): self.decide(ticket)
        self.client.respond.assert_not_called()

    def test_cancel_requires_exact_native_exit_and_reserves_before_stop(self):
        ticket = self.receive()
        def stop(context):
            self.assertEqual(self.saved()["nativeSdk"]["phase"], "stop-reserved")
            self.assertEqual(self.saved()["nativeSdk"]["stopOperationId"], context["operationId"])
            return {**context, "stopped": True, "processExitVerified": True}
        self.bridge.stop_and_verify = Mock(side_effect=stop)
        self.assertTrue(self.task.cancel())
        self.assertEqual(self.task.state, "cancelled")
        self.assertFalse(self.task.cancel())
        self.bridge.stop_and_verify.assert_called_once()
        with self.assertRaises(ValueError): self.decide(ticket)
        self.client.respond.assert_not_called()

    def test_uncertain_native_stop_never_reports_cancelled_or_retries(self):
        self.receive()
        self.bridge.stop_and_verify = Mock(return_value={"stopped": True})
        self.assertFalse(self.task.cancel())
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "stop-uncertain")
        self.assertEqual(self.task.state, "interrupted")
        self.assertFalse(self.task.cancel())
        self.bridge.stop_and_verify.assert_called_once()

    def test_verified_terminal_stop_survives_restart_and_allows_new_admission(self):
        self.receive()
        self.bridge.stop_and_verify = lambda context: {
            **context, "stopped": True, "processExitVerified": True}
        self.assertTrue(self.task.cancel())
        registry = self.broker.Registry()
        recovered = registry.get(self.task.id)
        self.assertEqual(recovered.state, "cancelled")
        self.assertEqual(recovered.native_sdk["phase"], "stopped")
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "stopped")
        with patch.object(self.broker.threading, "Thread") as thread:
            new = registry.create({"runtime": "claude", "project": ".", "writes": False,
                                   "backend": "private", "prompt": "not executed"})
            thread.return_value.start.assert_called_once()
            self.assertNotEqual(new.id, recovered.id)

    def test_stopped_label_or_changed_exit_proof_still_fences_recovery(self):
        self.receive()
        self.bridge.stop_and_verify = lambda context: {
            **context, "stopped": True, "processExitVerified": True}
        self.assertTrue(self.task.cancel())
        original = self.saved()
        import copy
        for change in ("missing-proof", "foreign-generation", "no-exit-proof"):
            value = copy.deepcopy(original)
            if change == "missing-proof": value["nativeSdk"].pop("stopReceipt")
            elif change == "foreign-generation": value["nativeSdk"]["stopReceipt"]["generation"] = "g2"
            else: value["nativeSdk"]["stopReceipt"]["processExitVerified"] = False
            with self.subTest(change=change):
                recovered = self.broker.Task.recover(value, self.task.directory)
                self.assertEqual(recovered.native_sdk["phase"], "fenced-after-recovery")

    def natural_exit(self, code):
        self.bridge.stop_and_verify = Mock(side_effect=lambda context: {
            **context, "stopped": True, "processExitVerified": True})
        process = Mock(stdout=iter(["synthetic final result\n"]))
        process.wait.return_value = code
        with patch.object(self.broker.subprocess, "Popen", return_value=process):
            self.task.run()
        self.assertEqual(self.task.native_sdk["phase"], "stopped")
        self.assertTrue(self.task.finished.is_set())
        self.bridge.stop_and_verify.assert_called_once()
        self.client.respond.assert_not_called()
        registry = self.broker.Registry()
        with patch.object(self.broker.threading, "Thread") as thread:
            registry.create({"runtime": "claude", "backend": "private",
                             "project": ".", "prompt": "not executed", "writes": False})
            thread.return_value.start.assert_called_once()

    def test_natural_success_retires_native_process_before_completed_and_new_task(self):
        self.natural_exit(0)
        self.assertEqual(self.task.state, "completed")
        self.assertEqual(self.saved()["state"], "completed")

    def test_natural_failure_retires_native_process_and_unblocks_admission(self):
        self.natural_exit(1)
        self.assertEqual(self.task.state, "failed")

    def test_natural_success_without_exit_proof_stays_interrupted(self):
        self.bridge.stop_and_verify = Mock(return_value={"stopped": True})
        process = Mock(stdout=iter([])); process.wait.return_value = 0
        with patch.object(self.broker.subprocess, "Popen", return_value=process): self.task.run()
        self.assertEqual(self.task.state, "interrupted")
        self.assertEqual(self.task.native_sdk["phase"], "stop-uncertain")
        self.broker.REGISTRY.tasks[self.task.id] = self.task
        with self.assertRaisesRegex(RuntimeError, "TASK_ALREADY_ACTIVE"):
            self.broker.REGISTRY.create({"runtime": "sdk", "project": ".", "writes": False})

    def test_blocked_response_cannot_hold_cancel_lock_or_reopen_stopped_task(self):
        ticket = self.receive(); entered = threading.Event(); release = threading.Event()
        self.addCleanup(release.set)
        self.bridge.operation_timeout = 0.1
        self.client.respond.side_effect = lambda *a: (entered.set(), release.wait(3))
        self.bridge.stop_and_verify = Mock(side_effect=lambda context: {
            **context, "stopped": True, "processExitVerified": True})
        errors = []
        def decide():
            try: self.decide(ticket)
            except (NativeOperationTimeout, ValueError) as error: errors.append(type(error).__name__)
        deciding = threading.Thread(target=decide); deciding.start()
        self.assertTrue(entered.wait(1))
        start = time.monotonic()
        self.assertTrue(self.task.cancel())
        self.assertLess(time.monotonic() - start, 1)
        release.set(); deciding.join(2)
        self.assertFalse(deciding.is_alive())
        self.assertEqual(self.task.state, "cancelled")
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "stopped")
        self.assertEqual(len(errors), 1)
        self.client.respond.assert_called_once()
        self.bridge.stop_and_verify.assert_called_once()

    def test_response_observation_timeout_is_uncertain_never_retry_or_auto_resume(self):
        ticket = self.receive(); release = threading.Event(); self.addCleanup(release.set)
        self.bridge.operation_timeout = 0.03
        self.client.respond.side_effect = lambda *a: release.wait(3)
        start = time.monotonic()
        with self.assertRaises(NativeOperationTimeout): self.decide(ticket)
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.task.state, "interrupted")
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "decision-uncertain")
        with self.assertRaises(ValueError): self.decide(ticket)
        release.set()
        self.client.respond.assert_called_once()

    def test_blocked_stop_times_out_without_claiming_exit_and_resolves_same_call(self):
        release = threading.Event(); self.addCleanup(release.set)
        self.bridge.operation_timeout = 0.03
        def stop(context):
            release.wait(3)
            return {**context, "stopped": True, "processExitVerified": True}
        self.bridge.stop_and_verify = Mock(side_effect=stop)
        start = time.monotonic()
        self.assertFalse(self.task.cancel())
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.task.state, "interrupted")
        self.assertFalse(self.task.cancel())
        self.assertFalse(self.bridge.resolve_stop())
        release.set(); self.assertTrue(self.bridge._stop_call.done.wait(1))
        self.assertTrue(self.bridge.resolve_stop())
        self.assertEqual(self.task.state, "cancelled")
        self.bridge.stop_and_verify.assert_called_once()

    def test_cancel_supersedes_finalization_without_second_stop(self):
        entered = threading.Event(); release = threading.Event(); self.addCleanup(release.set)
        self.bridge.operation_timeout = 1
        def stop(context):
            entered.set(); release.wait(3)
            return {**context, "stopped": True, "processExitVerified": True}
        self.bridge.stop_and_verify = Mock(side_effect=stop)
        finishing = threading.Thread(target=lambda: self.bridge.finalize("completed")); finishing.start()
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.task.cancel())  # Intent is fenced; existing stop is still pending.
        release.set(); finishing.join(2)
        self.assertFalse(finishing.is_alive())
        self.assertEqual(self.task.state, "cancelled")
        self.bridge.stop_and_verify.assert_called_once()

    def test_changed_task_context_refused(self):
        ticket = self.receive()
        self.task.correlation_id = "b" * 32
        with self.assertRaises(ValueError): self.decide(ticket)
        self.client.respond.assert_not_called()

    def test_response_uncertainty_is_reserved_and_cannot_replay(self):
        ticket = self.receive()
        self.client.respond.side_effect = TimeoutError("synthetic")
        with self.assertRaises(TimeoutError): self.decide(ticket)
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "decision-uncertain")
        self.assertEqual(self.task.state, "interrupted")
        with self.assertRaises(ValueError): self.decide(ticket)
        self.assertEqual(self.client.respond.call_count, 1)

    def test_persistence_failure_never_responds(self):
        ticket = self.receive()
        with patch.object(self.task, "save", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError): self.decide(ticket)
        self.client.respond.assert_not_called()
        with self.assertRaises(ValueError): self.decide(ticket)

    def test_recovery_fences_saved_native_request_without_starting_client(self):
        self.receive()
        recovered = self.broker.Task.recover(self.saved(), self.task.directory)
        self.assertIsNone(recovered.official_sdk_bridge)
        self.assertEqual(recovered.state, "interrupted")
        self.assertEqual(self.saved()["nativeSdk"]["phase"], "fenced-after-recovery")
        self.assertFalse(recovered.approve())
        self.client.respond.assert_not_called()
        registry = self.broker.Registry()
        with self.assertRaisesRegex(RuntimeError, "TASK_ALREADY_ACTIVE"):
            registry.create({"runtime": "sdk", "project": ".", "writes": False,
                             "backend": "private", "prompt": "must not start"})

    def test_malformed_or_unbound_native_payload_refused(self):
        for changes in ({"sessionId": "other"}, {"callId": None}, {"toolName": "bad tool"},
                        {"unexpected": True}, {"reason": {}}, {"reason": "x" * 8193}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.receive(**changes)
        self.client.respond.assert_not_called()


if __name__ == "__main__": unittest.main()
