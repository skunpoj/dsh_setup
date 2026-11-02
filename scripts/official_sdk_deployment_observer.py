"""Read-only verifier for a disposable SDK qualification Job and its own Pod.

The protected control-plane integration injects a TLS-verified named-resource
GET and an independently attested identity of the executing broker. No default
request, kubeconfig, token discovery, environment identity or retry exists.
This verifier does not implement or attest those physical dependencies.
"""
import re

ENVIRONMENT = "dsh.example.com/runtime-environment"
ROLE = "dsh.example.com/runtime-purpose"
UID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
NAME = re.compile(r"[a-z0-9][a-z0-9.-]{0,252}")


def exact_running_digest(value):
    if not isinstance(value, str): raise ValueError("INVALID_QUALIFICATION_IMAGE_ID")
    direct = re.fullmatch(r"(?:containerd|cri-o)://(sha256:[a-f0-9]{64})", value)
    pulled = re.fullmatch(r"docker-pullable://[A-Za-z0-9][A-Za-z0-9._:/-]*@(sha256:[a-f0-9]{64})", value)
    match = direct or pulled
    if match is None: raise ValueError("INVALID_QUALIFICATION_IMAGE_ID")
    return match.group(1)


class OfficialSDKDeploymentObserver:
    def __init__(self, *, read_resource, executing_identity, namespace, namespace_uid,
                 pod_name, pod_uid, job_name, job_uid, container_name, image_digest):
        if not callable(read_resource) or not callable(executing_identity):
            raise ValueError("PROTECTED_DEPLOYMENT_OBSERVER_DEPENDENCIES_REQUIRED")
        for value in (namespace, pod_name, job_name, container_name):
            if not isinstance(value, str) or not NAME.fullmatch(value):
                raise ValueError("INVALID_SDK_QUALIFICATION_RESOURCE_NAME")
        for value in (namespace_uid, pod_uid, job_uid):
            if not isinstance(value, str) or not UID.fullmatch(value):
                raise ValueError("EXACT_SDK_QUALIFICATION_UID_REQUIRED")
        if not isinstance(image_digest, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest):
            raise ValueError("IMMUTABLE_SDK_QUALIFICATION_IMAGE_REQUIRED")
        self.read, self.self_identity = read_resource, executing_identity
        self.namespace, self.namespace_uid = namespace, namespace_uid
        self.pod_name, self.pod_uid = pod_name, pod_uid
        self.job_name, self.job_uid = job_name, job_uid
        self.container_name, self.image_digest = container_name, image_digest

    def metadata(self, value, kind, version, name, uid, *, namespaced=True):
        if not isinstance(value, dict) or value.get("kind") != kind or value.get("apiVersion") != version:
            raise ValueError("SDK_QUALIFICATION_RESOURCE_TYPE_MISMATCH")
        meta = value.get("metadata", {})
        if (meta.get("name") != name or meta.get("uid") != uid or meta.get("deletionTimestamp")
                or not isinstance(meta.get("resourceVersion"), str) or not meta["resourceVersion"]
                or (namespaced and meta.get("namespace") != self.namespace)):
            raise ValueError("SDK_QUALIFICATION_RESOURCE_IDENTITY_MISMATCH")
        return meta

    def own_identity(self):
        identity = self.self_identity()
        expected = {"namespace": self.namespace, "namespaceUID": self.namespace_uid,
                    "podUID": self.pod_uid, "container": self.container_name}
        if not isinstance(identity, dict) or identity != expected:
            raise ValueError("FOREIGN_EXECUTING_BROKER_IDENTITY")
        return identity

    @staticmethod
    def test_labels(meta):
        labels = meta.get("labels", {})
        if labels.get(ENVIRONMENT) != "test" or labels.get(ROLE) != "qualification":
            raise ValueError("NON_TEST_QUALIFICATION_WORKLOAD")

    def image(self, spec):
        containers = spec.get("containers", [])
        # One-container Test profile only. Credential-mount and OS isolation
        # still require the separately qualified physical supervisor.
        if len(containers) != 1 or containers[0].get("name") != self.container_name:
            raise ValueError("UNADMITTED_QUALIFICATION_CONTAINER_SET")
        image = containers[0].get("image", "")
        if (not isinstance(image, str) or not re.fullmatch(r"[^\s@]+@sha256:[a-f0-9]{64}", image)
                or not image.endswith("@" + self.image_digest)):
            raise ValueError("SDK_QUALIFICATION_IMAGE_SPEC_MISMATCH")

    def __call__(self):
        before = self.own_identity()
        # Fixed named GETs only; no list/watch/Secrets/exec/delete/API discovery.
        ns = self.read("Namespace", "v1", None, self.namespace)
        namespace_meta = self.metadata(ns, "Namespace", "v1", self.namespace, self.namespace_uid, namespaced=False)
        # Job/Pod labels cannot classify a shared or Production namespace as
        # Test. Namespace classification is independently owned by the platform.
        self.test_labels(namespace_meta)
        job = self.read("Job", "batch/v1", self.namespace, self.job_name)
        job_meta = self.metadata(job, "Job", "batch/v1", self.job_name, self.job_uid)
        self.test_labels(job_meta)
        template = job.get("spec", {}).get("template", {})
        self.test_labels(template.get("metadata", {}))
        self.image(template.get("spec", {}))
        job_spec = job.get("spec", {})
        if (job_spec.get("suspend") is True or type(job_spec.get("backoffLimit")) is not int
                or job_spec["backoffLimit"] != 0 or type(job_spec.get("parallelism")) is not int
                or job_spec["parallelism"] != 1 or type(job_spec.get("completions")) is not int
                or job_spec["completions"] != 1
                or type(job_spec.get("activeDeadlineSeconds")) is not int
                or not 0 < job_spec["activeDeadlineSeconds"] <= 300
                or template.get("spec", {}).get("restartPolicy") != "Never"):
            raise ValueError("BOUNDED_ZERO_RETRY_QUALIFICATION_JOB_REQUIRED")
        pod = self.read("Pod", "v1", self.namespace, self.pod_name)
        meta = self.metadata(pod, "Pod", "v1", self.pod_name, self.pod_uid)
        self.test_labels(meta)
        owners = [x for x in meta.get("ownerReferences", []) if x.get("controller") is True]
        if len(owners) != 1 or any(owners[0].get(k) != v for k, v in {
                "kind": "Job", "apiVersion": "batch/v1", "name": self.job_name, "uid": self.job_uid}.items()):
            raise ValueError("SDK_QUALIFICATION_OWNER_UID_MISMATCH")
        self.image(pod.get("spec", {}))
        if pod.get("spec", {}).get("restartPolicy") != "Never":
            raise ValueError("BOUNDED_ZERO_RETRY_QUALIFICATION_POD_REQUIRED")
        status = pod.get("status", {}); statuses = status.get("containerStatuses", [])
        if (status.get("phase") != "Running" or len(statuses) != 1
                or statuses[0].get("name") != self.container_name or statuses[0].get("ready") is not True
                or not statuses[0].get("state", {}).get("running")
                or exact_running_digest(statuses[0].get("imageID")) != self.image_digest):
            raise ValueError("SDK_QUALIFICATION_RUNNING_IMAGE_UNVERIFIED")
        # Replacement/mutation during observation is refused, never retried.
        again = self.read("Pod", "v1", self.namespace, self.pod_name)
        again_meta = self.metadata(again, "Pod", "v1", self.pod_name, self.pod_uid)
        again_job = self.read("Job", "batch/v1", self.namespace, self.job_name)
        again_job_meta = self.metadata(again_job, "Job", "batch/v1", self.job_name, self.job_uid)
        again_ns = self.read("Namespace", "v1", None, self.namespace)
        again_ns_meta = self.metadata(again_ns, "Namespace", "v1", self.namespace, self.namespace_uid, namespaced=False)
        if (again_meta["resourceVersion"] != meta["resourceVersion"]
                or again_job_meta["resourceVersion"] != job_meta["resourceVersion"]
                or again_ns_meta["resourceVersion"] != ns["metadata"]["resourceVersion"]
                or self.own_identity() != before):
            raise ValueError("SDK_QUALIFICATION_OBSERVATION_CHANGED")
        return {"namespace": self.namespace, "namespaceUID": self.namespace_uid,
            "podUID": self.pod_uid, "workloadUID": self.job_uid,
            "environment": "test", "workloadRole": "qualification"}
