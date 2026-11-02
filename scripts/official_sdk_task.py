"""Official SDK qualification adapter; never silently substitutes Deep Agents.

This is a candidate adapter, not the deployed resumable broker launcher. Native
approval continuation must be integrated before replacing that launcher's API.
"""
import importlib.metadata
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


PIN = "0.2.1rc2"
MODEL = "deepseek-v4.1-flash"


def guarded_endpoint(value):
    endpoint = urlsplit(value)
    if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1"
            or endpoint.username or endpoint.password or endpoint.path != "/v1"
            or endpoint.query or endpoint.fragment or not endpoint.port):
        raise ValueError("OFFICIAL_SDK_GUARD_REQUIRED")
    return value


def qualify(prompt, *, task_id, project, state_root, guard_url,
            harness_factory=None, version=importlib.metadata.version):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
        raise ValueError("INVALID_TASK")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("EMPTY_PROMPT")
    endpoint = guarded_endpoint(guard_url)
    for distribution in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin"):
        if version(distribution) != PIN:
            raise ValueError("OFFICIAL_SDK_VERSION_MISMATCH")
    project = Path(project).resolve(strict=True)
    task_root = Path(state_root) / task_id
    # Both directories are supplied by the broker qualification controller, not
    # user-selected config. Exclusive creation fences repeated adapter starts.
    task_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    home = task_root / "official-sdk-home"
    home.mkdir(mode=0o700)
    patch = task_root / "qualification.patch.yml"
    patch.write_text(
        "- id: session-log-deepseek\n  config:\n    enabled: false\n"
        "- id: llm-retry\n  disabled: true\n"
        "- id: sandbox-policy\n  config:\n    mode: read-only\n"
        "    workspaceRoot: " + json.dumps(str(project)) + "\n",
        encoding="utf-8")
    reservation = task_root / "invocation.json"
    with reservation.open("x", encoding="utf-8") as stream:
        json.dump({"kind": "OFFICIAL_SDK_QUALIFICATION_V1", "taskId": task_id,
                   "sdkVersion": PIN, "profile": "sdk", "state": "RESERVED",
                   "automaticReplay": False}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    if harness_factory is None:
        from deepseek_harness import DeepSeekHarness
        harness_factory = DeepSeekHarness
    # Dummy loopback key only. The approved guard alone owns upstream auth.
    with harness_factory(provider="deepseek-official", model=MODEL,
                         profile="sdk", max_tokens=64, cwd=str(project),
                         runtime_cwd=str(project), dsh_home=str(home),
                         patches=(str(patch),), base_url=endpoint,
                         api_key="local-guard-placeholder",
                         request_timeout_seconds=120) as harness:
        result = harness.run(prompt, session_id=task_id)
    if result.finish_reason != "completed" or not result.final_response.strip():
        raise RuntimeError("OFFICIAL_SDK_RESULT_NOT_COMPLETED")
    return result.final_response
