"""Linux mount-backed executing-Pod identity reader (REDESIGN DRAFT, not reviewed, not merged).

Consumes only three fixed NONSECRET Downward API fields and kernel mountinfo.
It never uses environment identity, service-account tokens, passwords or keys.
Unsupported layouts refuse, not guess.

Layout OBSERVED on this RKE2/containerd node (probe OPERATOR-P3-IDENTITY-PROBE, 10 Nov 2026, Pod identity-probe): the three subPath files are bind mounts of
files of the kubelet's own tmpfs for the downward-API volume, so their mount ROOT is relative to that tmpfs, e.g.
    /..2026_11_10_14_37_31.3061124380/pod-uid   mount point /run/dsh-executing-identity/pod-uid   ro,relatime  tmpfs tmpfs  device 0:2391 (the same for all three)
It has NO pods/<podUID> prefix: the earlier candidate patterns could never match, and no field of these three lines carries the Pod UID. The Pod UID and the
container name are therefore bound by two KUBELET-OWNED bind mounts of the same mount namespace (K1: /etc/hosts and /dev/termination-log, whose roots carry
pods/<podUID>/ and, for the termination log, containers/<container>/), and the volume name and field by the exact API spec (volume, items, mounts) plus the layout
of the three tmpfs mounts (K2). K1 layout is the DOCUMENTED kubelet layout and is PENDING confirmation by a second probe on this node.
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


# K2: the kubelet AtomicWriter directory inside the downward-API tmpfs, e.g. ..2026_11_10_14_37_31.3061124380 (observed). Never a pods/<uid> path.
TMPFS_DIR = re.compile(r"/\.\.[0-9]{4}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}_[0-9]{2}\.[0-9]{1,12}")
KUBELET_POINTS = ("/etc/hosts", "/dev/termination-log")   # K1: kubelet-created bind mounts of THIS container; their roots carry the Pod UID


def mount_entries(raw, points):
    found = {point: [] for point in points}
    for line in raw.decode("utf-8").splitlines():
        parts = line.split(" - ")
        if len(parts) != 2: raise ValueError("INVALID_KERNEL_MOUNTINFO")
        left = parts[0].split(); right = parts[1].split()
        if len(left) < 6 or len(right) < 3: raise ValueError("INVALID_KERNEL_MOUNTINFO")
        point = unescape(left[4])
        if point in found:
            found[point].append({"device": left[2], "root": unescape(left[3]), "options": left[5].split(","), "fstype": right[0], "source": right[1]})
    return found


def verify_mounts(raw, pod_uid, container):
    points = {field: ROOT.as_posix() + "/" + field for field in FIELDS}
    found = mount_entries(raw, list(points.values()) + list(KUBELET_POINTS))
    directories, devices = set(), set()
    for field, point in points.items():
        entries = found[point]
        if len(entries) != 1: raise ValueError("EXECUTING_IDENTITY_MOUNT_AMBIGUOUS")
        entry = entries[0]
        if "ro" not in entry["options"] or "rw" in entry["options"] or ".." in Path(entry["root"]).parts:
            raise ValueError("EXECUTING_IDENTITY_MOUNT_NOT_READONLY")
        # K2: a file of the kubelet's own tmpfs, inside one AtomicWriter directory, named exactly like its field
        directory, _, leaf = entry["root"].rpartition("/")
        if entry["fstype"] != "tmpfs" or entry["source"] != "tmpfs" or leaf != field or not TMPFS_DIR.fullmatch(directory):
            raise ValueError("EXECUTING_IDENTITY_KERNEL_VOLUME_LAYOUT_MISMATCH")
        directories.add(directory); devices.add(entry["device"])
    # one tmpfs instance and one AtomicWriter generation for all three fields (never a mixture of mounts)
    if len(directories) != 1 or len(devices) != 1: raise ValueError("EXECUTING_IDENTITY_KERNEL_VOLUME_LAYOUT_MISMATCH")
    # K1: bind this mount namespace to the Pod UID and the container name through the kubelet's own mounts
    prefix = r"/(?:[^/]+/)*pods/" + re.escape(pod_uid) + "/"
    expected = {"/etc/hosts": prefix + r"etc-hosts",
                "/dev/termination-log": prefix + r"containers/" + re.escape(container) + r"/[0-9a-f]{8}"}
    for point, pattern in expected.items():
        entries = found[point]
        if len(entries) != 1: raise ValueError("EXECUTING_POD_BINDING_MOUNT_MISSING_OR_AMBIGUOUS")
        if not re.fullmatch(pattern, entries[0]["root"]): raise ValueError("EXECUTING_IDENTITY_KERNEL_POD_BINDING_MISMATCH")


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
