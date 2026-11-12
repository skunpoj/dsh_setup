"""Official SDK session control; no helper substitution or automatic activation.

Server configuration supplies the qualified runtime scope and existing model
guard. This runner owns no provider credential and never installs a package.
The protected scope must start, identify, stop and reap the exact native process
and its descendants. Source tests cannot qualify that external implementation.
"""
import importlib.metadata
from contextlib import contextmanager
import glob
import os
from pathlib import Path
import re
import threading
import time
import uuid

from scripts.official_sdk_approval import NativeSDKApprovalBridge, _ReservedCall, verified_terminal_stop
from scripts.official_sdk_task import guarded_endpoint
from scripts.official_sdk_package_admission import verify_sdk_admission
from scripts.official_sdk_control_peer import SDKControlPeer


SDK_VERSION = "0.2.2a2"
MODEL = "deepseek-v4.1-flash"
# The matched SDK pair is installed ONLY in the SDK venv (Dockerfile.sdk-test), while the qualification broker runs under the system python3.
# This parent module must not import the SDK or spawn a process (tests/test_official_sdk_isolation.py), so the version is read from the
# dist-info METADATA of that venv's site-packages (a file read), never by running its interpreter.
SDK_SITE_PACKAGES = "/opt/dsh/deepagents/lib/python3*/site-packages"
_DISTRIBUTION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_VERSION_TEXT = re.compile(r"[0-9][0-9A-Za-z.+!_-]{0,63}")


def sdk_distribution_version(name):
    """Exact installed version of a distribution: this interpreter first, then the SDK venv's site-packages.

    A distribution found nowhere, or found more than once in the SDK venv, still raises importlib.metadata.PackageNotFoundError and the
    caller still compares the result with the exact pinned version: nothing is relaxed."""
    if not isinstance(name, str) or not _DISTRIBUTION_NAME.fullmatch(name):
        raise ValueError("INVALID_DISTRIBUTION_NAME")
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        pass
    found = [d for site in sorted(glob.glob(SDK_SITE_PACKAGES)) if os.path.isdir(site)
             for d in importlib.metadata.distributions(name=name, path=[site])]
    if len(found) != 1:
        raise importlib.metadata.PackageNotFoundError(name)
    version = found[0].version
    if not isinstance(version, str) or not _VERSION_TEXT.fullmatch(version):
        raise importlib.metadata.PackageNotFoundError(name)
    return version


class OfficialSDKSessionRunner:
    def __init__(self, *, subject, generation, guard_factory, runtime_scope,
                 harness_factory=None, version=sdk_distribution_version,
                 admission_check=verify_sdk_admission,
                 operation_timeout=5.0, workspace_root="/workspace", banking_guard_factory=None):
        if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", value)
               for value in (subject, generation)):
            raise ValueError("INVALID_NATIVE_SERVER_IDENTITY")
        if runtime_scope is None or getattr(runtime_scope, "qualified", False) is not True:
            raise ValueError("QUALIFIED_NATIVE_RUNTIME_SCOPE_REQUIRED")
        if not callable(guard_factory): raise ValueError("EXISTING_MODEL_GUARD_REQUIRED")
        for method in ("preflight", "start", "stop_and_verify", "inspect_exit"):
            if not callable(getattr(runtime_scope, method, None)):
                raise ValueError("NATIVE_SCOPE_LIFECYCLE_REQUIRED")
        if type(operation_timeout) not in (int, float) or not 0 < operation_timeout <= 5:
            raise ValueError("INVALID_NATIVE_OPERATION_TIMEOUT")
        self.subject, self.generation = subject, generation
        if banking_guard_factory is not None and not callable(banking_guard_factory):
            raise ValueError("EXPLICIT_BANKING_SDK_GUARD_FACTORY_REQUIRED")
        self.banking_guard_factory = banking_guard_factory
        self.guard_factory, self.scope = guard_factory, runtime_scope
        self.harness_factory, self.version = harness_factory, version
        self.admission_check = admission_check
        self.operation_timeout = operation_timeout
        self.workspace_root = Path(workspace_root).resolve(strict=True)
        self.recovery_calls = {}

    def fresh_admission(self):
        # Read protected bytes on EVERY admission/UI read. Version labels and
        # an earlier scope flag cannot qualify a repacked or revoked package.
        package = self.admission_check()
        state = self.scope.admission_state(self.subject, self.generation)
        if (self.scope.qualified is not True or not isinstance(state, dict)
                or state.get("admitted") is not True
                or state.get("subject") != self.subject or state.get("generation") != self.generation
                or state.get("packageAdmissionSha256") != package["admissionSha256"]
                or state.get("isolatedControl") is not True
                or state.get("brokerCredentialMounts") is not False
                or not (self.banking_guard_factory is not None and "expiresAt" in state and state["expiresAt"] is None or type(state.get("expiresAt")) in (int,float) and time.time() < state["expiresAt"] <= time.time()+300)):
            raise ValueError("FRESH_ISOLATED_SDK_ADMISSION_REQUIRED")
        return package

    @property
    def qualified(self):
        try:
            self.fresh_admission()
            return True
        except Exception:
            return False

    def recover_task(self, subject, task):
        """Inspect the old session only; never start/resume a model or process.

        A still-running native session remains fenced and needs a separately
        qualified exact-stop action. Absence alone is not an exit receipt.
        """
        if subject != self.subject: raise ValueError("FOREIGN_NATIVE_SDK_SUBJECT")
        inspect_exit = getattr(self.scope, "inspect_exit", None)
        if not callable(inspect_exit): raise ValueError("NATIVE_RECONCILIATION_UNAVAILABLE")
        with task.persistence_lock:
            state = task.native_sdk
            if (not isinstance(state, dict) or state.get("subject") != subject
                    or state.get("taskId") != task.id
                    or state.get("project") != task.request["project"]
                    or state.get("correlationId") != task.correlation_id):
                raise ValueError("FOREIGN_NATIVE_RECOVERY_BINDING")
            if state.get('postStopLifecycleFailure') or state.get('guardLifecyclePending'):
                # A saved physical exit cannot cure failed guard/accounting
                # teardown. Never restart or manufacture accepted completion.
                task.state='interrupted';task.save()
                return False
            if state["phase"] == "stopped":
                verified = verified_terminal_stop({"id": task.id, "state": task.state,
                    "project": task.request["project"], "correlationId": task.correlation_id,
                    "nativeSdk": state})
                if not verified:
                    state["phase"] = "recovery-unverified"; task.state = "interrupted"; task.save()
                return verified
            if task.official_sdk_bridge is not None:
                return False  # In-memory observers/session still own this task.
            if task.id in self.recovery_calls:
                call, context = self.recovery_calls[task.id]
            else:
                if not re.fullmatch(r"[a-f0-9]{32}", str(state.get("launchOperationId", ""))):
                    raise ValueError("NATIVE_RECOVERY_LAUNCH_ID_REQUIRED")
                context = {"subject": subject, "generation": state["generation"],
                    "taskId": task.id, "sessionId": state["sessionId"],
                    "project": task.request["project"], "correlationId": task.correlation_id,
                    "launchOperationId": state["launchOperationId"],
                    "runtimeIdentity": state.get("runtimeIdentity")}
                state["phase"] = "recovery-read-reserved"
                task.state = "interrupted"; task.save()
                call = _ReservedCall(lambda: inspect_exit(dict(context)))
                self.recovery_calls[task.id] = (call, context)
                call.thread.start()
        try: receipt = call.result(self.operation_timeout)
        except BaseException:
            with task.persistence_lock:
                task.native_sdk["phase"] = "recovery-read-uncertain"; task.save()
            return False
        with task.persistence_lock:
            state = task.native_sdk
            if (state.get("subject") != context["subject"]
                    or state.get("generation") != context["generation"]
                    or state.get("launchOperationId") != context["launchOperationId"]
                    or task.request["project"] != context["project"]
                    or task.correlation_id != context["correlationId"]):
                raise ValueError("RECOVERY_BINDING_CHANGED")
            operation = receipt.get("operationId") if isinstance(receipt, dict) else None
            if (not isinstance(receipt, dict)
                    or any(receipt.get(k) != v for k, v in context.items())
                    or receipt.get("stopped") is not True
                    or receipt.get("processExitVerified") is not True
                    or receipt.get('descendantAbsenceVerified') is not True
                    or receipt.get("launchFenced") is not True
                    or (context["runtimeIdentity"] is None and receipt.get("neverStarted") is not True)
                    or not isinstance(operation, str) or not re.fullmatch(r"[a-f0-9]{32}", operation)
                    or (state.get("stopOperationId") and state["stopOperationId"] != operation)):
                state["phase"] = "recovery-unverified"; task.save()
                return False
            terminal = state.get("desiredTerminalState", "failed")
            if terminal not in {"completed", "failed", "cancelled"}: terminal = "failed"
            state.update(phase="stopped", stopOperationId=operation,
                stopReceipt={"taskId": task.id, "sessionId": state["sessionId"],
                    "subject": subject, "generation": state["generation"],
                    "operationId": operation, "stopped": True, "processExitVerified": True,
                    'descendantAbsenceVerified': True})
            task.state = terminal; task.save()
            task.emit("state", {"state": terminal, "nativeRecoveryExitVerified": True})
            return True

    def _guard_lifecycle_failed(self,task):
        with task.persistence_lock:
            if task.native_sdk is not None:
                task.native_sdk['postStopLifecycleFailure']=True
                if task.native_sdk.get('phase')=='stopped':
                    task.native_sdk['phase']='post-stop-lifecycle-uncertain'
            task.state='interrupted';task.save()

    def _guard_lifecycle_succeeded(self,task):
        with task.persistence_lock:
            native=task.native_sdk
            if native is None or not native.get('guardLifecyclePending'):return
            native['guardLifecyclePending']=False
            if native.get('phase')=='stopped' and not native.get('postStopLifecycleFailure'):
                desired=native.get('desiredTerminalState')
                record=dict(id=task.id,project=task.request['project'],correlationId=task.correlation_id,
                    state=desired,nativeSdk=native)
                task.state=desired if verified_terminal_stop(record) else 'interrupted'
            task.save()
            task.emit('state',dict(state=task.state,guardContextExited=True))

    @contextmanager
    def _guard_lifecycle(self,task):
        entered=False;body_error=None
        try:
            # Separate server-composed banking adapter; native qualification's
            # existing guard/cap is unchanged when it is absent.
            factory = self.banking_guard_factory or self.guard_factory
            with factory(task) as guard:
                entered=True
                try:yield guard
                except BaseException as error:
                    body_error=error
                    raise
        except BaseException as error:
            # A body exception rethrown unchanged is NOT a guard teardown
            # failure (in particular, preserve an already verified cancel).
            if entered:
                if error is not body_error:self._guard_lifecycle_failed(task)
                else:self._guard_lifecycle_succeeded(task)
            raise
        if body_error is not None:
            self._guard_lifecycle_failed(task)
            raise body_error  # A guard cannot silently suppress a task fault.
        self._guard_lifecycle_succeeded(task)

    def run_task(self, subject, task):
        if subject != self.subject: raise ValueError("FOREIGN_NATIVE_SDK_SUBJECT")
        if (not re.fullmatch(r"[a-f0-9]{32}", task.id)
                or not re.fullmatch(r"[a-f0-9]{32}", task.correlation_id)):
            raise ValueError("INVALID_NATIVE_SDK_TASK_IDENTITY")
        if task.request["runtime"] != "sdk" or task.request.get("backend", "private") != "private":
            raise ValueError("INVALID_NATIVE_SDK_TASK")
        if task.request.get("handoffRuntime"):
            # Stage-specific native session bindings are a separate contract.
            # Never ignore a requested handoff and claim that task completed.
            raise ValueError("NATIVE_SDK_HANDOFF_NOT_YET_QUALIFIED")
        if not isinstance(task.request.get("prompt"), str) or not 1 <= len(task.request["prompt"]) <= 65536:
            raise ValueError("INVALID_NATIVE_SDK_PROMPT")
        task.finished.clear()
        harness = bridge = subscription = None
        final_output = None
        readers = []
        reader_stop = threading.Event()
        protocol_failed = threading.Event()
        session = task.id
        context = {"subject": self.subject, "generation": self.generation,
                   "taskId": task.id, "sessionId": session,
                   "project": task.request["project"], "correlationId": task.correlation_id}
        try:
            if self.scope.qualified is not True:
                raise ValueError("NATIVE_RUNTIME_SCOPE_REVOKED")
            package = self.fresh_admission()
            with task.persistence_lock:
                # A DELETE that arrives while the task is still queued is handled by the generic Task.cancel (no bridge, no process yet) and leaves
                # state cancelling/cancelled. The runner must never overwrite that fence: it neither starts a worker nor re-opens the task.
                if task.state in {"cancelling", "cancelled"}:
                    task.state = "cancelled"; task.save()
                    return None
                task.state = "running"; task.runner_owned = True; task.save()
            # This call is a protected no-spawn admission check, not permission
            # to discover credentials, grant privileges or create a worker.
            admission = self.scope.preflight(dict(context))
            if (not isinstance(admission, dict) or admission.get("admitted") is not True
                    or any(admission.get(k) != v for k, v in context.items())
                    or admission.get("packageAdmissionSha256") != package["admissionSha256"]):
                raise ValueError("NATIVE_SCOPE_PREFLIGHT_REFUSED")
            for distribution in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin"):
                if self.version(distribution) != SDK_VERSION:
                    raise ValueError("MATCHED_APPROVAL_CAPABLE_SDK_PAIR_REQUIRED")
            project = (self.workspace_root / task.request["project"]).resolve(strict=True)
            if not project.is_relative_to(self.workspace_root) or not project.is_dir():
                raise ValueError("BROKER_RESOLVED_PROJECT_REQUIRED")
            home = task.directory / "official-sdk-home"
            home.mkdir(mode=0o700, exist_ok=False)
            with self._guard_lifecycle(task) as guard:
                endpoint = guarded_endpoint(guard.base_url)
                if getattr(guard, "task_id", None) != task.id or getattr(guard, "correlation_id", None) != task.correlation_id:
                    raise ValueError("NATIVE_MODEL_GUARD_BINDING_MISMATCH")
                if (type(getattr(guard, "temperature", None)) not in (int, float)
                        or guard.temperature != 0):
                    raise ValueError("NATIVE_GUARD_TEMPERATURE_POLICY_REQUIRED")
                # Passed only to an isolated child. Do not copy or enumerate
                # broker environment names or values into its private pipe.
                environment = dict(PATH="/usr/local/bin:/usr/bin:/bin", LANG="C.UTF-8",
                    HOME=str(home), PYTHONDONTWRITEBYTECODE="1", OTEL_SDK_DISABLED="true",
                    DO_NOT_TRACK="1", LANGSMITH_TRACING="false",
                    DSH_UNATTENDED_TASK=task.id, DSH_CORRELATION_ID=task.correlation_id,
                    DSH_GUARDED_MODEL_BASE_URL=endpoint)
                if self.banking_guard_factory is not None:environment['TMPDIR']='/tmp/user'
                options = dict(provider="deepseek-official", model=MODEL,
                    profile="sdk", cwd=str(project), runtime_cwd=str(project),
                    dsh_bin="/usr/local/bin/dsh-official-sdk-runtime",
                    dsh_home=str(home), approval_requests=True,
                    base_url=endpoint, api_key="local-guard-placeholder",
                    max_tokens=8192 if self.banking_guard_factory is not None else 256, initialize_timeout_seconds=15,
                    request_timeout_seconds=300 if self.banking_guard_factory is not None else 120, shutdown_timeout_seconds=2,
                    env=environment)
                if self.banking_guard_factory is not None:options['patches']=['/opt/dsh/config/banking-sdk-tool-policy.patch.yml']
                if self.harness_factory is not None:
                    harness = self.harness_factory(**options)  # Explicit synthetic source-test seam.
                else:
                    harness = SDKControlPeer(runtime_scope=self.scope,
                        binding={**context, "packageAdmissionSha256": package["admissionSha256"]}, options=options)

                def verified_stop(stop_context):
                    with task.persistence_lock:
                        launch_id = task.native_sdk["launchOperationId"]
                    receipt = self.scope.stop_and_verify(harness, {**stop_context,
                        "launchOperationId": launch_id, "project": task.request["project"],
                        "correlationId": task.correlation_id})
                    with task.persistence_lock:
                        identity = task.native_sdk.get("runtimeIdentity")
                        if (not isinstance(receipt, dict) or receipt.get("launchOperationId") != launch_id
                                or receipt.get("launchFenced") is not True):
                            raise ValueError("NATIVE_SCOPE_LAUNCH_FENCE_UNVERIFIED")
                        returned = receipt.get("runtimeIdentity")
                        if identity is None:
                            if isinstance(returned, dict) and returned:
                                task.native_sdk["runtimeIdentity"] = returned
                            elif returned is None and receipt.get("neverStarted") is True:
                                task.native_sdk["nativeNeverStarted"] = True
                            else: raise ValueError("NATIVE_SCOPE_STOP_IDENTITY_MISMATCH")
                            task.save()
                        elif returned != identity:
                            raise ValueError("NATIVE_SCOPE_STOP_IDENTITY_MISMATCH")
                    return receipt

                bridge = NativeSDKApprovalBridge(task, harness.client,
                    subject=self.subject, generation=self.generation, session_id=session,
                    stop_and_verify=verified_stop, operation_timeout=self.operation_timeout)
                with task.persistence_lock:
                    launch = uuid.uuid4().hex
                    task.native_sdk.update(phase="launch-reserved", launchOperationId=launch,
                                           managedSession=True,guardLifecyclePending=True)
                    task.save()
                if task.cancel_pending:
                    task.cancel_pending = False
                    task.cancel()                # the bridge exists now: the normal native cancel (fence + scope stop receipt, neverStarted when nothing started)
                start_context = {**context, "operationId": launch}
                start = _ReservedCall(lambda: self.scope.start(harness, dict(start_context)))
                start.thread.start()
                receipt = start.result(self.operation_timeout)
                with task.persistence_lock:
                    if (not isinstance(receipt, dict) or receipt.get("started") is not True
                            or any(receipt.get(k) != v for k, v in start_context.items())
                            or not isinstance(receipt.get("runtimeIdentity"), dict)
                            or not receipt["runtimeIdentity"]):
                        raise ValueError("NATIVE_SCOPE_START_IDENTITY_MISMATCH")
                    if task.native_sdk["phase"] != "launch-reserved" or task.state != "running":
                        raise ValueError("NATIVE_START_COMPLETED_AFTER_FENCE")
                    task.native_sdk.update(phase="running", runtimeIdentity=receipt["runtimeIdentity"])
                    task.save()

                def approvals():
                    try:
                        while not reader_stop.is_set():
                            request = harness.client.next_request()
                            if reader_stop.is_set(): break
                            bridge.receive(request)
                    except BaseException:
                        if not reader_stop.is_set():
                            protocol_failed.set()
                            bridge.finalize("failed")

                capture_drained=threading.Event()
                def notifications():
                    try:
                        while not reader_stop.is_set():
                            event = subscription.next()
                            if reader_stop.is_set(): break
                            payload = event.payload
                            if not isinstance(payload, dict) or payload.get("sessionId") != session:
                                raise ValueError("FOREIGN_NATIVE_NOTIFICATION")
                            capture=getattr(task,'private_capture',None)
                            if capture is not None:
                                if event.method=='banking.capture.complete':
                                    if payload!={'sessionId':session,'complete':True}:raise ValueError('SDK_CAPTURE_BARRIER_REFUSED')
                                    capture.drain_verified=True;capture_drained.set();continue
                                capture.notification(event.method,payload)
                            with task.persistence_lock:
                                if task.native_sdk["phase"] not in {"running", "awaiting-approval", "decision-reserved"}:
                                    continue
                                # No raw prompts, tool arguments, provider payloads
                                # or native reason text enter this progress log.
                                task.emit("sdk_progress", {"state": task.state,
                                    "method": event.method})
                    except BaseException:
                        if not reader_stop.is_set():
                            protocol_failed.set()
                            bridge.finalize("failed")

                subscription = harness.client.subscribe_session_notifications(session)
                for callback in (approvals, notifications):
                    reader = threading.Thread(target=callback, daemon=True)
                    readers.append(reader); reader.start()
                result = harness.run(task.request["prompt"], session_id=session)
                capture=getattr(task,'private_capture',None)
                if capture is not None:
                    if isinstance(result.final_response,str):capture.final_response(result.final_response)
                    if not capture_drained.wait(self.operation_timeout):raise ValueError('SDK_VISIBLE_CAPTURE_DRAIN_UNVERIFIED')
                if (protocol_failed.is_set() or result.finish_reason != "completed"
                        or not isinstance(result.final_response, str) or not result.final_response.strip()):
                    raise ValueError("NATIVE_SDK_TURN_NOT_COMPLETED")
                if len(result.final_response.encode("utf-8")) > 262144:
                    raise ValueError("NATIVE_SDK_RESULT_TOO_LARGE")
                final_output = result.final_response
                with task.persistence_lock:
                    settling = task.native_sdk["phase"] == "decision-reserved"
                if settling and not bridge.wait_decision_settlement(self.operation_timeout):
                    raise ValueError("NATIVE_SDK_DECISION_STILL_UNCERTAIN")
                with task.persistence_lock:
                    if task.state != "running" or task.native_sdk["phase"] != "running":
                        raise ValueError("NATIVE_SDK_RESULT_AFTER_FENCE")
                    # Captured final response remains private to the existing
                    # authenticated Task event stream; no extra result store.
                    task.emit("output", {"runtime": "sdk", "text": result.final_response[:16384]})
                reader_stop.set()
                bridge.finalize("completed")
        except BaseException as error:
            reader_stop.set()
            if bridge is not None:
                bridge.finalize("failed")
            else:
                with task.persistence_lock:
                    task.state = "failed"; task.save()
            detail = {"state": task.state, "error": type(error).__name__}
            if isinstance(error, ValueError) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,80}", str(error)):
                detail["code"] = str(error)             # fixed refusal codes only (no paths, no payloads): says WHICH check refused
            if isinstance(error, importlib.metadata.PackageNotFoundError):
                missing = str(error.args[0]) if error.args else ""       # str(error) is a sentence on newer Pythons; args[0] is the name
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", missing):
                    detail["distribution"] = missing   # which installed distribution was missing (a package name, nothing else)
            task.emit("state", detail)
        finally:
            reader_stop.set()
            if subscription is not None: subscription.close()
            # The protected scope closes/reaps the SDK runtime as part of its
            # exact stop receipt. A close() call alone is never an exit proof.
            for reader in readers: reader.join(timeout=1)
            if any(reader.is_alive() for reader in readers):
                with task.persistence_lock:
                    if task.native_sdk is not None:
                        task.native_sdk["phase"] = "observer-cleanup-uncertain"
                        task.state = "interrupted"
                        task.save()
            capture=getattr(task,'private_capture',None)
            if capture is not None and capture.failed:task.state='interrupted'
            if capture is not None and not capture.closed and not capture.failed and task.state=='completed':
                try:
                    from scripts.banking_private_capture import sdk_terminal,agent_inventory
                    capture.finish(terminal=sdk_terminal(task),artifacts=agent_inventory(project))
                except Exception:task.state='interrupted'
            task.save(); task.finished.set()
        with task.persistence_lock:
            record = dict(id=task.id, project=task.request["project"],
                correlationId=task.correlation_id, state=task.state, nativeSdk=task.native_sdk)
            if task.state == "completed" and verified_terminal_stop(record):
                return final_output  # Private in-memory handoff, not progress-log text.
        return None
