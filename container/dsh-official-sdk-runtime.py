#!/opt/dsh/deepagents/bin/python -I
"""Owned Linux child entry: isolate environment and exec one admitted runtime.

Never installs packages, discovers a credential or selects an alternate model.
The root-protected admission must be produced by the approved package process.
"""
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
import sys

VERSION = "0.2.2a2"
SOURCE = "ce7073d51254c26cd63b22a60835b8f948deb447"
ADMISSION = "/etc/dsh-native-admission/official-sdk-runtime.json"


def parse_admission(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value: raise ValueError("DUPLICATE_NATIVE_ADMISSION_FIELD")
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {
            "kind", "sourceCommit", "sdkVersion", "runtimeVersion", "runtimeSha256"}
            or value["kind"] != "DSH_OFFICIAL_SDK_RUNTIME_V1"
            or value["sourceCommit"] != SOURCE
            or value["sdkVersion"] != VERSION or value["runtimeVersion"] != VERSION
            or not isinstance(value["runtimeSha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["runtimeSha256"])
            or value["runtimeSha256"] == "0" * 64):
        raise ValueError("UNADMITTED_OFFICIAL_SDK_RUNTIME")
    return value


def child_environment(values, *, state_root=Path("/state/web-tasks")):
    from scripts.official_sdk_task import guarded_endpoint
    task, correlation = values.get("DSH_UNATTENDED_TASK", ""), values.get("DSH_CORRELATION_ID", "")
    if not re.fullmatch(r"[a-f0-9]{32}", task) or not re.fullmatch(r"[a-f0-9]{32}", correlation):
        raise ValueError("NATIVE_CHILD_BINDING_REQUIRED")
    endpoint = guarded_endpoint(values.get("DSH_GUARDED_MODEL_BASE_URL", ""))
    home = state_root / task / "official-sdk-home"
    if Path(values.get("HOME", "")) != home:
        raise ValueError("NATIVE_CHILD_HOME_MISMATCH")
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
        "PYTHONDONTWRITEBYTECODE": "1", "OTEL_SDK_DISABLED": "true", "DO_NOT_TRACK": "1",
        "LANGSMITH_TRACING": "false", "DSH_UNATTENDED_TASK": task,
        "DSH_CORRELATION_ID": correlation, "DSH_GUARDED_MODEL_BASE_URL": endpoint,
        "DEEPSEEK_BASE_URL": endpoint, "DEEPSEEK_API_KEY": "local-guard-placeholder"}


def admitted_binary(admission):
    for package in ("deepseek-harness-sdk", "deepseek-harness-runtime-bin"):
        if importlib.metadata.version(package) != VERSION:
            raise ValueError("NATIVE_CHILD_WHEEL_PAIR_MISMATCH")
    from deepseek_harness_runtime import bundled_runtime_path
    binary = Path(bundled_runtime_path())
    info = binary.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & 0o022 or not info.st_mode & stat.S_IXUSR):
        raise ValueError("UNPROTECTED_NATIVE_RUNTIME_BINARY")
    distribution = importlib.metadata.distribution("deepseek-harness-runtime-bin")
    records = [entry for entry in distribution.files or ()
               if Path(distribution.locate_file(entry)).absolute() == binary.absolute()]
    if len(records) != 1 or records[0].hash is None or records[0].hash.mode != "sha256":
        raise ValueError("NATIVE_RUNTIME_RECORD_REQUIRED")
    with binary.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").digest()
    if (digest.hex() != admission["runtimeSha256"]
            or base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != records[0].hash.value
            or records[0].size != info.st_size):
        raise ValueError("NATIVE_RUNTIME_HASH_MISMATCH")
    return binary


def main():
    if sys.platform != "linux": raise ValueError("NATIVE_RUNTIME_REQUIRES_LINUX")
    # This changes only the newly spawned child, never an existing session.
    if os.getsid(0) != os.getpid() or os.getpgrp() != os.getpid(): os.setsid()
    for directory in (Path("/opt/dsh"), Path("/opt/dsh/scripts")):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("UNPROTECTED_NATIVE_LAUNCHER_SOURCE")
    sys.path.insert(0, "/opt/dsh")  # Fixed, checked image path; -I ignores caller PYTHONPATH.
    from scripts.openshell_bootstrap import read_protected
    admission = parse_admission(read_protected(ADMISSION))
    names = ("DSH_UNATTENDED_TASK", "DSH_CORRELATION_ID", "DSH_GUARDED_MODEL_BASE_URL", "HOME")
    environment = child_environment({name: os.environ.get(name, "") for name in names})
    # Clear inherited values before loading runtime package resolution code.
    os.environ.clear(); os.environ.update(environment)
    binary = admitted_binary(admission)
    os.execve(binary, [str(binary), *sys.argv[1:]], environment)


if __name__ == "__main__":
    try: main()
    except Exception as error:
        print("Official SDK runtime refused: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(70)
