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
import time
import http.client
import json

sys.path.insert(0, "/opt/dsh/scripts")
from unattended_model_guard import AdmissionLedger, APPROVED_UPSTREAM, running_guard, validate_proxy_origin
from unattended_env import minimal_environment
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


CLAUDE_MANAGED_SETTINGS = Path("/etc/claude-code/managed-settings.json")
# One task runs per workspace Pod, so a fixed loopback port cannot collide.
CLAUDE_GUARD_PORT = 4180


def claude_managed_pin(path=None):
    """The model endpoint the managed Claude policy pins, or None when it pins none.

    Claude Code reads managed settings only from the system path, so a task cannot
    carry its own policy. The policy's pinned endpoint is the one name Claude will
    accept, so an unattended Claude task is pointed at that name and reaches the
    guard through the guard's proxy listener instead of through a different URL.
    Fail closed: a policy that restricts providers but pins no endpoint cannot be
    satisfied, and a malformed pin is never repaired.
    """
    try:
        raw = Path(path or CLAUDE_MANAGED_SETTINGS).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        policy = json.loads(raw)
    except ValueError as exc:
        raise ValueError("CLAUDE_MANAGED_SETTINGS_UNREADABLE") from exc
    if not isinstance(policy, dict):
        raise ValueError("CLAUDE_MANAGED_SETTINGS_UNREADABLE")
    env = policy.get("env")
    pin = env.get("ANTHROPIC_BASE_URL") if isinstance(env, dict) else None
    if pin is None:
        if policy.get("allowedProviders"):
            raise ValueError("CLAUDE_MANAGED_PIN_REQUIRED")
        return None
    if not isinstance(pin, str):
        raise ValueError("CLAUDE_MANAGED_PIN_INVALID")
    try:
        validate_proxy_origin(pin)
    except ValueError as exc:
        raise ValueError("CLAUDE_MANAGED_PIN_INVALID") from exc
    return pin


def build_environment(parent, client, base, claude_pin=None):
    env = minimal_environment(parent)
    env["DSH_UNATTENDED_TASK"] = env.get("DSH_UNATTENDED_TASK", "")
    env["DSH_GUARDED_MODEL_BASE_URL"] = base + "/v1"
    if client == "claude":
        if claude_pin is None:
            env["ANTHROPIC_BASE_URL"] = base
        else:
            # The managed pin stays the endpoint; only this process's HTTP proxy is
            # the guard. No other proxy variable survives the allowlist.
            env["ANTHROPIC_BASE_URL"] = claude_pin
            env["HTTP_PROXY"] = base
            env["http_proxy"] = base
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
    return env


def verify_external_guard(port, task_id, correlation_id, maximum):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('INVALID_EXTERNAL_GUARD_PORT')
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request('GET', '/_dsh/task-identity')
        response = connection.getresponse()
        raw = response.read(4097)
        if response.status != 200 or len(raw) > 4096:
            raise ValueError('EXTERNAL_TASK_GUARD_UNVERIFIED')
        observed = json.loads(raw)
        if observed != dict(taskId=task_id, correlationId=correlation_id,
                            maximum=maximum, upstream=APPROVED_UPSTREAM):
            raise ValueError('EXTERNAL_TASK_GUARD_BINDING_MISMATCH')
    finally:
        connection.close()
    return f'http://127.0.0.1:{port}'


def stop_client_group(pgid, timeout=2.0):
    """Bounded POSIX group cleanup; does not prove cgroup/escaped-child isolation."""
    if type(pgid) is not int or pgid <= 1:
        raise ValueError("CLI_GROUP_IDENTITY_REQUIRED")
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, signum)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                return
            time.sleep(.02)
    raise RuntimeError("CLI_PROCESS_GROUP_STOP_UNVERIFIED")


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
        if os.name != "nt":
            # The leader may already have exited while descendants still live.
            # Cleanup the owned inner session group, not just the wrapper PID.
            stop_client_group(child.pid)
            child.wait(timeout=5)
        elif child.poll() is None:
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
    parser.add_argument("--guard-port", type=int, default=0)
    parser.add_argument('--external-guard-port', type=int, default=0)
    parser.add_argument("--cwd", default="/workspace")
    parser.add_argument("--resume", action="store_true")
    options = parser.parse_args(control)
    if options.max_model_starts < 1 or options.max_model_starts > 64:
        raise ValueError("max model starts must be 1-64")
    task = safe_task(options.task_id)
    task_correlation_id = validate_correlation_id(os.environ.get("DSH_CORRELATION_ID", ""))
    cwd = Path(options.cwd).resolve()
    workspace = Path('/workspace').resolve()
    if cwd != workspace and workspace not in cwd.parents:
        raise ValueError('cwd must be inside /workspace')
    if options.external_guard_port:
        if options.guard_port or options.resume:
            raise ValueError('EXTERNAL_GUARD_MODE_CONFLICT')
        # Guard sidecar owns the existing durable ledger and model credential.
        # This payload mode never mounts/reads credentials or creates a guard.
        base = verify_external_guard(options.external_guard_port, task,
                                     task_correlation_id, options.max_model_starts)
        env = build_environment(os.environ, options.client, base)
        env['DSH_UNATTENDED_TASK'] = task
        env['DSH_EXTERNAL_TASK_GUARD'] = 'sidecar'
        return run_client([*CLIENTS[options.client], *client_args], env, str(cwd))
    # Read the managed pin before any task state exists so a policy the guard cannot
    # satisfy fails closed without leaving a half-created task behind.
    claude_pin = claude_managed_pin() if options.client == "claude" else None
    state = Path("/state/unattended") / task
    if options.resume:
        if not state.is_dir():
            raise ValueError("task state is unavailable for resume")
    else:
        state.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = AdmissionLedger(state / "model-starts.jsonl", task, options.max_model_starts,
                             task_correlation_id=task_correlation_id)
    guard_options={"listen_port":options.guard_port} if options.guard_port else {}
    if claude_pin is not None:
        guard_options["proxy_origin"] = claude_pin
        guard_options.setdefault("listen_port", CLAUDE_GUARD_PORT)
    with running_guard(APPROVED_UPSTREAM, Path("/harness-credentials/api-key"), ledger,**guard_options) as port:
        base = f"http://127.0.0.1:{port}"
        env = build_environment(os.environ, options.client, base, claude_pin)
        env["DSH_UNATTENDED_TASK"] = task
        env["DSH_CORRELATION_ID"] = task_correlation_id
        return run_client([*CLIENTS[options.client], *client_args], env, str(cwd))


if __name__ == "__main__":
    raise SystemExit(main())
