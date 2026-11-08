"""Typed OpenShell state attached to the existing broker Task journal.

The injected transport must be provided by the qualified image. This module
does not create Kubernetes resources, retrieve secrets, or enable a backend.
"""
import re
import threading
import time
import uuid


class OpenShellBinding:
    KEYS = frozenset({"subject", "generation", "taskId", "project", "bindingId", "workerUID"})

    def __init__(self, task, transport):
        self.task = task
        self.transport = transport
        self.lock = threading.RLock()

    def _persist(self, state):
        self.task.openshell = state
        self.task.save()

    def _current(self, context, allow_fenced=False):
        if not isinstance(context, dict) or set(context) != self.KEYS:
            raise ValueError("INVALID_BINDING_CONTEXT")
        state = getattr(self.task, "openshell", None)
        if not state or any(context[k] != state[k] for k in self.KEYS):
            raise ValueError("STALE_OR_FOREIGN_BINDING")
        if not isinstance(state.get("workerUID"),str) or not state["workerUID"]:
            raise ValueError("ALLOCATION_IDENTITY_UNCERTAIN")
        if not allow_fenced and (state["fenced"] or state["expiresAt"] <= time.time()):
            raise ValueError("FENCED_OR_EXPIRED_BINDING")
        return state

    def bind(self, context, expires_at):
        with self.lock:
            if not isinstance(context, dict) or set(context) != self.KEYS:
                raise ValueError("INVALID_BINDING_CONTEXT")
            if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", v)
                   for k, v in context.items() if k != "project"):
                raise ValueError("INVALID_BINDING_ID")
            if context["taskId"] != self.task.id or context["project"] != self.task.request["project"]:
                raise ValueError("TASK_PROJECT_MISMATCH")
            if not isinstance(expires_at, (float, int)) or not time.time() < expires_at <= time.time() + 300:
                raise ValueError("INVALID_BINDING_EXPIRY")
            if getattr(self.task, "openshell", None):
                raise ValueError("BINDING_ALREADY_EXISTS")
            self._persist({**context, "expiresAt": expires_at, "fenced": False,
                           "revoked": False, "phase": "bound", "operationId": None})
            return dict(self.task.openshell)

    def resolve(self, context):
        with self.lock:
            return dict(self._current(context))

    def dispatch(self, context, operation_id):
        with self.lock:
            state = self._current(context)
            if state["phase"] != "bound" or not re.fullmatch(r"[a-f0-9]{32}", operation_id):
                raise ValueError("DISPATCH_REPLAY_OR_INVALID_OPERATION")
            # Reserve durably before transport. An uncertain dispatch is never replayed.
            self._persist({**state, "phase": "dispatch-reserved", "operationId": operation_id})
            receipt = self.transport.dispatch(dict(context), operation_id)
            if not isinstance(receipt, dict) or any(receipt.get(k) != context[k] for k in self.KEYS):
                raise ValueError("DISPATCH_IDENTITY_MISMATCH")
            if receipt.get("operationId") != operation_id or receipt.get("nativeRequired") is not True or receipt.get("unrestrictedFallback") is not False:
                raise ValueError("DISPATCH_RECEIPT_INVALID")
            self._persist({**self.task.openshell, "phase": "running"})
            return receipt
    def revoke(self, context):
        with self.lock:
            state = self._current(context, allow_fenced=True)
            self._persist({**state, "revoked": True, "fenced": True})
            return {"bindingId": state["bindingId"], "revoked": True, "fenced": True}

    def stop(self, context, operation_id):
        with self.lock:
            state = self._current(context, allow_fenced=True)
            if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
                raise ValueError("INVALID_STOP_OPERATION")
            if state.get("stopOperationId") not in (None, operation_id):
                raise ValueError("STOP_OPERATION_CHANGED")
            if state["phase"] == "stopped":
                return {"workerUID": context["workerUID"], "absent": True, "operationId": operation_id}
            self._persist({**state, "revoked": True, "fenced": True,
                           "phase": "stop-reserved", "stopOperationId": operation_id})
            receipt = self.transport.stop_exact(dict(context), operation_id)
            if receipt != {"workerUID": context["workerUID"], "stopped": True, "operationId": operation_id}:
                raise ValueError("STOP_UNVERIFIED")
            receipt = self.transport.verify_absent(dict(context), operation_id)
            if receipt != {"workerUID": context["workerUID"], "absent": True, "operationId": operation_id}:
                raise ValueError("ABSENCE_UNVERIFIED")
            self._persist({**self.task.openshell, "phase": "stopped"})
            return receipt


class BrokerOpenShellService:
    """Use server-assigned workspace identity, never caller-supplied bindings.

    An admitted server injects this service and its protected transport. No
    environment switch alone enables it. Registry remains the sole Task owner.
    """
    def __init__(self, registry, subject, generation, transport, *, qualified=False, admission_expires_at=None):
        if not all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", v)
                   for v in (subject, generation)):
            raise ValueError("INVALID_SERVER_IDENTITY")
        self.registry, self.subject, self.generation = registry, subject, generation
        self.transport, self._qualified = transport, qualified
        self.admission_expires_at=admission_expires_at
        self.lock = threading.RLock()

    @property
    def qualified(self):
        return self._qualified and (self.admission_expires_at is None or time.time()<self.admission_expires_at)

    def operate(self, subject, task_id, operation, body):
        with self.lock:
            if not self._qualified:
                raise ValueError("OPENSHELL_NOT_QUALIFIED")
            if operation in {'bind','dispatch'} and not self.qualified:
                raise ValueError('NATIVE_ADMISSION_EXPIRED')
            if subject != self.subject:
                raise ValueError("FOREIGN_SUBJECT")
            task = self.registry.get(task_id)
            if task is None:
                raise ValueError("TASK_NOT_FOUND")
            if operation not in {"bind", "resolve", "dispatch", "revoke", "stop"}:
                raise ValueError("UNKNOWN_OPERATION")
            if body != {"approved": True}:
                raise ValueError("BOUND_APPROVAL_REQUIRED")
            binding = OpenShellBinding(task, self.transport)
            if operation == "bind":
                if task.state != "queued" or getattr(task, "openshell", None):
                    raise ValueError("TASK_NOT_BINDABLE")
                binding_id = uuid.uuid4().hex
                context = dict(subject=self.subject, generation=self.generation,
                               taskId=task.id, project=task.request["project"],
                               bindingId=binding_id)
                expires_at=min(time.time()+120,self.admission_expires_at or float('inf'))
                operation_id=uuid.uuid4().hex
                # Creation assigns the native worker UID. Reserve before making
                # that external call; never invent a UID in an inert preflight.
                binding._persist({**context,"workerUID":None,"expiresAt":expires_at,
                                  "phase":"allocation-reserved","fenced":True,
                                  "revoked":False,"operationId":None,
                                  "allocationOperationId":operation_id})
                worker=self.transport.allocate(dict(context),operation_id,expires_at)
                return self._accept_allocation(task,context,worker,operation_id)
            state = getattr(task, "openshell", None)
            if state is None:
                raise ValueError("BINDING_NOT_FOUND")
            context = {k: state[k] for k in OpenShellBinding.KEYS}
            if context["subject"] != self.subject or context["generation"] != self.generation:
                raise ValueError("STALE_SERVER_IDENTITY")
            if state["phase"] == "allocation-reserved":
                if operation != "resolve":
                    raise ValueError("ALLOCATION_IDENTITY_UNCERTAIN")
                # Lookup is read-only and must never create a replacement worker.
                allocation_context={k:v for k,v in context.items() if k != "workerUID"}
                worker=self.transport.lookup_allocation(dict(allocation_context),state["allocationOperationId"])
                return self._accept_allocation(task,allocation_context,worker,state["allocationOperationId"])
            if operation == "resolve":
                return binding.resolve(context)
            if operation == "dispatch":
                return binding.dispatch(context, uuid.uuid4().hex)
            if operation == "revoke":
                return binding.revoke(context)
            return binding.stop(context, state.get("stopOperationId") or uuid.uuid4().hex)

    def run_task(self, subject, task):
        """One or two native stages; clean each exact worker before advancing."""
        task.finished.clear()
        task.native_stages = getattr(task, "native_stages", [])
        task.execution_prompt = task.request.get("prompt", "")
        stage_runtimes = [task.request["runtime"]]
        if task.request.get("handoffRuntime"):
            stage_runtimes.append(task.request["handoffRuntime"])
        try:
            for stage_index, runtime in enumerate(stage_runtimes):
                with self.lock:
                    if task.state in {"cancelled", "cancelling"}:
                        return
                    if stage_index:
                        if not task.openshell or task.openshell["phase"] != "stopped":
                            raise ValueError("PREVIOUS_WORKER_NOT_ABSENT")
                        task.openshell = None
                    task.execution_stage = {
                        "index": stage_index, "runtime": runtime,
                        "correlationId": task.correlation_id if stage_index == 0 else uuid.uuid4().hex,
                    }
                    task.state = "queued"
                    task.save()
                    self.operate(subject, task.id, "bind", {"approved": True})
                with self.lock:
                    if task.state == "cancelled":
                        return
                    if task.state == "cancelling":
                        self.cancel_task(subject, task)
                        return
                    task.state = "running"
                    task.emit("state", {"state": task.state, "backend": "openshell", "runtime": runtime})
                    task.save()
                    receipt = self.operate(subject, task.id, "dispatch", {"approved": True})
                context = {k: task.openshell[k] for k in OpenShellBinding.KEYS}
                terminal = False
                exit_code = None
                captured = []
                captured_bytes = 0
                for event in self.transport.events(context, receipt["operationId"]):
                    if terminal:
                        raise ValueError("EVENT_AFTER_TERMINAL")
                    if task.state in {"cancelling", "cancelled"}:
                        return
                    if not isinstance(event, dict):
                        raise ValueError("INVALID_NATIVE_EVENT")
                    if event.get("type") == "output" and set(event) == {"type", "text"} and isinstance(event["text"], str):
                        text = event["text"][:16384]
                        task.emit("output", {"text": text, "runtime": runtime})
                        piece = text.encode("utf-8")[:max(0, 262144-captured_bytes)]
                        captured_bytes += len(piece)
                        captured.append(piece.decode("utf-8", errors="replace"))
                    elif (event.get("type") == "exit" and set(event) == {"type", "exitCode", "workerUID", "operationId"}
                          and type(event["exitCode"]) is int and event["workerUID"] == context["workerUID"]
                          and event["operationId"] == receipt["operationId"]):
                        terminal = True
                        exit_code = event["exitCode"]
                        task.state = "finalizing"
                        task.emit("state", {"state": task.state, "exitCode": exit_code, "backend": "openshell"})
                    else:
                        raise ValueError("INVALID_NATIVE_EVENT")
                if not terminal:
                    raise ValueError("NATIVE_RESULT_UNCERTAIN")
                if task.state in {"cancelled", "cancelling"}:
                    return
                self.operate(subject, task.id, "revoke", {"approved": True})
                cleanup = self.operate(subject, task.id, "stop", {"approved": True})
                if cleanup.get("absent") is not True:
                    raise ValueError("ABSENCE_UNVERIFIED")
                task.native_stages.append({
                    **task.execution_stage, "binding": dict(task.openshell), "exitCode": exit_code,
                })
                if exit_code != 0:
                    task.state = "interrupted" if exit_code == 75 else "failed"
                    task.emit("state", {"state": task.state, "exitCode": exit_code, "backend": "openshell"})
                    return
                if stage_index+1 < len(stage_runtimes):
                    instruction = task.request.get("handoffPrompt") or "Review the previous agent result and produce the final checked answer."
                    task.execution_prompt = instruction + "\n\nPrevious agent result:\n" + "".join(captured)
                    task.state = "handoff"
                    task.emit("handoff", {"from": runtime, "to": stage_runtimes[stage_index+1]})
                    task.save()
                else:
                    task.state = "completed"
                    task.emit("state", {"state": task.state, "exitCode": exit_code, "backend": "openshell"})
        except Exception as error:
            if task.state not in {"cancelled", "cancelling"}:
                task.state = "interrupted"
                task.emit("state", {"state": task.state, "error": type(error).__name__, "backend": "openshell"})
        finally:
            task.execution_prompt = None
            try:
                task.save()
            finally:
                task.finished.set()

    def cancel_task(self,subject,task):
        with self.lock:
            return self._cancel_task_locked(subject,task)

    def _cancel_task_locked(self,subject,task):
        task.state="cancelling";task.emit("state",{"state":task.state});task.save()
        try:
            self.operate(subject,task.id,"revoke",{"approved":True})
            receipt=self.operate(subject,task.id,"stop",{"approved":True})
            if receipt.get("absent") is not True:raise ValueError("ABSENCE_UNVERIFIED")
            task.state="cancelled";task.emit("state",{"state":task.state,"backend":"openshell"});task.save()
            return True
        except Exception as error:
            task.emit("state",{"state":"cancelling","error":"NATIVE_STOP_UNCERTAIN","errorType":type(error).__name__});task.save()
            return False

    def _accept_allocation(self,task,context,worker,operation_id):
        if (not isinstance(worker,dict) or set(worker) != set(context)|{"workerUID","operationId"}
            or any(worker.get(k)!=v for k,v in context.items())
            or worker.get("operationId")!=operation_id
            or not isinstance(worker.get("workerUID"),str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}",worker["workerUID"])):
            raise ValueError("INVALID_ALLOCATED_IDENTITY")
        if task.openshell["expiresAt"]<=time.time():
            # Preserve the recovered identity for exact cleanup, keep it fenced.
            task.openshell={**task.openshell,"workerUID":worker["workerUID"],"phase":"expired"}
        else:
            task.openshell={**task.openshell,"workerUID":worker["workerUID"],"phase":"bound","fenced":False}
        task.save()
        return dict(task.openshell)

    def recover_pending(self):
        """Fence/stop prior generations without recreating or replaying a task."""
        if not self._qualified:raise ValueError("OPENSHELL_NOT_QUALIFIED")
        results=[]
        for task in list(self.registry.tasks.values()):
            state=getattr(task,"openshell",None)
            if task.request.get("backend")!="openshell" or not state or state.get("phase")=="stopped":
                continue
            if state.get("subject")!=self.subject:raise ValueError("FOREIGN_RECOVERY_SUBJECT")
            task.state="cancelling";task.save()
            try:
                context={k:state[k] for k in OpenShellBinding.KEYS}
                if state["phase"]=="allocation-reserved":
                    allocation={k:v for k,v in context.items() if k!="workerUID"}
                    worker=self.transport.lookup_allocation(allocation,state["allocationOperationId"])
                    self._accept_allocation(task,allocation,worker,state["allocationOperationId"])
                    context={k:task.openshell[k] for k in OpenShellBinding.KEYS}
                binding=OpenShellBinding(task,self.transport)
                binding.revoke(context)
                receipt=binding.stop(context,task.openshell.get("stopOperationId") or uuid.uuid4().hex)
                task.state="interrupted";task.save()
                task.emit("recovery",{"workerUID":context["workerUID"],"absent":True,"modelReplay":False})
                results.append(receipt)
            except Exception:
                task.save()
                raise
        return results
