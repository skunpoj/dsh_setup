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
from banking_process_identity import agent_kwargs,banking_guard_state
from dsh_correlation import validate_correlation_id

CLIENTS = {
    "claude": ["/usr/local/bin/claude"],
    "sdk": ["/usr/local/bin/dsh-sdk-task"],
    "deepagents": ["/usr/local/bin/deepagents"],
    "kilo": ["/usr/local/bin/kilo"],
}


BANKING_GATE_ROOT = Path("/state/banking-gate")
# Runs AS the agent identity (see banking_gate_dir): creates /state/banking-gate (if missing) and the fresh /state/banking-gate/<task>, both owned by that identity, and verifies
# them. No chown, no capability, no root-owned directory is involved: the creator IS the owner, so a rollout that keeps only SETUID/SETGID/KILL (no CHOWN, no DAC_OVERRIDE) works.
BANKING_GATE_HELPER = r"""
import os, re, stat, sys
root, task = sys.argv[1], sys.argv[2]
if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task):
    sys.exit(64)
posix = os.name == 'posix'
os.makedirs(root, mode=0o700, exist_ok=True)
info = os.lstat(root)
if not stat.S_ISDIR(info.st_mode) or (posix and (info.st_uid != os.getuid() or info.st_mode & 0o022)):
    sys.exit(70)
directory = os.path.join(root, task)
os.mkdir(directory, 0o700)
info = os.lstat(directory)
if not stat.S_ISDIR(info.st_mode) or (posix and (info.st_uid != os.getuid() or info.st_mode & 0o077)):
    sys.exit(71)
"""


def banking_gate_dir(task, *, root=None, euid=None, platform=None, runner=None):
    """Fresh PRIVATE directory for the PreToolUse gate's write-success marker (contract in container/dsh-banking-gate.cjs).

    Created by this launcher BEFORE claude starts, one per task id (os.mkdir, no exist_ok: a task id gets it once, so no marker can carry over), by a short helper that runs AS
    the fixed agent identity through the SAME drop claude itself gets (agent_kwargs: user/group AGENT_UID, no extra groups, umask 077). So the directory is owned by the identity
    the hook runs as WITHOUT chown: no CAP_CHOWN and no DAC capability is needed or used (the UID-separated rollout keeps only SETUID/SETGID/KILL). It is deliberately NOT inside the
    protected guard/journal tree (root 0700, budget authority). Returns the exact path the hook must be given in DSH_BANKING_GATE_DIR."""
    if not isinstance(task, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task):
        raise ValueError("EXACT_GATE_TASK_REQUIRED")
    root = Path(root) if root is not None else BANKING_GATE_ROOT
    done = (runner or subprocess.run)([sys.executable, "-I", "-c", BANKING_GATE_HELPER, str(root), task], cwd=os.path.abspath(os.sep),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                                       **agent_kwargs(platform=platform, euid=euid))
    if done.returncode != 0:
        raise ValueError("BANKING_GATE_DIR_REFUSED")
    return str(root / task)


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


def build_environment(parent, client, base, claude_pin=None, banking_gate=False, banking_gate_dir=None):
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
        # The per-task guard admits ONE upstream start and refuses an identical request as 'duplicate-or-uncertain' (no replay), so an unattended Claude must never
        # retry or fall back to a non-streaming resend. Interactive Claude has no guard and keeps Claude Code's normal retry; the managed policy therefore no longer
        # sets these (a managed policy value would override this process environment).
        env["CLAUDE_CODE_MAX_RETRIES"] = "0"
        env["CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"] = "1"
        if banking_gate:
            # An admitted banking task only: the managed PreToolUse hook (container/dsh-banking-gate.cjs) denies everything but the two exact banking commands.
            env["DSH_BANKING_GATE"] = "1"
            if banking_gate_dir:
                env["DSH_BANKING_GATE_DIR"] = banking_gate_dir
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


def run_client(command, env, cwd="/workspace", completion=None):
    child = subprocess.Popen(command, env=env, cwd=cwd, **agent_kwargs(),
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
    exit_code=None
    try:
        exit_code=child.wait()
        return exit_code
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        if os.name != "nt":
            # The leader may already have exited while descendants still live.
            # Cleanup the owned inner session group, not just the wrapper PID.
            stop_client_group(child.pid)
            child.wait(timeout=5)
            if completion is not None and type(exit_code) is int:
                completion.update(trueExitCode=exit_code,childPID=child.pid,processGroup=child.pid,descendantAbsenceVerified=True)
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
    parser.add_argument("--max-model-starts", type=lambda value: None if value=="standing-banking" else int(value), default=12)
    parser.add_argument("--guard-port", type=int, default=0)
    parser.add_argument('--external-guard-port', type=int, default=0)
    parser.add_argument("--cwd", default="/workspace")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--banking-gate", action="store_true")
    options = parser.parse_args(control)
    if options.banking_gate and (options.client != "claude" or options.resume):
        raise ValueError("--banking-gate is only for a fresh claude task")
    if options.max_model_starts is not None and (options.max_model_starts < 1 or options.max_model_starts > 64):
        raise ValueError("max model starts must be 1-64")
    task = safe_task(options.task_id)
    task_correlation_id = validate_correlation_id(os.environ.get("DSH_CORRELATION_ID", ""))
    cwd = Path(options.cwd).resolve()
    workspace = Path('/workspace').resolve()
    if cwd != workspace and workspace not in cwd.parents:
        raise ValueError('cwd must be inside /workspace')
    if options.external_guard_port and options.max_model_starts is None:raise ValueError("STANDING_CLI_EXTERNAL_GUARD_REFUSED")
    if options.external_guard_port:
        if options.guard_port or options.resume:
            raise ValueError('EXTERNAL_GUARD_MODE_CONFLICT')
        # Guard sidecar owns the existing durable ledger and model credential.
        # This payload mode never mounts/reads credentials or creates a guard.
        base = verify_external_guard(options.external_guard_port, task,
                                     task_correlation_id, options.max_model_starts)
        env = build_environment(os.environ, options.client, base, banking_gate=options.banking_gate,
                                banking_gate_dir=banking_gate_dir(task) if options.banking_gate else None)
        env['DSH_UNATTENDED_TASK'] = task
        env['DSH_EXTERNAL_TASK_GUARD'] = 'sidecar'
        return run_client([*CLIENTS[options.client], *client_args], env, str(cwd))
    # Read the managed pin before any task state exists so a policy the guard cannot
    # satisfy fails closed without leaving a half-created task behind.
    claude_pin = claude_managed_pin() if options.client == "claude" else None
    state = banking_guard_state(task) or Path("/state/unattended") / task
    if options.resume:
        if not state.is_dir():
            raise ValueError("task state is unavailable for resume")
    else:
        state.mkdir(mode=0o700, parents=True, exist_ok=False)
    if options.max_model_starts is None:
        from scripts.banking_allowance import require_standing_cli_reservation
        if str(state)!='/state/banking-guard-protected/tasks/cli/'+task:raise ValueError("STANDING_BANKING_PRIVATE_STATE_REQUIRED")
        require_standing_cli_reservation(task,task_correlation_id)
    ledger = AdmissionLedger(state / "model-starts.jsonl", task, options.max_model_starts,
                             task_correlation_id=task_correlation_id,banking_accounting_only=options.max_model_starts is None)
    guard_options={"listen_port":options.guard_port} if options.guard_port else {}
    if claude_pin is not None:
        guard_options["proxy_origin"] = claude_pin
        guard_options.setdefault("listen_port", CLAUDE_GUARD_PORT)
    completion={} if str(state).startswith('/state/banking-guard-protected/tasks/cli/') else None
    with running_guard(APPROVED_UPSTREAM, Path("/harness-credentials/api-key"), ledger,**guard_options) as port:
        base = f"http://127.0.0.1:{port}"
        env = build_environment(os.environ, options.client, base, claude_pin, banking_gate=options.banking_gate,
                                banking_gate_dir=banking_gate_dir(task) if options.banking_gate else None)
        env["DSH_UNATTENDED_TASK"] = task
        env["DSH_CORRELATION_ID"] = task_correlation_id
        code=run_client([*CLIENTS[options.client], *client_args], env, str(cwd),completion=completion) if completion is not None else run_client([*CLIENTS[options.client], *client_args], env, str(cwd))
    if str(state).startswith('/state/banking-guard-protected/tasks/cli/'):
        from banking_private_capture import write_cli_terminal
        write_cli_terminal(state,task=task,correlation=task_correlation_id,maximum=options.max_model_starts,completion=completion,ledger=state/'model-starts.jsonl')
    return code


if __name__ == "__main__":
    raise SystemExit(main())
