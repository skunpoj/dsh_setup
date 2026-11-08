"""One-shot native SDK decisions in the existing broker Task journal.

The protected launcher supplies the native client/session and authenticated
owner/generation. This module does not start a runtime, model or subprocess,
and does not enable SDK approval support on an incompatible native binary.
"""
import re
import threading
import uuid


class NativeOperationTimeout(TimeoutError):
    pass


class _ReservedCall:
    """One external invocation; timeout stops waiting, never retries or claims exit.

    An unresponsive callback may still be running. Its durable operation stays
    reserved, and only its exact completed receipt can later resolve it.
    """
    def __init__(self, callback):
        self.done = threading.Event()
        self.value = None
        self.error = None
        def run():
            try: self.value = callback()
            except BaseException as error: self.error = error
            finally: self.done.set()
        self.thread = threading.Thread(target=run, daemon=True)

    def result(self, timeout):
        if not self.done.wait(timeout):
            raise NativeOperationTimeout("NATIVE_OPERATION_STILL_RESERVED")
        if self.error is not None: raise self.error
        return self.value


def verified_terminal_stop(record):
    """Retain an exact saved exit proof; a stopped label alone is insufficient."""
    native = record.get("nativeSdk")
    if (record.get("state") not in {"completed", "failed", "cancelled"}
            or not isinstance(native, dict) or native.get("phase") != "stopped"
            or native.get('postStopLifecycleFailure')
            or native.get('guardLifecyclePending')
            or not isinstance(native.get("stopOperationId"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", native["stopOperationId"])
            or native.get("taskId") != record.get("id")
            or native.get("project") != record.get("project")
            or native.get("correlationId") != record.get("correlationId")):
        return False
    context = {"taskId": record["id"], "sessionId": native.get("sessionId"),
               "subject": native.get("subject"), "generation": native.get("generation"),
               "operationId": native["stopOperationId"]}
    if any(not isinstance(v, str) or not v for v in context.values()):
        return False
    expected = {**context, "stopped": True, "processExitVerified": True,
                'descendantAbsenceVerified': True}
    receipt = native.get("stopReceipt")
    return (isinstance(receipt, dict) and receipt.get("stopped") is True
            and receipt.get("processExitVerified") is True
            and receipt.get('descendantAbsenceVerified') is True and receipt == expected)


class NativeSDKApprovalBridge:
    def __init__(self, task, client, *, subject, generation, session_id,
                 stop_and_verify=None, operation_timeout=5.0):
        if any(not isinstance(v, str) or not v or len(v) > 128
               or not re.fullmatch(r"[A-Za-z0-9_.@:-]+", v)
               for v in (subject, generation, session_id)):
            raise ValueError("INVALID_NATIVE_SDK_IDENTITY")
        if (type(operation_timeout) not in (int, float)
                or not 0 < operation_timeout <= 5):
            raise ValueError("INVALID_NATIVE_OPERATION_TIMEOUT")
        self.task, self.client = task, client
        self.subject, self.generation, self.session_id = subject, generation, session_id
        self.stop_and_verify = stop_and_verify
        self.operation_timeout = operation_timeout
        self._stop_call = None
        self._decision_settled = threading.Event()
        self._decision_settled.set()
        with task.persistence_lock:
            if task.request["runtime"] != "sdk" or task.state != "running":
                raise ValueError("NATIVE_SDK_TASK_NOT_RUNNING")
            if getattr(task, "native_sdk", None) is not None:
                raise ValueError("NATIVE_SDK_ALREADY_BOUND")
            # OpenShell needs its protected worker adapter; no local substitute.
            if task.request.get("backend", "private") != "private":
                raise ValueError("NATIVE_SDK_BACKEND_NOT_BOUND")
            task.native_sdk = {"subject": subject, "generation": generation,
                               "taskId": task.id, "project": task.request["project"],
                               "correlationId": task.correlation_id,
                               "sessionId": session_id, "phase": "running",
                               "pending": None, "usedCallIds": []}
            task.save()
            task.official_sdk_bridge = self

    def _current(self, subject, generation):
        state = self.task.native_sdk
        if (subject != self.subject or generation != self.generation
                or not state or state["subject"] != subject
                or state["generation"] != generation
                or state["sessionId"] != self.session_id
                or state["taskId"] != self.task.id
                or state["project"] != self.task.request["project"]
                or state["correlationId"] != self.task.correlation_id):
            raise ValueError("STALE_OR_FOREIGN_NATIVE_SDK_IDENTITY")
        return state

    def receive(self, request):
        """Receive only the pinned native approval/request wire shape.

        An absent callId cannot safely identify one operation, even if allowed
        by the upstream optional-field type. Such a request is refused locally.
        """
        payload = request.payload
        if (request.method != "approval/request" or not isinstance(payload, dict)
                or set(payload) - {"sessionId", "toolName", "callId", "reason"}
                or payload.get("sessionId") != self.session_id
                or not isinstance(payload.get("toolName"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", payload["toolName"])
                or not isinstance(payload.get("callId"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", payload["callId"])
                or not isinstance(request.id, (str, int))
                or isinstance(request.id, bool) or not str(request.id)
                or len(str(request.id)) > 256
                or (payload.get("reason") is not None
                    and (not isinstance(payload["reason"], str)
                         or len(payload["reason"]) > 8192))):
            raise ValueError("INVALID_NATIVE_APPROVAL_REQUEST")
        with self.task.persistence_lock:
            state = self._current(self.subject, self.generation)
            if (self.task.state != "running" or state["phase"] != "running"
                    or state["pending"] is not None
                    or len(state["usedCallIds"]) >= 256
                    or payload["callId"] in state["usedCallIds"]):
                raise ValueError("NATIVE_APPROVAL_REPLAY_OR_FENCED")
            pending = {"approvalId": uuid.uuid4().hex, "requestId": request.id,
                       "callId": payload["callId"], "toolName": payload["toolName"],
                       "decision": None}
            # Do not persist arbitrary native reason text or tool arguments.
            state.update(phase="awaiting-approval", pending=pending)
            self.task.state = "awaiting_approval"
            self.task.save()
            self.task.emit("native_approval_required", {
                "approvalId": pending["approvalId"], "generation": self.generation,
                "sessionId": self.session_id, "toolName": pending["toolName"],
                "callId": pending["callId"]})
            return {"approvalId": pending["approvalId"], "generation": self.generation}

    def decide(self, *, subject, generation, approval_id, outcome):
        if not isinstance(outcome, str) or outcome not in {"allowed-once", "rejected", "cancelled"}:
            raise ValueError("INVALID_NATIVE_APPROVAL_OUTCOME")
        with self.task.persistence_lock:
            state = self._current(subject, generation)
            if outcome == "allowed-once" and self.task.request["writes"] is not True:
                raise ValueError("NATIVE_ESCALATION_NOT_ADMITTED_FOR_READ_ONLY_TASK")
            pending = state["pending"]
            if (state["phase"] != "awaiting-approval"
                    or self.task.state != "awaiting_approval" or not pending
                    or pending["approvalId"] != approval_id):
                raise ValueError("NATIVE_APPROVAL_REPLAY_OR_FENCED")
            pending["decision"] = outcome
            operation = uuid.uuid4().hex
            pending["decisionOperationId"] = operation
            state["phase"] = "decision-reserved"
            self._decision_settled.clear()
            self.task.save()  # Must persist before the external native response.
            request_id = pending["requestId"]
            call = _ReservedCall(lambda: self.client.respond(request_id, {"outcome": outcome}))
            # Starting is ordered with the reservation/fence, but the external
            # call NEVER holds the journal lock. Cancellation can stop the same
            # native process even when its response pipe is blocked.
            try: call.thread.start()
            except Exception:
                state["phase"] = "decision-uncertain"
                self.task.state = "interrupted"
                self.task.save()
                self._decision_settled.set()
                raise
        try:
            call.result(self.operation_timeout)
        except BaseException:
            with self.task.persistence_lock:
                state = self._current(subject, generation)
                if (state["phase"] == "decision-reserved" and state["pending"]
                        and state["pending"].get("decisionOperationId") == operation):
                    state["phase"] = "decision-uncertain"
                    self.task.state = "interrupted"
                    self.task.save()
            self._decision_settled.set()
            raise
        with self.task.persistence_lock:
            state = self._current(subject, generation)
            pending = state["pending"]
            if (state["phase"] != "decision-reserved" or not pending
                    or pending.get("decisionOperationId") != operation):
                # A late response never reopens a cancelled/fenced generation.
                self._decision_settled.set()
                raise ValueError("NATIVE_DECISION_COMPLETED_AFTER_FENCE")
            state["usedCallIds"].append(pending["callId"])
            state.update(phase="running", pending=None)
            self.task.state = "running"
            self.task.save()
            self._decision_settled.set()
            self.task.emit("native_approval_decision", {
                "approvalId": approval_id, "outcome": outcome,
                "generation": generation})

    def wait_decision_settlement(self, timeout):
        """Internal ordering signal only; never a native completion/exit proof."""
        return self._decision_settled.wait(timeout)

    def fence(self):
        """Fence the native session before process cancellation; never replay."""
        with self.task.persistence_lock:
            state = self._current(self.subject, self.generation)
            if state["phase"] == "stopped" or state.get("stopOperationId"):
                return False
            state["phase"] = "fenced"
            self._decision_settled.set()
            self.task.save()
            return True

    def cancel(self):
        """Require protected native process-exit proof, not client.close alone."""
        return self._retire("cancelled")

    def finalize(self, terminal_state):
        """Natural completion/failure also retires the exact native process."""
        if terminal_state not in {"completed", "failed"}:
            raise ValueError("INVALID_NATIVE_TERMINAL_STATE")
        return self._retire(terminal_state)

    def _retire(self, terminal_state):
        with self.task.persistence_lock:
            state = self._current(self.subject, self.generation)
            if state["phase"] == "stopped": return False
            if state.get("stopOperationId"):
                # A concurrent cancel supersedes a successful-finalization
                # intent, but never starts a second stop or replays an uncertain one.
                if terminal_state == "cancelled":
                    state["desiredTerminalState"] = "cancelled"
                    self.task.save()
                return False
            if terminal_state == "completed" and (state["phase"] != "running"
                                                    or state["pending"] is not None):
                terminal_state = "failed"
            state["phase"] = "fenced"
            self._decision_settled.set()
            self.task.state = "interrupted"
            self.task.save()
            if self.stop_and_verify is None:
                return False
            operation = uuid.uuid4().hex
            state.update(phase="stop-reserved", stopOperationId=operation,
                         desiredTerminalState=terminal_state)
            self.task.state = "cancelling" if terminal_state == "cancelled" else "finalizing"
            self.task.save()
            context = {"taskId": self.task.id, "sessionId": self.session_id,
                       "subject": self.subject, "generation": self.generation,
                       "operationId": operation}
            self._stop_call = _ReservedCall(lambda: self.stop_and_verify(dict(context)))
            try: self._stop_call.thread.start()
            except Exception:
                state["phase"] = "stop-uncertain"
                self.task.state = "interrupted"
                self.task.save()
                return False
        try:
            receipt = self._stop_call.result(self.operation_timeout)
        except BaseException:
            with self.task.persistence_lock:
                state = self._current(self.subject, self.generation)
                if state.get("stopOperationId") == operation and state["phase"] != "stopped":
                    state["phase"] = "stop-uncertain"
                    self.task.state = "interrupted"
                    self.task.save()
            return False
        return self._accept_stop(receipt, operation)

    def resolve_stop(self):
        """Read only the SAME in-flight call's result, without resubmission.

        After broker restart the handle is lost; protected read-only native
        reconciliation is still required. Saved intent is never an exit proof.
        """
        with self.task.persistence_lock:
            state = self._current(self.subject, self.generation)
            if (not self._stop_call or not self._stop_call.done.is_set()
                    or state["phase"] not in {"stop-reserved", "stop-uncertain"}):
                return False
            operation = state["stopOperationId"]
        try: receipt = self._stop_call.result(0)
        except BaseException: return False
        return self._accept_stop(receipt, operation)

    def _accept_stop(self, receipt, operation):
        with self.task.persistence_lock:
            state = self._current(self.subject, self.generation)
            if state.get("stopOperationId") != operation or state["phase"] == "stopped":
                return False
            context = {"taskId": self.task.id, "sessionId": self.session_id,
                       "subject": self.subject, "generation": self.generation,
                       "operationId": operation}
            if (not isinstance(receipt, dict)
                    or any(receipt.get(k) != v for k, v in context.items())
                    or receipt.get("stopped") is not True
                    or receipt.get("processExitVerified") is not True
                    or receipt.get('descendantAbsenceVerified') is not True):
                state["phase"] = "stop-uncertain"
                self.task.state = "interrupted"
                self.task.save()
                return False
            lifecycle_failed=bool(state.get('postStopLifecycleFailure'))
            state["phase"] = "post-stop-lifecycle-uncertain" if lifecycle_failed else "stopped"
            # Persist only the checked identity/proof fields, never arbitrary
            # callback output, so recovery can distinguish proof from a label.
            state["stopReceipt"] = {**context, "stopped": True,
                                    "processExitVerified": True, 'descendantAbsenceVerified': True}
            self.task.state = ('interrupted' if lifecycle_failed else
                ('finalizing' if state.get('guardLifecyclePending') else state["desiredTerminalState"]))
            self.task.save()
            self.task.emit("state", {"state": self.task.state, "nativeExitVerified": True})
            return not lifecycle_failed
