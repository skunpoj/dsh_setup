"""Explicit server-composed official SDK banking guard; never installed by qualification.

open_guard must create the actual task guard with the supplied cap and expose its
AdmissionLedger as guard.ledger. This adapter does not create a worker, discover
credentials, grant scope admission, or change the native qualification guard.
Failed opens consume the durable reservation conservatively; no automatic retry.
"""
import hashlib
import re
from contextlib import contextmanager
from scripts import banking_allowance


class SDKBankingGuardFactory:
    def __init__(self, *, subject, generation, run_id, open_guard,
                 allowance_file=None, ledger_file=None, owner_check=None):
        if (any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", v)
                for v in (subject, generation, run_id)) or not callable(open_guard)):
            raise ValueError("EXPLICIT_BANKING_SDK_BINDING_REQUIRED")
        self.subject, self.generation, self.run_id = subject, generation, run_id
        self.open_guard = open_guard
        self.options = dict(allowance_file=allowance_file, ledger_file=ledger_file, owner_check=owner_check)

    @contextmanager
    def __call__(self, task):
        with task.persistence_lock:
            request = task.request
            if (task.authenticated_subject != self.subject or request.get("runtime") != "sdk"
                    or request.get("backend") != "private" or request.get("handoffRuntime") is not None
                    or task.state != "running" or not isinstance(request.get("prompt"), str)
                    or type(request.get("writes")) is not bool
                    or any(not re.fullmatch(r"[a-f0-9]{32}", str(v)) for v in (task.id, task.correlation_id))):
                raise ValueError("EXACT_BANKING_SDK_TASK_REQUIRED")
            binding = dict(subject=self.subject, generation=self.generation, runId=self.run_id,
                taskId=task.id, correlationId=task.correlation_id, project=request.get("project"),
                runtime="sdk", runner="official-native-sdk", writes=request["writes"],
                promptSha256=hashlib.sha256(request["prompt"].encode()).hexdigest())
            reservation = {}
            cap = banking_allowance.request_cap("sdk", binding["project"], task.id,
                subject=self.subject, run_id=self.run_id, runner=binding["runner"], sdk_binding=binding, sdk_receipt=reservation, **self.options)
            if cap is not None and cap <= 1:
                raise ValueError("OFFICIAL_SDK_BANKING_GRANT_REQUIRED")
        # The scope preflight and package/physical identity remain the runner's
        # independent requirements. This callback is trusted composition only.
        guard_binding = dict(binding, grantSha256=reservation["grantSha256"])
        with self.open_guard(task=task, binding=guard_binding, max_requests=cap) as guard:
            with task.persistence_lock:
                if (task.state != "running" or task.authenticated_subject != self.subject
                        or task.correlation_id != binding["correlationId"]
                        or request is not task.request or request.get("project") != binding["project"]
                        or request.get("writes") is not binding["writes"]
                        or request.get("runtime") != "sdk" or request.get("backend") != "private"
                        or request.get("handoffRuntime") is not None
                        or hashlib.sha256(request.get("prompt", "").encode()).hexdigest() != binding["promptSha256"]):
                    raise ValueError("BANKING_SDK_TASK_FENCED_OR_CHANGED")
                ledger = getattr(guard, "ledger", None)
                if (getattr(guard, "task_id", None) != task.id
                        or getattr(guard, "correlation_id", None) != task.correlation_id
                        or getattr(ledger, "task_id", None) != task.id
                        or getattr(ledger, "task_correlation_id", None) != task.correlation_id
                        or not hasattr(ledger,"maximum") or ledger.maximum != cap):
                    raise ValueError("BANKING_SDK_GUARD_CAP_BINDING_MISMATCH")
            yield guard
