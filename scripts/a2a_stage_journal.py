"""Stage transitions owned and persisted by the existing authenticated broker.

No process launch, model call, credential access or independent state writer.
The caller must hold the Task persistence lock and persist returned records
before dispatch. Interrupted reservations are fenced, never replayed.
"""
import copy
import hashlib
import re
from scripts.official_sdk_approval import verified_terminal_stop

RUNTIMES = {"sdk", "claude", "deepagents"}


def reserve(stages, *, runtime, stage_id, correlation_id):
    if runtime not in RUNTIMES or any(not isinstance(v, str) or
            not re.fullmatch(r"[a-f0-9]{32}", v) for v in (stage_id, correlation_id)):
        raise ValueError("A2A_INVALID_STAGE_IDENTITY")
    if len(stages) >= 2:
        raise ValueError("A2A_STAGE_LIMIT")
    if any(s["stageId"] == stage_id or s["correlationId"] == correlation_id for s in stages):
        raise ValueError("A2A_DUPLICATE_STAGE")
    if stages and (stages[-1]["status"] != "completed" or
                   stages[-1].get("terminalVerified") is not True):
        raise ValueError("A2A_PREVIOUS_STAGE_NOT_RETIRED")
    result = copy.deepcopy(stages)
    result.append(dict(runtime=runtime, stageId=stage_id, correlationId=correlation_id,
                       status="reserved", terminalVerified=False))
    return result


def complete(stages, *, stage_id, output, terminal_receipt):
    if (not stages or stages[-1]["stageId"] != stage_id or
            stages[-1]["status"] != "reserved"):
        raise ValueError("A2A_STALE_OR_FENCED_RESULT")
    if (not isinstance(terminal_receipt, dict) or
            terminal_receipt.get("stageId") != stage_id or
            terminal_receipt.get("correlationId") != stages[-1]["correlationId"] or
            terminal_receipt.get("stopped") is not True or
            terminal_receipt.get("processExitVerified") is not True or
            terminal_receipt.get("descendantAbsenceVerified") is not True or
            (stages[-1]['runtime'] in {'claude','deepagents'} and
             (not isinstance(terminal_receipt.get('scopeUid'),str) or not terminal_receipt['scopeUid']))):
        raise ValueError("A2A_TERMINAL_PROOF_REQUIRED")
    if not isinstance(output, str) or not output.strip() or len(output.encode("utf-8")) > 262144:
        raise ValueError("A2A_BOUNDED_OUTPUT_REQUIRED")
    result = copy.deepcopy(stages)
    result[-1].update(status="completed", terminalVerified=True,
                      outputSha256=hashlib.sha256(output.encode("utf-8")).hexdigest())
    return result


def fence(stages):
    result = copy.deepcopy(stages)
    for stage in result:
        if stage["status"] == "reserved":
            stage["status"] = "fenced"
    return result


def complete_native(stages, *, record, output):
    """Consume a broker-owned native Task snapshot, never client-submitted proof."""
    if (not stages or stages[-1]["runtime"] != "sdk" or
            not isinstance(record, dict) or record.get("state") != "completed" or
            record.get("id") != stages[-1]["stageId"] or
            record.get("correlationId") != stages[-1]["correlationId"] or
            not verified_terminal_stop(record)):
        raise ValueError("A2A_NATIVE_TERMINAL_PROOF_REQUIRED")
    return complete(stages, stage_id=record["id"], output=output,
                    terminal_receipt=dict(stageId=record["id"],
                        correlationId=record["correlationId"], stopped=True,
                        processExitVerified=True, descendantAbsenceVerified=True))
