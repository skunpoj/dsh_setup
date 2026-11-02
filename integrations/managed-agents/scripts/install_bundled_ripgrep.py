"""Build-only installation of the RECORD-verified runtime wheel's rg sidecar.

No downloads or provider access. Run using the managed environment's Python.
"""
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess


def verify_record_file(source, record):
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Bundled rg must be a regular file")
    if record.hash is None or record.hash.mode != "sha256":
        raise ValueError("Bundled rg has no SHA-256 RECORD entry")
    data = source.read_bytes()
    digest = hashlib.sha256(data).digest()
    if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != record.hash.value:
        raise ValueError("Bundled rg differs from its wheel RECORD")
    if record.size is None or len(data) != record.size:
        raise ValueError("Bundled rg size differs from its wheel RECORD")
    return digest.hex()


def install(destination=Path("/usr/local/bin/rg")):
    from deepseek_harness_runtime import bundled_runtime_path

    distribution = importlib.metadata.distribution("deepseek-harness-runtime-bin")
    sdk = importlib.metadata.version("deepseek-harness-sdk")
    if sdk != distribution.version:
        raise ValueError("SDK and runtime wheel versions must match")
    source = Path(str(bundled_runtime_path()) + "-rg")
    records = [r for r in distribution.files or ()
               if Path(distribution.locate_file(r)).absolute() == source.absolute()]
    if len(records) != 1:
        raise ValueError("Bundled rg must have exactly one wheel RECORD entry")
    digest = verify_record_file(source, records[0])
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to replace an existing rg")
    # The immutable image build owns this path; no runtime install is performed.
    with destination.open("xb") as target, source.open("rb") as original:
        shutil.copyfileobj(original, target)
    os.chmod(destination, 0o755)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
        raise ValueError("Installed rg digest differs")
    version = subprocess.run([str(destination), "--version"], check=True,
                             capture_output=True, text=True, timeout=10).stdout.splitlines()[0]
    if not version.startswith("ripgrep "):
        raise ValueError("Unexpected bundled rg version response")
    return {"runtimeVersion": distribution.version, "sdkVersion": sdk,
            "sha256": digest, "destination": str(destination), "version": version,
            "source": "installed-runtime-wheel-RECORD", "downloads": False}


if __name__ == "__main__":
    print(json.dumps(install(), sort_keys=True))
