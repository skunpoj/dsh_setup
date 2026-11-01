#!/usr/bin/env python3
"""Launch a managed client behind one bounded unattended task guard."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, "/opt/dsh/scripts")
from unattended_model_guard import AdmissionLedger, APPROVED_UPSTREAM, running_guard

CLIENTS = {
    "claude": ["/usr/local/bin/claude"],
    "kilo": ["/usr/local/bin/kilo"],
}


def safe_task(value):
    return value or str(uuid.uuid4())


def build_environment(parent, client, base):
    env = dict(parent)
    env["DSH_UNATTENDED_TASK"] = env.get("DSH_UNATTENDED_TASK", "")
    env["DSH_GUARDED_MODEL_BASE_URL"] = base + "/v1"
    if client == "claude":
        env["ANTHROPIC_BASE_URL"] = base
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
    return env


def main():
    parser = argparse.ArgumentParser(description="Run a managed client without unattended replay")
    parser.add_argument("client", choices=sorted(CLIENTS))
    parser.add_argument("--task-id")
    parser.add_argument("--max-model-starts", type=int, default=12)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    task = safe_task(options.task_id)
    state = Path("/state/unattended") / task
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = AdmissionLedger(state / "model-starts.jsonl", task, options.max_model_starts)
    with running_guard(APPROVED_UPSTREAM, Path("/harness-credentials/api-key"), ledger) as port:
        base = f"http://127.0.0.1:{port}"
        env = build_environment(os.environ, options.client, base)
        env["DSH_UNATTENDED_TASK"] = task
        return subprocess.call([*CLIENTS[options.client], *options.args], env=env, cwd="/workspace")


if __name__ == "__main__":
    raise SystemExit(main())
