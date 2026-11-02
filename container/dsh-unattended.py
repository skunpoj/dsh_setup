#!/usr/bin/env python3
"""Launch a managed client behind one bounded unattended task guard."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import uuid
import re

sys.path.insert(0, "/opt/dsh/scripts")
from unattended_model_guard import AdmissionLedger, APPROVED_UPSTREAM, running_guard
from dsh_correlation import validate_correlation_id

CLIENTS = {
    "claude": ["/usr/local/bin/claude"],
    "sdk": ["/usr/local/bin/dsh-sdk-task"],
    "deepagents": ["/usr/local/bin/deepagents"],
    "kilo": ["/usr/local/bin/kilo"],
}


def safe_task(value):
    value = value or uuid.uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid task id")
    return value


def build_environment(parent, client, base):
    env = dict(parent)
    env["DSH_UNATTENDED_TASK"] = env.get("DSH_UNATTENDED_TASK", "")
    env["DSH_GUARDED_MODEL_BASE_URL"] = base + "/v1"
    if client == "claude":
        env["ANTHROPIC_BASE_URL"] = base
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
    return env


def run_client(command, env, cwd="/workspace"):
    child = subprocess.Popen(command, env=env, cwd=cwd,
                             start_new_session=(os.name != "nt"))

    def forward(signum, _frame):
        if child.poll() is not None:
            return
        if os.name == "nt":
            child.send_signal(signum)
        else:
            os.killpg(child.pid, signum)

    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, forward)
    try:
        return child.wait()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main():
    raw = sys.argv[1:]
    separator = raw.index("--") if "--" in raw else len(raw)
    control, client_args = raw[:separator], raw[separator + 1:] if separator < len(raw) else []
    parser = argparse.ArgumentParser(description="Run a managed client without unattended replay")
    parser.add_argument("client", choices=sorted(CLIENTS))
    parser.add_argument("--task-id")
    parser.add_argument("--max-model-starts", type=int, default=12)
    parser.add_argument("--cwd", default="/workspace")
    parser.add_argument("--resume", action="store_true")
    options = parser.parse_args(control)
    if options.max_model_starts < 1 or options.max_model_starts > 64:
        raise ValueError("max model starts must be 1-64")
    task = safe_task(options.task_id)
    task_correlation_id = validate_correlation_id(os.environ.get("DSH_CORRELATION_ID", ""))
    state = Path("/state/unattended") / task
    if options.resume:
        if not state.is_dir():
            raise ValueError("task state is unavailable for resume")
    else:
        state.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = AdmissionLedger(state / "model-starts.jsonl", task, options.max_model_starts,
                             task_correlation_id=task_correlation_id)
    with running_guard(APPROVED_UPSTREAM, Path("/harness-credentials/api-key"), ledger) as port:
        base = f"http://127.0.0.1:{port}"
        env = build_environment(os.environ, options.client, base)
        env["DSH_UNATTENDED_TASK"] = task
        env["DSH_CORRELATION_ID"] = task_correlation_id
        cwd = Path(options.cwd).resolve()
        workspace = Path("/workspace").resolve()
        if cwd != workspace and workspace not in cwd.parents:
            raise ValueError("cwd must be inside /workspace")
        return run_client([*CLIENTS[options.client], *client_args], env, str(cwd))


if __name__ == "__main__":
    raise SystemExit(main())
