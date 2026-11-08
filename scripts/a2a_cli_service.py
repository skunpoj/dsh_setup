"""Private CLI execution through a separately qualified protected supervisor.

No direct Popen fallback: a launcher exit is not descendant-absence evidence.
"""
from scripts.agent_runtime_commands import command_for
import uuid


class ProtectedCLIService:
    def __init__(self, *, subject, supervisor, workspace_resolver):
        self.subject = subject
        self.supervisor = supervisor
        self.workspace_resolver = workspace_resolver

    @property
    def qualified(self):
        return (self.supervisor is not None and self.supervisor.qualified is True
                and self.supervisor.subject == self.subject)

    def run_task(self, subject, task):
        if not self.qualified or subject != self.subject:
            raise ValueError("A2A_CLI_SCOPE_NOT_QUALIFIED")
        if task.request["runtime"] not in {"claude", "deepagents"} or task.request.get("backend") != "private":
            raise ValueError("A2A_CLI_RUNTIME_REFUSED")
        project = self.workspace_resolver(task.request["project"])
        command = command_for(task.request["runtime"], task.request["prompt"],
            task.request["writes"], project, task.id)
        context = dict(subject=subject, stageId=task.id, correlationId=task.correlation_id,
            project=task.request["project"], runtime=task.request["runtime"])
        with task.persistence_lock:
            if task.state != "queued": raise ValueError("A2A_CLI_TASK_ALREADY_RESERVED")
            task.finished.clear()
            task.a2a_cli_context = dict(context)
            task.cli_service = self
            task.state = "running"; task.save()
        try:
            # Supervisor owns the exact child scope and authenticated control
            # channel. It must independently observe all descendants absent.
            result = self.supervisor.execute_once(dict(context), command, str(project))
            if (not isinstance(result, dict) or result.get("exitCode") != 0
                    or any(result.get(k) != v for k,v in context.items())
                    or result.get("stopped") is not True
                    or result.get("processExitVerified") is not True
                    or result.get("descendantAbsenceVerified") is not True
                    or not isinstance(result.get("scopeUid"), str) or not result["scopeUid"]
                    or not isinstance(result.get("output"), str) or not result["output"].strip()
                    or len(result["output"].encode("utf-8")) > 262144):
                raise ValueError("A2A_CLI_RESULT_UNVERIFIED")
            with task.persistence_lock:
                if task.state != "running": raise ValueError("A2A_CLI_RESULT_AFTER_FENCE")
                task.a2a_terminal_receipt = {**context, "stopped": True, "processExitVerified": True,
                    "descendantAbsenceVerified": True, "scopeUid": result["scopeUid"]}
                task.state = "completed"; task.save()
            return result["output"]
        except BaseException:
            with task.persistence_lock:
                if task.state != "cancelled": task.state = "interrupted"
                task.save()
            raise
        finally:
            task.finished.set()

    def cancel_task(self, subject, task):
        if subject != self.subject or not self.qualified:
            raise ValueError("A2A_CLI_SCOPE_NOT_QUALIFIED")
        with task.persistence_lock:
            context = getattr(task, "a2a_cli_context", None)
            if (task.state not in {"running", "awaiting_approval"} or not context or context.get("stageId") != task.id
                    or context.get("correlationId") != task.correlation_id
                    or context.get("subject") != subject
                    or getattr(task, "a2a_cli_cancel", None) is not None):
                return False
            operation = uuid.uuid4().hex
            task.a2a_cli_cancel = dict(operationId=operation, status="reserved")
            task.state = "cancelling"; task.save()
        try:
            receipt = self.supervisor.stop_and_verify(dict(context, operationId=operation))
            verified = (isinstance(receipt, dict)
                and all(receipt.get(k) == v for k,v in dict(context,operationId=operation).items())
                and receipt.get("stopped") is True and receipt.get("processExitVerified") is True
                and receipt.get("descendantAbsenceVerified") is True
                and isinstance(receipt.get("scopeUid"),str) and bool(receipt["scopeUid"]))
        except BaseException:
            verified = False
        with task.persistence_lock:
            task.a2a_cli_cancel["status"] = "verified" if verified else "uncertain"
            if verified: task.a2a_terminal_receipt = receipt
            task.state = "cancelled" if verified else "interrupted"; task.save()
            if verified: task.finished.set()
        return verified

    def recover_task(self, subject, task):
        if subject != self.subject or not self.qualified:
            raise ValueError("A2A_CLI_SCOPE_NOT_QUALIFIED")
        with task.persistence_lock:
            context = getattr(task, "a2a_cli_context", None)
            if (not context or context.get("stageId") != task.id
                    or context.get("correlationId") != task.correlation_id
                    or context.get("project") != task.request["project"]
                    or context.get("subject") != subject):
                raise ValueError("A2A_CLI_RECOVERY_IDENTITY_REFUSED")
            retained = getattr(task, "a2a_terminal_receipt", None)
            if (task.state in {"completed", "cancelled"} and isinstance(retained, dict)
                    and all(retained.get(k) == v for k,v in context.items())
                    and retained.get("stopped") is True
                    and retained.get("processExitVerified") is True
                    and retained.get("descendantAbsenceVerified") is True
                    and isinstance(retained.get("scopeUid"), str) and retained["scopeUid"]):
                task.finished.set()
                return True  # Preserve accepted results without another transport call.
        # Observation only: never execute/restart a recovered client or prompt.
        receipt = self.supervisor.observe_terminal(dict(context))
        if (not isinstance(receipt, dict) or any(receipt.get(k) != v for k,v in context.items())
                or receipt.get("stopped") is not True
                or receipt.get("processExitVerified") is not True
                or receipt.get("descendantAbsenceVerified") is not True
                or not isinstance(receipt.get("scopeUid"), str) or not receipt["scopeUid"]):
            return False
        with task.persistence_lock:
            task.a2a_terminal_receipt = receipt
            # Absence does not recover a lost result, so do not claim completion.
            task.state = "interrupted"; task.save(); task.finished.set()
        return True
