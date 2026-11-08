"""Verify pre-image artifacts for a separate offline Test image, never deploy.

The trusted receipt hash must come from independent CI intake, not this input
directory. The base application image and final built digest need separate
source/image admission. None of these files authorize a workload or model call.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

from scripts.official_sdk_release_admission import (
    VERSION, SOURCE, MAX_SDK_WHEEL, MAX_RUNTIME_WHEEL, verify_producer_pair,
)
from scripts.produce_official_sdk_pair import (
    SDK_NAME, RUNTIME_NAME, require_plain_ancestors,
)


def read_artifact(path, maximum):
    require_plain_ancestors(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("BOUNDED_REGULAR_ARTIFACT_REQUIRED")
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("BOUNDED_REGULAR_ARTIFACT_REQUIRED")
    return raw


def prepare(directory, output, trusted_receipt_sha256):
    directory, output = Path(directory), Path(output)
    require_plain_ancestors(directory)
    expected = {SDK_NAME, RUNTIME_NAME, "producer-receipt.json"}
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("EXACT_TEST_WHEEL_INPUTS_REQUIRED")
    raw = read_artifact(directory / "producer-receipt.json", 65536)
    if hashlib.sha256(raw).hexdigest() != trusted_receipt_sha256:
        raise ValueError("UNTRUSTED_RELEASE_RECEIPT")
    sdk = read_artifact(directory / SDK_NAME, MAX_SDK_WHEEL)
    runtime = read_artifact(directory / RUNTIME_NAME, MAX_RUNTIME_WHEEL)
    verified = verify_producer_pair(
        receipt_raw=raw, trusted_receipt_sha256=trusted_receipt_sha256,
        sdk_raw=sdk, runtime_raw=runtime)
    # pip rechecks these same hashes while opening the wheels. A subsequent
    # input change cannot be accepted merely because this earlier check passed.
    lock = (
        f"deepseek-harness-sdk=={VERSION} --hash=sha256:{verified['sdkWheelSha256']}\n"
        f"deepseek-harness-runtime-bin=={VERSION} --hash=sha256:{verified['runtimeWheelSha256']}\n"
    )
    native = {"kind": "DSH_OFFICIAL_SDK_RUNTIME_V1", "sourceCommit": SOURCE,
              "sdkVersion": VERSION, "runtimeVersion": VERSION,
              "runtimeSha256": verified["runtimeSha256"]}
    require_plain_ancestors(output, leaf_may_be_missing=True)
    output.mkdir(mode=0o700)  # Never overwrite an earlier operation's output.
    (output / "requirements.txt").write_text(lock, encoding="ascii")
    (output / "official-sdk-runtime.json").write_text(
        json.dumps(native, sort_keys=True) + "\n", encoding="utf-8")
    (output / "producer-verified.json").write_text(
        json.dumps(verified, sort_keys=True) + "\n", encoding="utf-8")
    return verified


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trusted-receipt-sha256", required=True)
    args = parser.parse_args()
    prepare(args.input, args.output, args.trusted_receipt_sha256)


if __name__ == "__main__":
    main()
