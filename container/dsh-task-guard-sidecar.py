#!/usr/bin/env python3
"""Per-task model guard sidecar of a native-qualification worker Pod (container `model-guard`).

Started by scripts/a2a_private_worker_pod.py as
  python3 -I -S /opt/dsh/container/dsh-task-guard-sidecar.py --task-id T --correlation-id C --drain-on-stdin
It runs the existing per-task guard (scripts/unattended_model_guard.py) on 127.0.0.1:4001 against the single approved
upstream, with the task ledger under /state/unattended/<task>/ and the task-only credential at /harness-credentials/api-key,
and answers exactly ONE private stdin command from the broker's kubectl attach: a `fence-and-snapshot` request that
scripts/a2a_guard_control.drain_once validates before it fences. The reply is one JSON line (DSH_GUARD_LOCAL_DRAIN_V1).
It opens no control socket, makes no model request of its own and never prints credential or ledger text except the
bounded, validated ledger snapshot inside the receipt.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path[:0] = ["/opt/dsh"]  # `-I -S` removes the script directory and site-packages from sys.path
from scripts.a2a_guard_control import drain_once
from scripts.dsh_correlation import validate_correlation_id
from scripts.official_sdk_package_admission import unique_json
from scripts.unattended_model_guard import APPROVED_UPSTREAM, AdmissionLedger, running_guard

GUARD_PORT = 4001  # the worker container's launcher verifies exactly this loopback port
MAX_MODEL_STARTS = 1
STATE_ROOT = Path("/state/unattended")
TOKEN_FILE = Path("/harness-credentials/api-key")
POD_UID_FILE = Path("/etc/dsh-worker-identity/pod-uid")
TASK_ID = re.compile(r"[a-f0-9]{32}")
UID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


def run(*, task_id, correlation_id, stdin, stdout, state_root=STATE_ROOT, token_file=TOKEN_FILE,
        pod_uid_file=POD_UID_FILE, listen_port=GUARD_PORT, upstream=APPROVED_UPSTREAM, allow_test_upstream=False):
    if not TASK_ID.fullmatch(task_id or ""):
        raise ValueError("INVALID_GUARD_TASK_ID")
    correlation_id = validate_correlation_id(correlation_id)
    pod_uid = Path(pod_uid_file).read_text(encoding="ascii").strip()
    if not UID.fullmatch(pod_uid):
        raise ValueError("INVALID_WORKER_POD_UID")
    state = Path(state_root) / task_id
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = AdmissionLedger(state / "model-starts.jsonl", task_id, MAX_MODEL_STARTS, task_correlation_id=correlation_id)
    with running_guard(upstream, Path(token_file), ledger, listen_port=listen_port, yield_server=True,
                       allow_test_upstream=allow_test_upstream) as server:
        line = stdin.readline(65537)
        if not line or len(line) > 65536:
            raise ValueError("DRAIN_REQUEST_MISSING_OR_TOO_LARGE")  # leaving the guard block fences the task
        request = unique_json(line.encode("utf-8"))
        receipt = drain_once(request, task_id=task_id, correlation_id=correlation_id, pod_uid=pod_uid,
                             server=server, ledger=ledger)
        stdout.write(json.dumps(receipt, separators=(",", ":")) + "\n")
        stdout.flush()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Per-task model guard sidecar (private stdin drain only)")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--drain-on-stdin", action="store_true", required=True)
    options = parser.parse_args(argv)
    try:
        return run(task_id=options.task_id, correlation_id=options.correlation_id, stdin=sys.stdin, stdout=sys.stdout)
    except (ValueError, OSError) as error:
        print("GUARD_SIDECAR_REFUSED " + str(error)[:120], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
