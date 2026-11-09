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
import stat
import zipfile


VERSION = "0.2.2a2"
SOURCE = "ce7073d51254c26cd63b22a60835b8f948deb447"
SOURCE_TREE = "d3c6ee1d1f0ec8b71c92e1b62d0cf9a8d6553bf8"
PNPM_LOCK_SHA256 = "6dbb7b4d0117aa2a69d19e348cb22e2b46eba5b11af146ab24b7a2bcc3a9b86c"
SDK_NAME = f"deepseek_harness_sdk-{VERSION}-py3-none-any.whl"
RUNTIME_NAME = f"deepseek_harness_runtime_bin-{VERSION}-py3-none-manylinux_2_28_x86_64.whl"
SHA256 = re.compile(r"[a-f0-9]{64}")
IMAGE = re.compile(r"[^\s@]+@sha256:[a-f0-9]{64}")
MAX_SDK_WHEEL = 16 * 1024 * 1024
MAX_RUNTIME_WHEEL = 512 * 1024 * 1024
MAX_SDK_MEMBER = 8 * 1024 * 1024
MAX_RUNTIME_MEMBER = 384 * 1024 * 1024
MAX_MEMBERS = 10000
RUNTIME_ROOT = "deepseek_harness_runtime/runtime/"
RUNTIME_EXE = "deepseek-harness-sdk-runtime-linux-x64"


def _immutable_image(value):
    return isinstance(value, str) and IMAGE.fullmatch(value) and not value.endswith(":" + "0" * 64)


def _runtime_payload(archive):
    """Read the pinned upstream Linux payload contract without executing it.

    ce7073 build-python-release.py requires the executable, its rg companion,
    and linux-x64 resources. Its _resources.validate_downloads checks this
    manifest and all three Office skill entry files. These are packaging
    checks, not proof the binaries run or that resource downloads are approved.
    """
    names = [entry.filename for entry in archive.infolist()
             if entry.filename.startswith(RUNTIME_ROOT) and not entry.is_dir()]
    found = {name[len(RUNTIME_ROOT):].split("/", 1)[0] for name in names}
    if found != {RUNTIME_EXE, RUNTIME_EXE + "-rg", "linux-x64"}:
        raise ValueError("RUNTIME_PAYLOAD_CLOSURE_REQUIRED")
    binaries = {}
    for filename in (RUNTIME_EXE, RUNTIME_EXE + "-rg"):
        if RUNTIME_ROOT + filename not in names:
            raise ValueError("RUNTIME_PAYLOAD_CLOSURE_REQUIRED")
        entry = archive.getinfo(RUNTIME_ROOT + filename)
        mode = entry.external_attr >> 16
        if not stat.S_ISREG(mode) or not mode & stat.S_IXUSR:
            raise ValueError("RUNTIME_EXECUTABLE_MODE_REQUIRED")
        raw = archive.read(entry)
        if (len(raw) < 64 or raw[:7] != b"\x7fELF\x02\x01\x01"
                or int.from_bytes(raw[18:20], "little") != 62):
            raise ValueError("RUNTIME_EXECUTABLE_IDENTITY_MISMATCH")
        binaries[filename] = _digest(raw)
    resources = RUNTIME_ROOT + "linux-x64/"
    manifest_name = resources + "downloads.json"
    if manifest_name not in names or archive.getinfo(manifest_name).file_size > 65536:
        raise ValueError("RUNTIME_DOWNLOAD_MANIFEST_REQUIRED")
    manifest = _unique_json(archive.read(manifest_name))
    if (not isinstance(manifest, dict) or manifest.get("target") != "linux-x64"
            or not isinstance(manifest.get("identity"), str)
            or not SHA256.fullmatch(manifest["identity"])
            or not isinstance(manifest.get("office"), list) or not manifest["office"]
            or not isinstance(manifest.get("pnpm"), dict)):
        raise ValueError("RUNTIME_DOWNLOAD_MANIFEST_MISMATCH")
    for kind in ("docx", "pptx", "xlsx"):
        if resources + f"office-skills/office-{kind}/SKILL.md" not in names:
            raise ValueError("RUNTIME_OFFICE_SKILL_REQUIRED")
    return binaries, manifest["identity"]


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


def _verify_pair(*, receipt_raw, trusted_receipt_sha256, sdk_raw, runtime_raw, producer):
    if (not isinstance(trusted_receipt_sha256, str)
            or not SHA256.fullmatch(trusted_receipt_sha256)
            or _digest(receipt_raw) != trusted_receipt_sha256):
        raise ValueError("UNTRUSTED_RELEASE_RECEIPT")
    receipt = _unique_json(receipt_raw)
    required = {"kind", "sourceCommit", "version", "platform", "builderImage",
                "applicationImage", "sdkWheel", "runtimeWheel", "sdkWheelSha256",
                "runtimeWheelSha256", "sdkWheelSize", "runtimeWheelSize"}
    if producer:
        required.remove("applicationImage")
        required.update({"sourceTree", "pnpmLockSha256", "manylinuxImage",
                         "nodeVersion", "pnpmVersion", "uvVersion", "operationId"})
    expected_kind = "DSH_OFFICIAL_SDK_PRODUCER_V1" if producer else "DSH_OFFICIAL_SDK_RELEASE_V1"
    if (not isinstance(receipt, dict) or set(receipt) != required
            or receipt["kind"] != expected_kind
            or receipt["sourceCommit"] != SOURCE or receipt["version"] != VERSION
            or receipt["platform"] != "manylinux_2_28_x86_64"
            or receipt["sdkWheel"] != SDK_NAME or receipt["runtimeWheel"] != RUNTIME_NAME
            or not _immutable_image(receipt["builderImage"])
            or (not producer and not _immutable_image(receipt["applicationImage"]))
            or not isinstance(receipt["sdkWheelSha256"], str) or not SHA256.fullmatch(receipt["sdkWheelSha256"])
            or not isinstance(receipt["runtimeWheelSha256"], str) or not SHA256.fullmatch(receipt["runtimeWheelSha256"])
            or type(receipt["sdkWheelSize"]) is not int or receipt["sdkWheelSize"] != len(sdk_raw)
            or type(receipt["runtimeWheelSize"]) is not int or receipt["runtimeWheelSize"] != len(runtime_raw)):
        raise ValueError("INVALID_RELEASE_RECEIPT")
    if producer:
        node = re.fullmatch(r"v24\.(\d+)\.(\d+)", str(receipt["nodeVersion"]))
        if (receipt["sourceTree"] != SOURCE_TREE or receipt["pnpmLockSha256"] != PNPM_LOCK_SHA256
                or not _immutable_image(receipt["manylinuxImage"])
                or node is None or int(node[1]) < 9
                or receipt["pnpmVersion"] != "11.28.5" or receipt["uvVersion"] != "0.11.23"
                or not re.fullmatch(r"[a-f0-9]{32}", str(receipt["operationId"]))
                or receipt["operationId"] == "0" * 32):
            raise ValueError("INVALID_PRODUCER_BUILD_BINDING")
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
    binaries, resource_identity = _runtime_payload(runtime)
    result = {
        "kind": "DSH_OFFICIAL_SDK_PRODUCER_VERIFIED_V1" if producer else "DSH_OFFICIAL_SDK_RELEASE_VERIFIED_V1",
        "sourceCommit": SOURCE,
        "sdkVersion": VERSION,
        "runtimeVersion": VERSION,
        "platform": receipt["platform"],
        "builderImage": receipt["builderImage"],
        "sdkWheelSha256": receipt["sdkWheelSha256"],
        "runtimeWheelSha256": receipt["runtimeWheelSha256"],
        "sdkWheelSize": receipt["sdkWheelSize"],
        "runtimeWheelSize": receipt["runtimeWheelSize"],
        "runtimeSha256": _digest(runtime_binary),
        "ripgrepSha256": binaries[RUNTIME_EXE + "-rg"],
        "resourceManifestIdentity": resource_identity,
        "receiptSha256": _digest(receipt_raw),
    }
    if producer:
        result.update(sourceTree=SOURCE_TREE, pnpmLockSha256=PNPM_LOCK_SHA256,
                      manylinuxImage=receipt["manylinuxImage"], operationId=receipt["operationId"],
                      applicationImageBound=False)
    else:
        result["applicationImage"] = receipt["applicationImage"]
    return result


def verify_release_pair(*, receipt_raw, trusted_receipt_sha256, sdk_raw, runtime_raw):
    """Verify actual wheel content and its separately observed final image binding."""
    return _verify_pair(receipt_raw=receipt_raw, trusted_receipt_sha256=trusted_receipt_sha256,
                        sdk_raw=sdk_raw, runtime_raw=runtime_raw, producer=False)


def verify_producer_pair(*, receipt_raw, trusted_receipt_sha256, sdk_raw, runtime_raw):
    """Verify pre-image build output, without fabricating a final image digest.

    The returned producer receipt is not runtime admission. Actual application
    image observation and the final release receipt remain separate gates.
    """
    return _verify_pair(receipt_raw=receipt_raw, trusted_receipt_sha256=trusted_receipt_sha256,
                        sdk_raw=sdk_raw, runtime_raw=runtime_raw, producer=True)


# ---------------------------------------------------------------------------------------------------------------------
# Additive: evidence for a producer run on Kubernetes (SDK_PRODUCER_K8S_PLAN.md, section 8). Nothing above this line
# is changed. The producer receipt of a Kubernetes run is the ordinary DSH_OFFICIAL_SDK_PRODUCER_V1 receipt (checked by
# verify_producer_pair); this separate sealed document proves how it was produced.
K8S_EVIDENCE_KIND = "DSH_OFFICIAL_SDK_PRODUCER_K8S_EVIDENCE_V1"
K8S_VERIFIED_KIND = "DSH_OFFICIAL_SDK_PRODUCER_K8S_VERIFIED_V1"
K8S_STAGE_ORDER = ("seed", "prepare", "manylinux", "compile")
K8S_MAX_SECONDS = 10800
_K8S_KEYS = {"kind", "operationId", "producerReceiptSha256", "specSha256", "spec", "objects", "events",
             "workMountLine", "outputSha256Lines", "sourceBoundLogs", "startedAt", "finishedAt"}


def _k8s_time(value):
    import datetime
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("K8S_EVIDENCE_TIME_INVALID")
    return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)


def _k8s_digest_of(image):
    return image.rsplit("@sha256:", 1)[1]


def _load_pinned_generator(path, trusted_sha256):
    import types
    raw = Path(path).read_bytes()
    if not isinstance(trusted_sha256, str) or not SHA256.fullmatch(trusted_sha256) or _digest(raw) != trusted_sha256:
        raise ValueError("K8S_GENERATOR_NOT_PINNED")
    module = types.ModuleType("dsh_bound_sdk_producer_k8s")
    module.__file__ = str(path)
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _k8s_terminated(status, name, expected_image):
    state = status.get("state", {}).get("terminated")
    if (not isinstance(state, dict) or state.get("exitCode") != 0 or status.get("restartCount") != 0
            or status.get("name") != name):
        raise ValueError("K8S_CONTAINER_NOT_CLEAN_SUCCESS")
    image_id = str(status.get("imageID", ""))
    if not image_id.endswith("@sha256:" + _k8s_digest_of(expected_image)):
        raise ValueError("K8S_IMAGE_DIGEST_THAT_RAN_NOT_ADMITTED")
    return _k8s_time(state.get("startedAt")), _k8s_time(state.get("finishedAt"))


def verify_k8s_producer_evidence(*, evidence_raw, trusted_evidence_sha256, producer_receipt_raw,
                                 trusted_producer_receipt_sha256, trusted_spec_sha256,
                                 generator_path, trusted_generator_sha256):
    """Verify the sealed evidence of a Kubernetes producer run against its producer receipt.

    The trusted hashes arrive through a separate channel. The wheels themselves are verified by
    verify_producer_pair; this checks how the run was bounded. Returns a result; raises ValueError otherwise."""
    for value in (trusted_evidence_sha256, trusted_producer_receipt_sha256, trusted_spec_sha256):
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            raise ValueError("UNTRUSTED_K8S_EVIDENCE")
    if _digest(evidence_raw) != trusted_evidence_sha256 or _digest(producer_receipt_raw) != trusted_producer_receipt_sha256:
        raise ValueError("UNTRUSTED_K8S_EVIDENCE")
    evidence = _unique_json(evidence_raw)
    receipt = _unique_json(producer_receipt_raw)
    if not isinstance(evidence, dict) or set(evidence) != _K8S_KEYS or evidence["kind"] != K8S_EVIDENCE_KIND:
        raise ValueError("INVALID_K8S_EVIDENCE")
    if not isinstance(receipt, dict) or receipt.get("kind") != "DSH_OFFICIAL_SDK_PRODUCER_V1":
        raise ValueError("PRODUCER_RECEIPT_REQUIRED")
    if (evidence["producerReceiptSha256"] != trusted_producer_receipt_sha256
            or evidence["operationId"] != receipt.get("operationId")):
        raise ValueError("K8S_EVIDENCE_NOT_BOUND_TO_RECEIPT")
    spec = evidence["spec"]
    if (not isinstance(spec, dict) or evidence["specSha256"] != trusted_spec_sha256
            or _digest(json.dumps(spec, sort_keys=True).encode()) != trusted_spec_sha256
            or spec.get("operationId") != receipt["operationId"]
            or spec.get("builderImage") != receipt.get("builderImage")
            or spec.get("manylinuxImage") != receipt.get("manylinuxImage")
            or not _immutable_image(spec.get("builderImage")) or not _immutable_image(spec.get("manylinuxImage"))):
        raise ValueError("K8S_SPEC_NOT_BOUND_TO_RECEIPT")
    generator = _load_pinned_generator(generator_path, trusted_generator_sha256)
    objects = evidence["objects"]
    try:
        generator.check_objects(objects, spec)
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise ValueError("K8S_OBJECT_READBACK_REFUSED:" + str(error)) from error
    for key in ("pod-fetch", "pod-build"):
        pod = objects[key]
        if pod["metadata"].get("annotations", {}).get("dsh.sdk/spec-sha256") != trusted_spec_sha256:
            raise ValueError("K8S_POD_NOT_FROM_ADMITTED_SPEC")
        if pod["spec"].get("ephemeralContainers") or pod.get("status", {}).get("ephemeralContainerStatuses"):
            raise ValueError("K8S_EPHEMERAL_CONTAINER_PRESENT")
        if pod.get("status", {}).get("phase") != "Succeeded":
            raise ValueError("K8S_POD_NOT_SUCCEEDED")
    fetch_status = objects["pod-fetch"]["status"].get("containerStatuses", [])
    if len(fetch_status) != 1:
        raise ValueError("K8S_FETCH_STATUS_INVALID")
    first_start, previous_end = _k8s_terminated(fetch_status[0], "fetch", spec["builderImage"])
    build_status = objects["pod-build"]["status"]
    init = build_status.get("initContainerStatuses", [])
    if [item.get("name") for item in init] != list(K8S_STAGE_ORDER):
        raise ValueError("K8S_STAGE_STATUS_ORDER")
    images = {"seed": spec["builderImage"], "prepare": spec["builderImage"],
              "manylinux": spec["manylinuxImage"], "compile": spec["builderImage"]}
    for item in init:
        start, end = _k8s_terminated(item, item["name"], images[item["name"]])
        if start < previous_end or end < start:
            raise ValueError("K8S_STAGE_TIMES_NOT_SEQUENTIAL")
        previous_end = end
    emit_status = build_status.get("containerStatuses", [])
    if len(emit_status) != 1:
        raise ValueError("K8S_EMIT_STATUS_INVALID")
    emit_start, emit_end = _k8s_terminated(emit_status[0], "emit", spec["builderImage"])
    if emit_start < previous_end:
        raise ValueError("K8S_STAGE_TIMES_NOT_SEQUENTIAL")
    if objects["pod-build"]["spec"]["nodeName"] != spec["nodeName"]:
        raise ValueError("K8S_NODE_MISMATCH")
    started, finished = _k8s_time(evidence["startedAt"]), _k8s_time(evidence["finishedAt"])
    if not (started <= first_start and emit_end <= finished and (finished - started).total_seconds() <= K8S_MAX_SECONDS):
        raise ValueError("K8S_TIME_WINDOW_REFUSED")
    events = evidence["events"]
    names = {objects["pod-fetch"]["metadata"]["name"], objects["pod-build"]["metadata"]["name"]}
    if not isinstance(events, list) or not events:
        raise ValueError("K8S_EVENTS_REQUIRED")
    for event in events:
        if (not isinstance(event, dict) or set(event) != {"object", "type", "reason", "count"}
                or event["object"] not in names or event["type"] != "Normal"):
            raise ValueError("K8S_WARNING_OR_FOREIGN_EVENT")
    for name in names:
        if not any(e["object"] == name and e["reason"] == "Started" for e in events):
            raise ValueError("K8S_EVENTS_INCOMPLETE")
    line = evidence["workMountLine"]
    match = re.fullmatch(r"tmpfs /work tmpfs (\S+) 0 0", str(line).strip())
    size = re.search(r"(?:^|,)size=(\d+)k(?:,|$)", match.group(1)) if match else None
    if not match or not size or int(size.group(1)) * 1024 > spec["limits"]["workspaceBytes"]:
        raise ValueError("K8S_WORKSPACE_NOT_BOUNDED_TMPFS")
    hashes = {}
    for entry in evidence["outputSha256Lines"]:
        parts = str(entry).split("  ", 1)
        if len(parts) != 2 or not SHA256.fullmatch(parts[0]) or parts[1] in hashes:
            raise ValueError("K8S_OUTPUT_LIST_INVALID")
        hashes[parts[1]] = parts[0]
    if (hashes.get("./wheels/" + SDK_NAME) != receipt.get("sdkWheelSha256")
            or hashes.get("./wheels/" + RUNTIME_NAME) != receipt.get("runtimeWheelSha256")):
        raise ValueError("K8S_OUTPUT_HASH_MISMATCH")
    if evidence["sourceBoundLogs"] != ["SOURCE_BOUND"]:
        raise ValueError("K8S_SOURCE_BINDING_MISSING")
    return {"kind": K8S_VERIFIED_KIND, "producerRuntime": "kubernetes", "applicationImageBound": False,
            "operationId": receipt["operationId"], "node": spec["nodeName"], "namespace": spec["namespace"],
            "builderImage": spec["builderImage"], "manylinuxImage": spec["manylinuxImage"],
            "producerReceiptSha256": trusted_producer_receipt_sha256, "specSha256": trusted_spec_sha256,
            "evidenceSha256": trusted_evidence_sha256, "generatorSha256": trusted_generator_sha256,
            "sdkWheelSha256": receipt["sdkWheelSha256"], "runtimeWheelSha256": receipt["runtimeWheelSha256"]}
