"""Synthetic Linux mount/Downward/API snapshots; no host or cluster probing."""
import copy
from pathlib import PurePosixPath
import unittest
from unittest.mock import patch
from scripts import official_sdk_executing_identity as identity


class ExecutingIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root_patch = patch.object(identity, "ROOT", PurePosixPath("/run/dsh-executing-identity")); self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        self.proc_patch = patch.object(identity, "MOUNTINFO", PurePosixPath("/proc/self/mountinfo")); self.proc_patch.start(); self.addCleanup(self.proc_patch.stop)
        self.platform = patch.object(identity.sys, "platform", "linux"); self.platform.start(); self.addCleanup(self.platform.stop)
        self.uid = "22222222-2222-2222-2222-222222222222"; self.ns_uid = "11111111-1111-1111-1111-111111111111"
        self.namespace = "dsh-sdk-test"; self.pod_name = "qualification-pod"
        self.files = {identity.ROOT / "pod-uid": self.uid.encode(), identity.ROOT / "pod-name": self.pod_name.encode(),
            identity.ROOT / "namespace": self.namespace.encode()}
        self.lines = []
        for index, field in enumerate(identity.FIELDS):   # K2: verbatim shape of the probe on the RKE2 node (OPERATOR-P3-IDENTITY-PROBE, 10 Nov 2026)
            self.lines.append(f"{27420+index} 27406 0:2391 /..2026_11_10_14_37_31.3061124380/{field} {identity.ROOT / field} ro,relatime - tmpfs tmpfs rw,seclabel,size=131072k,inode64")
        self.k1 = [f"30 27406 253:1 /var/lib/kubelet/pods/{self.uid}/etc-hosts /etc/hosts rw,relatime - xfs /dev/synthetic rw",
                   f"31 27406 253:1 /var/lib/kubelet/pods/{self.uid}/containers/broker/a1b2c3d4 /dev/termination-log rw,relatime - xfs /dev/synthetic rw"]
        self.files[identity.MOUNTINFO] = ("\n".join(self.lines + self.k1) + "\n").encode()
        self.ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": self.namespace, "uid": self.ns_uid}}
        self.pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": self.pod_name, "namespace": self.namespace, "uid": self.uid},
            "spec": {"containers": [{"name": "broker", "securityContext": {"allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                "volumeMounts": [{"name": identity.VOLUME, "mountPath": str(identity.ROOT / field),
                    "subPath": field, "readOnly": True} for field in identity.FIELDS]}],
                "volumes": [{"name": identity.VOLUME, "downwardAPI": {"defaultMode": 0o444,
                    "items": [{"path": field, "fieldRef": {"apiVersion": "v1", "fieldPath": source}}
                        for field, source in identity.FIELDS.items()]}}]}}
        self.reads = []; self.calls = []
        def reader(path, limit):
            self.reads.append(path); raw = self.files[path]
            if len(raw) > limit: raise ValueError("synthetic oversize")
            return raw
        def api(kind, version, namespace, name):
            self.calls.append((kind, version, namespace, name))
            return copy.deepcopy(self.ns if kind == "Namespace" else self.pod)
        self.attestor = identity.ExecutingPodIdentity(read_resource=api, reader=reader,
            namespace=self.namespace, namespace_uid=self.ns_uid, pod_name=self.pod_name,
            pod_uid=self.uid, container_name="broker")
    def test_bound_projection_kernel_mount_and_api_identity(self):
        self.assertEqual(self.attestor(), {"namespace": self.namespace, "namespaceUID": self.ns_uid,
            "podUID": self.uid, "container": "broker"})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(set(self.reads), set(self.files))
    def test_ordinary_file_cannot_claim_another_pod_identity(self):
        self.files[identity.MOUNTINFO] = self.files[identity.MOUNTINFO].replace(self.uid.encode(), b"44444444-4444-4444-4444-444444444444")
        with self.assertRaisesRegex(ValueError, "KERNEL_POD_BINDING_MISMATCH"): self.attestor()
        self.assertEqual(self.calls, [])
    def test_writable_and_duplicate_mounts_refused(self):
        original = self.files[identity.MOUNTINFO]
        self.files[identity.MOUNTINFO] = original.replace(b"ro,relatime", b"rw,relatime")
        with self.assertRaisesRegex(ValueError, "NOT_READONLY"): self.attestor()
        self.files[identity.MOUNTINFO] = original + self.lines[0].encode() + b"\n"
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS"): self.attestor()
    def test_the_old_candidate_layouts_are_no_longer_accepted(self):
        direct = [f"{i+10} 1 8:1 /var/lib/kubelet/pods/{self.uid}/volumes/kubernetes.io~downward-api/{identity.VOLUME}/..fixture/{f} {identity.ROOT / f} ro,relatime - ext4 /dev/synthetic rw"
                  for i, f in enumerate(identity.FIELDS)]
        subpath = [f"{i+10} 1 8:1 /var/lib/kubelet/pods/{self.uid}/volume-subpaths/{identity.VOLUME}/broker/{i} {identity.ROOT / f} ro - ext4 /dev/synthetic rw"
                   for i, f in enumerate(identity.FIELDS)]
        for layout in (direct, subpath):
            self.files[identity.MOUNTINFO] = ("\n".join(layout + self.k1) + "\n").encode()
            with self.assertRaisesRegex(ValueError, "KERNEL_VOLUME_LAYOUT_MISMATCH"): self.attestor()
        self.assertEqual(self.calls, [])

    def test_tmpfs_layout_must_be_one_instance_one_generation_and_the_exact_field(self):
        original = self.files[identity.MOUNTINFO]
        for old, new in ((b"0:2391 /..2026_11_10_14_37_31.3061124380/pod-name", b"0:2392 /..2026_11_10_14_37_31.3061124380/pod-name"),      # another tmpfs instance
                         (b"/..2026_11_10_14_37_31.3061124380/namespace", b"/..2026_11_10_14_37_32.3061124380/namespace"),                     # another generation
                         (b"/..2026_11_10_14_37_31.3061124380/pod-uid", b"/..2026_11_10_14_37_31.3061124380/pod-name"),                       # wrong leaf for the field
                         (b"/..2026_11_10_14_37_31.3061124380/pod-uid", b"/pod-uid"),                                                          # not inside an AtomicWriter directory
                         (b"/..2026_11_10_14_37_31.3061124380/pod-uid", b"/..data/pod-uid"),                                                   # the symlink name, not a generation
                         (b" - tmpfs tmpfs rw,seclabel", b" - ext4 /dev/synthetic rw,seclabel")):                                              # not a tmpfs
            self.files[identity.MOUNTINFO] = original.replace(old, new, 1)
            with self.assertRaisesRegex(ValueError, "KERNEL_VOLUME_LAYOUT_MISMATCH|AMBIGUOUS"): self.attestor()
        self.assertEqual(self.calls, [])

    def test_pod_and_container_are_bound_by_the_kubelet_owned_mounts(self):
        original = self.files[identity.MOUNTINFO]
        other = b"44444444-4444-4444-4444-444444444444"
        for old, new in ((f"pods/{self.uid}/etc-hosts".encode(), b"pods/" + other + b"/etc-hosts"),
                         (f"pods/{self.uid}/containers/broker/".encode(), b"pods/" + other + b"/containers/broker/"),
                         (b"containers/broker/", b"containers/worker/"),
                         (b"containers/broker/a1b2c3d4", b"containers/broker/xyz"),
                         (b"/var/lib/kubelet/pods/", b"/unsupported/")):
            self.files[identity.MOUNTINFO] = original.replace(old, new, 1)
            with self.assertRaisesRegex(ValueError, "POD_BINDING_MISMATCH"): self.attestor()
        for point in (b"/etc/hosts", b"/dev/termination-log"):   # a missing or doubled kubelet mount is not a binding
            mine = [line for line in original.split(b"\n") if line and line.split(b" ")[4] == point]
            others = [line for line in original.split(b"\n") if line and line.split(b" ")[4] != point]
            self.files[identity.MOUNTINFO] = b"\n".join(others) + b"\n"
            with self.assertRaisesRegex(ValueError, "MISSING_OR_AMBIGUOUS"): self.attestor()
            self.files[identity.MOUNTINFO] = original + mine[0] + b"\n"
            with self.assertRaisesRegex(ValueError, "MISSING_OR_AMBIGUOUS"): self.attestor()
        self.assertEqual(self.calls, [])

    def test_a_perfect_tmpfs_layout_alone_cannot_pass_without_the_pod_binding(self):
        self.files[identity.MOUNTINFO] = ("\n".join(self.lines) + "\n").encode()
        with self.assertRaisesRegex(ValueError, "MISSING_OR_AMBIGUOUS"): self.attestor()

    def test_the_observed_probe_lines_verbatim_are_accepted_with_a_matching_pod_binding(self):
        probe = ("27420 27406 0:2391 /..2026_11_10_14_37_31.3061124380/pod-uid /run/dsh-executing-identity/pod-uid ro,relatime - tmpfs tmpfs rw,seclabel,size=131072k,inode64\n"
                 "27421 27406 0:2391 /..2026_11_10_14_37_31.3061124380/pod-name /run/dsh-executing-identity/pod-name ro,relatime - tmpfs tmpfs rw,seclabel,size=131072k,inode64\n"
                 "27422 27406 0:2391 /..2026_11_10_14_37_31.3061124380/namespace /run/dsh-executing-identity/namespace ro,relatime - tmpfs tmpfs rw,seclabel,size=131072k,inode64\n")
        self.files[identity.MOUNTINFO] = (probe + "\n".join(self.k1) + "\n").encode()
        self.assertEqual(self.attestor()["podUID"], self.uid)

    def test_host_namespace_or_privileged_mount_capability_refused(self):
        self.pod["spec"]["hostPID"] = True
        with self.assertRaisesRegex(ValueError, "HOST_NAMESPACE"): self.attestor()
        self.pod["spec"].pop("hostPID")
        self.pod["spec"]["containers"][0]["securityContext"]["capabilities"]["add"] = ["SYS_ADMIN"]
        with self.assertRaisesRegex(ValueError, "MOUNT_TAMPER"): self.attestor()
    def test_wrong_field_projection_or_secret_volume_refused(self):
        volume = self.pod["spec"]["volumes"][0]
        volume["downwardAPI"]["items"][0]["fieldRef"]["fieldPath"] = "metadata.name"
        with self.assertRaisesRegex(ValueError, "FIELD_BINDING"): self.attestor()
        volume.pop("downwardAPI"); volume["secret"] = {"secretName": "unread-fixture"}
        with self.assertRaisesRegex(ValueError, "VOLUME_REQUIRED"): self.attestor()
    def test_api_replacement_and_downward_value_mismatch_refused(self):
        self.pod["metadata"]["uid"] = "44444444-4444-4444-4444-444444444444"
        with self.assertRaisesRegex(ValueError, "API_IDENTITY"): self.attestor()
        self.files[identity.ROOT / "pod-uid"] = b"44444444-4444-4444-4444-444444444444"
        with self.assertRaisesRegex(ValueError, "DOWNWARD_IDENTITY_MISMATCH"): self.attestor()
    def test_kernel_mount_mutation_refused(self):
        original = self.attestor.reader; mount_reads = []
        def changed(path, limit):
            raw = original(path, limit)
            if path == identity.MOUNTINFO:
                mount_reads.append(path)
                if len(mount_reads) > 1: return raw + b"\n"
            return raw
        self.attestor.reader = changed
        with self.assertRaisesRegex(ValueError, "MOUNTS_CHANGED"): self.attestor()
    def test_non_linux_refuses_before_file_or_api_access(self):
        with patch.object(identity.sys, "platform", "win32"):
            with self.assertRaisesRegex(ValueError, "REQUIRES_LINUX"): self.attestor()
        self.assertEqual(self.calls, []); self.assertEqual(self.reads, [])
    def test_unsupported_root_layout_is_not_attestation(self):
        self.files[identity.MOUNTINFO] = self.files[identity.MOUNTINFO].replace(b"/var/lib/kubelet/pods/", b"/unsupported/")
        with self.assertRaisesRegex(ValueError, "KERNEL_POD_BINDING"): self.attestor()
    def test_ephemeral_or_init_container_invalidates_profile(self):
        self.pod["spec"]["ephemeralContainers"] = [{"name": "debug"}]
        with self.assertRaisesRegex(ValueError, "NOT_UNIQUE"): self.attestor()
        self.pod["spec"].pop("ephemeralContainers")
        self.pod["spec"]["initContainers"] = [{"name": "init"}]
        with self.assertRaisesRegex(ValueError, "NOT_UNIQUE"): self.attestor()
    def test_composed_observer_uses_kernel_identity_not_only_test_api_labels(self):
        from scripts.official_sdk_deployment_observer import OfficialSDKDeploymentObserver, ENVIRONMENT, ROLE
        digest = "sha256:" + "a" * 64; job_uid = "33333333-3333-3333-3333-333333333333"
        labels = {ENVIRONMENT: "test", ROLE: "qualification"}
        self.ns["metadata"].update(resourceVersion="1", labels=labels)
        self.pod["metadata"].update(resourceVersion="2", labels=labels, ownerReferences=[{
            "controller": True, "apiVersion": "batch/v1", "kind": "Job", "name": "test-job", "uid": job_uid}])
        self.pod["spec"]["restartPolicy"] = "Never"
        self.pod["spec"]["containers"][0]["image"] = "registry/qualified@" + digest
        self.pod["status"] = {"phase": "Running", "containerStatuses": [{"name": "broker", "ready": True,
            "state": {"running": {"startedAt": "synthetic"}}, "imageID": "containerd://" + digest}]}
        job = {"kind": "Job", "apiVersion": "batch/v1", "metadata": {"name": "test-job", "uid": job_uid,
            "namespace": self.namespace, "resourceVersion": "3", "labels": labels}, "spec": {
            "backoffLimit": 0, "parallelism": 1, "completions": 1, "activeDeadlineSeconds": 300,
            "template": {"metadata": {"labels": labels}, "spec": copy.deepcopy(self.pod["spec"])}}}
        def api(kind, version, namespace, name):
            return copy.deepcopy({"Namespace": self.ns, "Pod": self.pod, "Job": job}[kind])
        self.attestor.read = api
        observer = OfficialSDKDeploymentObserver(read_resource=api, executing_identity=self.attestor,
            namespace=self.namespace, namespace_uid=self.ns_uid, pod_name=self.pod_name,
            pod_uid=self.uid, job_name="test-job", job_uid=job_uid, container_name="broker", image_digest=digest)
        self.assertEqual(observer()["podUID"], self.uid)
        self.files[identity.MOUNTINFO] = self.files[identity.MOUNTINFO].replace(self.uid.encode(), b"44444444-4444-4444-4444-444444444444")
        with self.assertRaisesRegex(ValueError, "KERNEL_POD_BINDING_MISMATCH"): observer()


if __name__ == "__main__": unittest.main()
