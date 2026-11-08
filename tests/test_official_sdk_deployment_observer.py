"""Synthetic authoritative-object fixtures, never live API/credential access."""
import copy
import unittest
from scripts.official_sdk_deployment_observer import OfficialSDKDeploymentObserver, ENVIRONMENT, ROLE


class DeploymentObserverTests(unittest.TestCase):
    def setUp(self):
        self.ns_uid = "11111111-1111-1111-1111-111111111111"
        self.pod_uid = "22222222-2222-2222-2222-222222222222"
        self.job_uid = "33333333-3333-3333-3333-333333333333"
        self.digest = "sha256:" + "a" * 64
        labels = {ENVIRONMENT: "test", ROLE: "qualification"}
        spec = {"restartPolicy": "Never", "containers": [{"name": "broker", "image": "registry/qualified@" + self.digest}]}
        self.ns = {"kind": "Namespace", "apiVersion": "v1", "metadata": {
            "name": "dsh-sdk-qualification-test", "uid": self.ns_uid, "resourceVersion": "1", "labels": dict(labels)}}
        self.job = {"kind": "Job", "apiVersion": "batch/v1", "metadata": {
            "namespace": "dsh-sdk-qualification-test", "name": "sdk-test", "uid": self.job_uid, "resourceVersion": "2",
            "labels": dict(labels)}, "spec": {"backoffLimit": 0, "parallelism": 1, "completions": 1,
                "activeDeadlineSeconds": 300, "template": {"metadata": {"labels": dict(labels)}, "spec": copy.deepcopy(spec)}}}
        self.pod = {"kind": "Pod", "apiVersion": "v1", "metadata": {
            "namespace": "dsh-sdk-qualification-test", "name": "sdk-test-pod", "uid": self.pod_uid, "resourceVersion": "3",
            "labels": dict(labels), "ownerReferences": [{"apiVersion": "batch/v1", "kind": "Job", "name": "sdk-test",
                "uid": self.job_uid, "controller": True}]}, "spec": copy.deepcopy(spec),
            "status": {"phase": "Running", "containerStatuses": [{"name": "broker", "ready": True,
                "state": {"running": {"startedAt": "synthetic"}}, "imageID": "containerd://" + self.digest}]}}
        self.identity = {"namespace": "dsh-sdk-qualification-test", "namespaceUID": self.ns_uid, "podUID": self.pod_uid, "container": "broker"}
        self.calls = []
        def read(kind, version, namespace, name):
            self.calls.append((kind, version, namespace, name))
            return copy.deepcopy({"Namespace": self.ns, "Job": self.job, "Pod": self.pod}[kind])
        self.observer = OfficialSDKDeploymentObserver(read_resource=read,
            executing_identity=lambda: dict(self.identity), namespace="dsh-sdk-qualification-test", namespace_uid=self.ns_uid,
            pod_name="sdk-test-pod", pod_uid=self.pod_uid, job_name="sdk-test", job_uid=self.job_uid,
            container_name="broker", image_digest=self.digest)
    def test_matches_actual_bound_objects_and_running_image(self):
        value = self.observer()
        self.assertEqual(value["workloadUID"], self.job_uid)
        self.assertEqual(value["environment"], "test")
        self.assertEqual([x[0] for x in self.calls], ["Namespace", "Job", "Pod", "Pod", "Job", "Namespace"])
    def test_production_job_or_pod_cannot_masquerade_as_test(self):
        for resource in (self.ns, self.job, self.pod):
            with self.subTest(kind=resource["kind"]):
                resource["metadata"]["labels"][ENVIRONMENT] = "production"
                with self.assertRaisesRegex(ValueError, "NON_TEST"): self.observer()
                resource["metadata"]["labels"][ENVIRONMENT] = "test"
    def test_observing_another_test_pod_is_not_executing_identity(self):
        self.identity["podUID"] = "44444444-4444-4444-4444-444444444444"
        with self.assertRaisesRegex(ValueError, "EXECUTING_BROKER"): self.observer()
        self.assertEqual(self.calls, [])
    def test_owner_name_alone_does_not_prove_job_uid(self):
        self.pod["metadata"]["ownerReferences"][0]["uid"] = "44444444-4444-4444-4444-444444444444"
        with self.assertRaisesRegex(ValueError, "OWNER_UID"): self.observer()
    def test_ready_with_wrong_running_image_refused(self):
        self.pod["status"]["containerStatuses"][0]["imageID"] = "containerd://sha256:" + "b" * 64
        with self.assertRaisesRegex(ValueError, "RUNNING_IMAGE"): self.observer()
    def test_spec_tag_and_extra_container_refused(self):
        self.pod["spec"]["containers"][0]["image"] = "registry/qualified:latest"
        with self.assertRaisesRegex(ValueError, "IMAGE_SPEC"): self.observer()
        self.pod["spec"]["containers"][0]["image"] = "registry/qualified@" + self.digest
        self.pod["spec"]["containers"].append({"name": "sidecar", "image": "anything"})
        with self.assertRaisesRegex(ValueError, "CONTAINER_SET"): self.observer()
    def test_changed_resource_version_refused_without_retry(self):
        original = self.observer.read
        def read(*args):
            value = original(*args)
            if len(self.calls) == 4: value["metadata"]["resourceVersion"] = "4"
            return value
        self.observer.read = read
        with self.assertRaisesRegex(ValueError, "OBSERVATION_CHANGED"): self.observer()
        self.assertEqual(len(self.calls), 6)
    def test_job_retries_or_pod_restart_refused(self):
        self.job["spec"]["backoffLimit"] = 1
        with self.assertRaisesRegex(ValueError, "ZERO_RETRY_QUALIFICATION_JOB"): self.observer()
        self.job["spec"]["backoffLimit"] = 0
        self.pod["spec"]["restartPolicy"] = "OnFailure"
        with self.assertRaisesRegex(ValueError, "ZERO_RETRY_QUALIFICATION_POD"): self.observer()
    def test_job_mutation_during_observation_refused(self):
        original = self.observer.read
        def read(*args):
            value = original(*args)
            if len(self.calls) == 5: value["metadata"]["resourceVersion"] = "changed"
            return value
        self.observer.read = read
        with self.assertRaisesRegex(ValueError, "OBSERVATION_CHANGED"): self.observer()
    def test_terminating_namespace_refused(self):
        self.ns["metadata"]["deletionTimestamp"] = "synthetic"
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"): self.observer()
    def test_api_failure_is_not_absence_or_permission(self):
        def fail(*args): raise TimeoutError("synthetic")
        self.observer.read = fail
        with self.assertRaises(TimeoutError): self.observer()
    def test_unclassified_namespace_refused(self):
        self.ns["metadata"].pop("labels")
        with self.assertRaisesRegex(ValueError, "NON_TEST"): self.observer()
    def test_malformed_image_id_prefix_cannot_pass_by_suffix(self):
        for prefix in ("unexpected:", "garbage", "containerd://wrong/", "docker-pullable://@", ""):
            with self.subTest(prefix=prefix):
                self.pod["status"]["containerStatuses"][0]["imageID"] = prefix + self.digest
                with self.assertRaisesRegex(ValueError, "IMAGE_ID"): self.observer()
    def test_only_admitted_exact_image_id_forms_pass(self):
        for value in ("containerd://" + self.digest, "cri-o://" + self.digest,
                "docker-pullable://registry.example:443/qualified@" + self.digest,
                "registry.example.internal/dsh-runtime@" + self.digest):
            with self.subTest(value=value):
                self.pod["status"]["containerStatuses"][0]["imageID"] = value
                self.assertEqual(self.observer()["podUID"], self.pod_uid)


if __name__ == "__main__": unittest.main()
