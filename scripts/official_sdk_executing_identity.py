"""Candidate Linux mount-backed executing-Pod identity reader.

Consumes only three fixed NONSECRET Downward API fields and kernel mountinfo.
It never uses environment identity, service-account tokens, passwords or keys.
Real RKE2/kubelet mount-root compatibility and the protected profile require
physical qualification before wiring; unsupported layouts refuse, not guess.
"""
import os
from pathlib import Path
import re
import sys

from scripts.official_sdk_package_admission import protected_bytes
from scripts.official_sdk_test_api import name

ROOT = Path("/run/dsh-executing-identity")
MOUNTINFO = Path("/proc/self/mountinfo")
VOLUME = "dsh-executing-identity"
FIELDS = {"pod-uid": "metadata.uid", "pod-name": "metadata.name", "namespace": "metadata.namespace"}
UID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")


def read_fixed(path, limit):
    if path in {ROOT / field for field in FIELDS}:
        return protected_bytes(path, limit)
    if path != MOUNTINFO: raise ValueError("UNADMITTED_EXECUTING_IDENTITY_PATH")
    # Fixed kernel interface, no caller-selected /proc PID or file path.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb", closefd=False) as stream: raw = stream.read(limit + 1)
        if len(raw) > limit: raise ValueError("EXECUTING_MOUNTINFO_TOO_LARGE")
        return raw
    finally: os.close(fd)


def unescape(value):
    allowed = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}
    def replace(match):
        if match.group(1) not in allowed: raise ValueError("INVALID_KERNEL_MOUNT_ESCAPE")
        return allowed[match.group(1)]
    result = re.sub(r"\\([0-9]{3})", replace, value)
    if "\\" in result: raise ValueError("INVALID_KERNEL_MOUNT_PATH")
    return result


def verify_mounts(raw, pod_uid, container):
    found = {str(ROOT / field): [] for field in FIELDS}
    for line in raw.decode("utf-8").splitlines():
        parts = line.split(" - ")
        if len(parts) != 2: raise ValueError("INVALID_KERNEL_MOUNTINFO")
        left = parts[0].split(); right = parts[1].split()
        if len(left) < 6 or len(right) < 3: raise ValueError("INVALID_KERNEL_MOUNTINFO")
        point = unescape(left[4])
        if point in found: found[point].append((unescape(left[3]), left[5].split(",")))
    for field in FIELDS:
        entries = found[str(ROOT / field)]
        if len(entries) != 1: raise ValueError("EXECUTING_IDENTITY_MOUNT_AMBIGUOUS")
        root, options = entries[0]
        if "ro" not in options or "rw" in options or ".." in Path(root).parts:
            raise ValueError("EXECUTING_IDENTITY_MOUNT_NOT_READONLY")
        # Only declared kubelet Downward API file/subPath roots. These patterns
        # are a candidate profile, not evidence that a live node uses them.
        prefix = r"/(?:[^/]+/)*pods/" + re.escape(pod_uid) + "/"
        direct = prefix + r"volumes/kubernetes\.io~downward-api/" + VOLUME + r"/(?:\.\.[^/]+/)?" + re.escape(field)
        subpath = prefix + r"volume-subpaths/" + VOLUME + "/" + re.escape(container) + r"/[0-9]+"
        if not re.fullmatch(direct, root) and not re.fullmatch(subpath, root):
            raise ValueError("EXECUTING_IDENTITY_KERNEL_POD_BINDING_MISMATCH")


class ExecutingPodIdentity:
    def __init__(self, *, read_resource, namespace, namespace_uid, pod_name, pod_uid,
                 container_name, reader=read_fixed):
        if not callable(read_resource): raise ValueError("PROTECTED_FIXED_API_REQUIRED")
        self.namespace = name(namespace, namespace=True); self.pod_name = name(pod_name)
        self.container = name(container_name, namespace=True)
        if not UID.fullmatch(str(namespace_uid)) or not UID.fullmatch(str(pod_uid)):
            raise ValueError("EXACT_EXECUTING_IDENTITY_UID_REQUIRED")
        self.namespace_uid, self.pod_uid = namespace_uid, pod_uid
        self.read, self.reader = read_resource, reader

    def __call__(self):
        if sys.platform != "linux": raise ValueError("EXECUTING_IDENTITY_REQUIRES_LINUX")
        values = {field: self.reader(ROOT / field, 256).decode("ascii").strip() for field in FIELDS}
        if values != {"pod-uid": self.pod_uid, "pod-name": self.pod_name, "namespace": self.namespace}:
            raise ValueError("EXECUTING_DOWNWARD_IDENTITY_MISMATCH")
        mounts = self.reader(MOUNTINFO, 256 * 1024)
        verify_mounts(mounts, self.pod_uid, self.container)
        ns = self.read("Namespace", "v1", None, self.namespace)
        pod = self.read("Pod", "v1", self.namespace, self.pod_name)
        if (not isinstance(ns, dict) or ns.get("kind") != "Namespace" or ns.get("apiVersion") != "v1"
                or ns.get("metadata", {}).get("name") != self.namespace
                or ns["metadata"].get("uid") != self.namespace_uid or ns["metadata"].get("deletionTimestamp")
                or not isinstance(pod, dict) or pod.get("kind") != "Pod" or pod.get("apiVersion") != "v1"
                or pod.get("metadata", {}).get("uid") != self.pod_uid
                or pod["metadata"].get("name") != self.pod_name or pod["metadata"].get("namespace") != self.namespace
                or pod["metadata"].get("deletionTimestamp")):
            raise ValueError("EXECUTING_API_IDENTITY_MISMATCH")
        spec = pod.get("spec", {}); containers = spec.get("containers", [])
        if (len(containers) != 1 or containers[0].get("name") != self.container
                or spec.get("initContainers") or spec.get("ephemeralContainers")):
            raise ValueError("EXECUTING_CONTAINER_NOT_UNIQUE")
        if any(spec.get(key, False) is not False for key in ("hostPID", "hostIPC", "hostNetwork", "shareProcessNamespace")):
            raise ValueError("EXECUTING_HOST_NAMESPACE_REFUSED")
        security = containers[0].get("securityContext", {})
        if (security.get("privileged", False) is not False or security.get("allowPrivilegeEscalation") is not False
                or security.get("readOnlyRootFilesystem") is not True
                or security.get("capabilities", {}).get("drop") != ["ALL"]
                or security.get("capabilities", {}).get("add", [])):
            raise ValueError("EXECUTING_MOUNT_TAMPER_CAPABILITY_REFUSED")
        volumes = [v for v in spec.get("volumes", []) if v.get("name") == VOLUME]
        if len(volumes) != 1 or set(volumes[0]) != {"name", "downwardAPI"}:
            raise ValueError("EXECUTING_DOWNWARD_VOLUME_REQUIRED")
        projection = volumes[0]["downwardAPI"]
        expected_items = [{"path": field, "fieldRef": {"apiVersion": "v1", "fieldPath": source}} for field, source in FIELDS.items()]
        if projection != {"defaultMode": 0o444, "items": expected_items}:
            raise ValueError("EXECUTING_DOWNWARD_FIELD_BINDING_MISMATCH")
        expected_mounts = [{"name": VOLUME, "mountPath": str(ROOT / field), "subPath": field, "readOnly": True} for field in FIELDS]
        mounts_spec = [m for m in containers[0].get("volumeMounts", []) if m.get("name") == VOLUME or str(m.get("mountPath", "")).startswith(str(ROOT))]
        if mounts_spec != expected_mounts: raise ValueError("EXECUTING_DOWNWARD_MOUNT_SPEC_MISMATCH")
        if self.reader(MOUNTINFO, 256 * 1024) != mounts:
            raise ValueError("EXECUTING_KERNEL_MOUNTS_CHANGED")
        for field, value in values.items():
            if self.reader(ROOT / field, 256).decode("ascii").strip() != value:
                raise ValueError("EXECUTING_DOWNWARD_IDENTITY_CHANGED")
        return {"namespace": self.namespace, "namespaceUID": self.namespace_uid,
                "podUID": self.pod_uid, "container": self.container}
