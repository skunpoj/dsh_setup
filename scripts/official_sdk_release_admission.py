"""Verify the matched official SDK release pair before image admission.

This module never builds, installs, imports, or executes either wheel.  The
approved Linux builder supplies both wheels plus a retained build receipt whose
hash is delivered through a separately protected channel. This verifier binds
them to the reviewed upstream commit, exact
version, Linux platform, builder image digest, and resulting application image
digest.  Missing or ambiguous provenance fails closed.
The byte ceilings are safety bounds, not evidence of actual artifact size or
compatibility; the trusted builder receipt must carry the real exact sizes.
"""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


VERSION = "0.2.2a2"
SOURCE = "ce7073d51254c26cd63b22a60835b8f948deb447"
SDK_NAME = f"deepseek_harness_sdk-{VERSION}-py3-none-any.whl"
RUNTIME_NAME = f"deepseek_harness_runtime_bin-{VERSION}-py3-none-manylinux_2_28_x86_64.whl"
SHA256 = re.compile(r"[a-f0-9]{64}")
IMAGE = re.compile(r"[^\s@]+@sha256:[a-f0-9]{64}")
MAX_SDK_WHEEL = 16 * 1024 * 1024
MAX_RUNTIME_WHEEL = 512 * 1024 * 1024
MAX_SDK_MEMBER = 8 * 1024 * 1024
MAX_RUNTIME_MEMBER = 384 * 1024 * 1024
MAX_MEMBERS = 10000


def _unique_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("DUPLICATE_RELEASE_RECEIPT_FIELD")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _record_digest(raw):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()


def _wheel(raw, distribution, expected_tag, *, max_wheel, max_member):
    if not raw or len(raw) > max_wheel:
        raise ValueError("RELEASE_WHEEL_SIZE_REFUSED")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as error:
        raise ValueError("INVALID_RELEASE_WHEEL") from error
    entries = archive.infolist(); names = [entry.filename for entry in entries]
    if len(names) != len(set(names)) or len(names) > MAX_MEMBERS:
        raise ValueError("INVALID_RELEASE_WHEEL_ENTRIES")
    if sum(entry.file_size for entry in entries) > max_wheel:
        raise ValueError("RELEASE_WHEEL_SIZE_REFUSED")
    for entry in entries:
        name = entry.filename
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name
                or entry.file_size > max_member or (entry.external_attr >> 16) & 0o170000 == 0o120000):
            raise ValueError("INVALID_RELEASE_WHEEL_PATH")
    prefix = distribution.replace("-", "_") + f"-{VERSION}.dist-info/"
    metadata_name = prefix + "METADATA"
    wheel_name = prefix + "WHEEL"
    record_name = prefix + "RECORD"
    if metadata_name not in names or wheel_name not in names or record_name not in names:
        raise ValueError("RELEASE_WHEEL_METADATA_REQUIRED")
    metadata = archive.read(metadata_name).decode("utf-8")
    required = {"Name": distribution, "Version": VERSION}
    fields = {}
    requirements = []
    for line in metadata.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        if key == "Requires-Dist":
            requirements.append(value)
        elif key in required:
            if key in fields:
                raise ValueError("DUPLICATE_RELEASE_METADATA")
            fields[key] = value
    if fields != required:
        raise ValueError("RELEASE_WHEEL_IDENTITY_MISMATCH")
    wheel_tags = [line.split(": ", 1)[1] for line in archive.read(wheel_name).decode("utf-8").splitlines()
                  if line.startswith("Tag: ")]
    if wheel_tags != [expected_tag]:
        raise ValueError("RELEASE_WHEEL_TAG_MISMATCH")
    rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    if not rows or any(len(row) != 3 for row in rows):
        raise ValueError("INVALID_RELEASE_WHEEL_RECORD")
    records = {}
    for name, digest, size in rows:
        if name in records:
            raise ValueError("DUPLICATE_RELEASE_WHEEL_RECORD")
        records[name] = (digest, size)
    payload_names = {entry.filename for entry in entries if not entry.is_dir()}
    if set(records) != payload_names:
        raise ValueError("RELEASE_WHEEL_RECORD_COVERAGE_MISMATCH")
    for name in payload_names:
        if name == record_name:
            if records[name] != ("", ""):
                raise ValueError("INVALID_RELEASE_WHEEL_RECORD_SELF_ENTRY")
            continue
        raw_member = archive.read(name)
        if records[name] != (_record_digest(raw_member), str(len(raw_member))):
            raise ValueError("RELEASE_WHEEL_RECORD_MISMATCH")
    return archive, requirements


def verify_release_pair(*, receipt_raw, trusted_receipt_sha256, sdk_raw, runtime_raw):
    if (not isinstance(trusted_receipt_sha256, str)
            or not SHA256.fullmatch(trusted_receipt_sha256)
            or _digest(receipt_raw) != trusted_receipt_sha256):
        raise ValueError("UNTRUSTED_RELEASE_RECEIPT")
    receipt = _unique_json(receipt_raw)
    required = {"kind", "sourceCommit", "version", "platform", "builderImage",
                "applicationImage", "sdkWheel", "runtimeWheel", "sdkWheelSha256",
                "runtimeWheelSha256", "sdkWheelSize", "runtimeWheelSize"}
    if (not isinstance(receipt, dict) or set(receipt) != required
            or receipt["kind"] != "DSH_OFFICIAL_SDK_RELEASE_V1"
            or receipt["sourceCommit"] != SOURCE or receipt["version"] != VERSION
            or receipt["platform"] != "manylinux_2_28_x86_64"
            or receipt["sdkWheel"] != SDK_NAME or receipt["runtimeWheel"] != RUNTIME_NAME
            or not IMAGE.fullmatch(receipt["builderImage"])
            or not IMAGE.fullmatch(receipt["applicationImage"])
            or not SHA256.fullmatch(receipt["sdkWheelSha256"])
            or not SHA256.fullmatch(receipt["runtimeWheelSha256"])
            or type(receipt["sdkWheelSize"]) is not int or receipt["sdkWheelSize"] != len(sdk_raw)
            or type(receipt["runtimeWheelSize"]) is not int or receipt["runtimeWheelSize"] != len(runtime_raw)):
        raise ValueError("INVALID_RELEASE_RECEIPT")
    if _digest(sdk_raw) != receipt["sdkWheelSha256"]:
        raise ValueError("SDK_RELEASE_HASH_MISMATCH")
    if _digest(runtime_raw) != receipt["runtimeWheelSha256"]:
        raise ValueError("RUNTIME_RELEASE_HASH_MISMATCH")
    sdk, requirements = _wheel(sdk_raw, "deepseek-harness-sdk", "py3-none-any",
                               max_wheel=MAX_SDK_WHEEL, max_member=MAX_SDK_MEMBER)
    runtime, _ = _wheel(runtime_raw, "deepseek-harness-runtime-bin",
                        "py3-none-manylinux_2_28_x86_64",
                        max_wheel=MAX_RUNTIME_WHEEL, max_member=MAX_RUNTIME_MEMBER)
    if "deepseek_harness/__init__.py" not in sdk.namelist():
        raise ValueError("SDK_PACKAGE_ENTRY_REQUIRED")
    expected = f"deepseek-harness-runtime-bin=={VERSION}"
    if requirements.count(expected) != 1:
        raise ValueError("SDK_RUNTIME_DEPENDENCY_MISMATCH")
    runtime_path = "deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64"
    runtime_entries = [name for name in runtime.namelist() if name == runtime_path]
    if len(runtime_entries) != 1:
        raise ValueError("RUNTIME_EXECUTABLE_REQUIRED")
    runtime_binary = runtime.read(runtime_entries[0])
    # ELF64, little endian, version 1, machine EM_X86_64 (62).
    if (len(runtime_binary) < 64 or runtime_binary[:7] != b"\x7fELF\x02\x01\x01"
            or int.from_bytes(runtime_binary[18:20], "little") != 62):
        raise ValueError("RUNTIME_EXECUTABLE_IDENTITY_MISMATCH")
    return {
        "kind": "DSH_OFFICIAL_SDK_RELEASE_VERIFIED_V1",
        "sourceCommit": SOURCE,
        "sdkVersion": VERSION,
        "runtimeVersion": VERSION,
        "platform": receipt["platform"],
        "builderImage": receipt["builderImage"],
        "applicationImage": receipt["applicationImage"],
        "sdkWheelSha256": receipt["sdkWheelSha256"],
        "runtimeWheelSha256": receipt["runtimeWheelSha256"],
        "sdkWheelSize": receipt["sdkWheelSize"],
        "runtimeWheelSize": receipt["runtimeWheelSize"],
        "runtimeSha256": _digest(runtime_binary),
        "receiptSha256": _digest(receipt_raw),
    }
