"""The qualification objects must satisfy the REAL protected modules (observer + executing identity), tolerate API read-backs, and refuse every drift.

No cluster, no credential, no network: the Kubernetes API is replaced by objects derived from the generator's own output.
"""
import base64
import copy
import hashlib
import json
from pathlib import PurePosixPath
import unittest
from unittest.mock import patch

from scripts import official_sdk_deployment_observer as observer_module
from scripts import official_sdk_executing_identity as identity
from scripts import sdk_qualification_k8s as q

WHEEL = b"synthetic wheel bytes, 24 KB in real life"
UIDS = {"namespace_uid": "11111111-1111-1111-1111-111111111111", "job_uid": "33333333-3333-3333-3333-333333333333",
        "pod_uid": "22222222-2222-2222-2222-222222222222"}
DIGEST = "sha256:" + "a" * 64


def spec(**override):
    value = {"namespace": "dsh-a2a-qual", "jobName": "sdk-qualification", "containerName": "broker", "image": "registry.example/dsh-runtime@" + DIGEST,
             "command": ["python3", "-I", "/opt/dsh/container/dsh-native-qualification-broker.py"],
             "identityRoute": "secret-client-certificate", "observerSubject": "sdk-qualification-observer", "podSecurity": "baseline",
             "activeDeadlineSeconds": 300, "resources": {"cpu": 2, "memoryBytes": 4 * q.GIB, "ephemeralBytes": 2 * q.GIB},
             "wheelSha256": hashlib.sha256(WHEEL).hexdigest(), "nodeName": None, "excludedNodes": [], "workspaceBytes": 256 * 1024 ** 2, "workspaceStorageClass": "topolvm-immediate",
             "clientPodLabels": {"app": "a2a-client"}, "apiServerTargets": [{"cidr": "192.0.2.54/32", "port": 6443}, {"cidr": "192.0.2.1/32", "port": 443}], "litellmPodLabels": {"app": "litellm"}}
    value.update(override)
    return value


def package_raw(s):
    return (json.dumps({"kind": "DSH_OFFICIAL_SDK_PACKAGE_V1", "sourceCommit": "c" * 40, "sdkVersion": "0.2.2a2", "runtimeVersion": "0.2.2a2",
                        "sdkWheelSha256": s["wheelSha256"], "installedRecordSha256": "d" * 64}, sort_keys=True) + "\n").encode()


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.spec = spec()
        self.package = package_raw(self.spec)
        self.objects = q.build_objects(self.spec, wheel_raw=WHEEL, package_admission_raw=self.package)


    def test_shared_objects_are_byte_identical_across_the_three_cases_except_the_job(self):
        # V12 case C was refused at NextJob (READBACK_VALUE_MISMATCH role-observer.rules[1].resourceNames[0]): the shared Role named only its own Job.
        built = {}
        for name in ("sdk-qualification-b", "sdk-qualification-c", "sdk-qualification-d"):
            s = spec(jobName=name)
            built[name] = q.build_objects(s, wheel_raw=WHEEL, package_admission_raw=package_raw(s))
        reference = built["sdk-qualification-b"]
        for name, objects in built.items():
            for key in reference:
                if key == "job":
                    continue
                self.assertEqual(json.dumps(objects[key], sort_keys=True), json.dumps(reference[key], sort_keys=True), name + " " + key)
        role = reference["role-observer"]["rules"][1]
        self.assertEqual(role["resourceNames"], ["sdk-qualification-b", "sdk-qualification-c", "sdk-qualification-d"])   # exact names, nothing wider
        self.assertNotIn("*", json.dumps(role))
    def check(self, objects=None, s=None):
        return q.check_objects(objects or self.objects, s or self.spec, wheel_raw=WHEEL, package_admission_raw=self.package)

    def test_generated_objects_pass_the_checker_and_cover_every_kind(self):
        self.assertEqual(self.check(), ["readback-contains-the-admitted-objects", "rbac-minimal-named-and-without-secrets",
                                        "job-pod-profile-for-observer-and-executing-identity"])
        self.assertEqual(set(self.objects), {"namespace", "limitrange", "resourcequota", "serviceaccount", "networkpolicy-default-deny", "networkpolicy-broker", "networkpolicy-worker", "clusterrole-read-namespace", "clusterrolebinding-read-namespace",
                                             "role-observer", "rolebinding-observer", "role-worker-controller", "rolebinding-worker-controller",
                                             "configmap-sdk-wheel", "configmap-package-admission", "configmap-workspace-policy",
                                             "persistentvolumeclaim-workspace", "job"})

    def test_no_secret_or_credential_is_ever_generated(self):
        text = json.dumps(self.objects)
        self.assertNotIn('"kind": "Secret"', text)
        self.assertNotIn("BEGIN", text)
        # the identity Secret is only REFERENCED (created by whoever holds the credential)
        self.assertIn("sdk-qualification-identity", text)

    def test_projected_token_route_has_no_secret_volume(self):
        s = spec(identityRoute="projected-token")
        objects = q.build_objects(s, wheel_raw=WHEEL, package_admission_raw=self.package)
        volumes = objects["job"]["spec"]["template"]["spec"]["volumes"]
        self.assertEqual([v["name"] for v in volumes if "secret" in v], ["broker-token"])   # the identity route adds no Secret volume; only the broker auth token is one
        self.assertTrue(any(v["name"] == "kubernetes-token" for v in volumes))
        q.check_objects(objects, s, wheel_raw=WHEEL, package_admission_raw=self.package)

    def test_a_live_read_back_with_server_fields_and_omitted_false_defaults_is_accepted(self):
        live = copy.deepcopy(self.objects)
        pod = live["job"]["spec"]["template"]["spec"]
        for field in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace"):
            pod.pop(field)
        live["job"]["spec"].pop("suspend")
        live["job"]["metadata"].update({"uid": UIDS["job_uid"], "resourceVersion": "9", "creationTimestamp": "x", "managedFields": [1]})
        live["job"]["status"] = {"active": 1}
        live["namespace"]["metadata"]["uid"] = UIDS["namespace_uid"]
        live["namespace"]["status"] = {"phase": "Active"}
        live["serviceaccount"].pop("automountServiceAccountToken") if False else None
        self.check(live)

    def test_every_drift_is_refused(self):
        def mutate(path_fn):
            broken = copy.deepcopy(self.objects)
            path_fn(broken)
            return broken
        cases = {
            "init container": lambda o: o["job"]["spec"]["template"]["spec"].update(initContainers=[{"name": "i", "image": "x@" + DIGEST}]),
            "second container": lambda o: o["job"]["spec"]["template"]["spec"]["containers"].append({"name": "side"}),
            "image": lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0].update(image="registry.example/other@sha256:" + "b" * 64),
            "deadline": lambda o: o["job"]["spec"].update(activeDeadlineSeconds=301),
            "retries": lambda o: o["job"]["spec"].update(backoffLimit=1),
            "writable root": lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["securityContext"].update(readOnlyRootFilesystem=False),
            "capability added": lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["securityContext"]["capabilities"].update(add=["SYS_ADMIN"]),
            "host network": lambda o: o["job"]["spec"]["template"]["spec"].update(hostNetwork=True),
            "test label": lambda o: o["namespace"]["metadata"]["labels"].update({observer_module.ENVIRONMENT: "production"}),
            "pod security": lambda o: o["namespace"]["metadata"]["labels"].update({"pod-security.kubernetes.io/enforce": "privileged"}),
            "rbac wildcard": lambda o: o["role-worker-controller"]["rules"][0].update(verbs=["*"]),
            "rbac secrets": lambda o: o["role-observer"]["rules"].append({"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]}),
            "rbac list": lambda o: o["role-observer"]["rules"][0].update(verbs=["get", "list"]),
            "rbac exec": lambda o: o["role-worker-controller"]["rules"][0].update(resources=["pods", "pods/exec"]),
            "job not pinned": lambda o: o["role-observer"]["rules"][1].update(resourceNames=["another-job"]),
            "wheel bytes": lambda o: o["configmap-sdk-wheel"]["binaryData"].update({q.WHEEL_NAME: base64.b64encode(b"other").decode()}),
            "host path volume": lambda o: o["job"]["spec"]["template"]["spec"]["volumes"].append({"name": "h", "hostPath": {"path": "/"}}),
            "extra object": lambda o: o.update(extra={"kind": "Secret"}),
        }
        for label, change in cases.items():
            with self.subTest(label):
                with self.assertRaises(q.SpecError):
                    self.check(mutate(change))

    def test_the_entry_point_environment_is_exactly_the_agreed_non_secret_set(self):
        env = {e["name"]: e["value"] for e in self.objects["job"]["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env, {"DSH_NATIVE_QUALIFICATION_MODE": "1", "DSH_OFFICIAL_SDK_ADMISSION_FILE": "/etc/dsh-native-admission/official-sdk-server.json",
                               "DSH_QUALIFICATION_JOB_NAME": "sdk-qualification", "DSH_QUALIFICATION_CONTAINER_NAME": "broker",
                               "DSH_QUALIFICATION_WAIT_SECONDS": "120", "DSH_QUALIFICATION_WORKER_NAMESPACE": "dsh-a2a-qual", "DSH_TASK_STATE_ROOT": "/state/web-tasks", "DSH_TASK_TOKEN_FILE": "/runtime-tokens/token"})
        with_node = q.build_objects(spec(nodeName="worker-2"), wheel_raw=WHEEL, package_admission_raw=self.package)
        self.assertIn({"name": "DSH_QUALIFICATION_NODE_NAME", "value": "worker-2"}, with_node["job"]["spec"]["template"]["spec"]["containers"][0]["env"])
        for label, extra in (("secret name", {"name": "ANTHROPIC_API_KEY", "value": "x"}), ("valueFrom", {"name": "X", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}})):
            broken = copy.deepcopy(self.objects)
            broken["job"]["spec"]["template"]["spec"]["containers"][0]["env"].append(extra)
            with self.subTest(label), self.assertRaises(q.SpecError):
                self.check(broken)

    def test_network_policies_follow_the_agreed_traffic(self):
        broker = self.objects["networkpolicy-broker"]["spec"]
        self.assertEqual(broker["ingress"], [{"from": [{"podSelector": {"matchLabels": {"app": "a2a-client"}}}], "ports": [{"protocol": "TCP", "port": 7682}]}])
        self.assertEqual([r["to"][0].get("ipBlock", {}).get("cidr") for r in broker["egress"]], [None, "192.0.2.54/32", "192.0.2.1/32"])
        worker = self.objects["networkpolicy-worker"]["spec"]
        self.assertEqual(worker["ingress"], [])
        self.assertEqual(worker["egress"][1]["ports"], [{"protocol": "TCP", "port": 4000}])
        self.assertEqual(worker["podSelector"], {"matchLabels": {"app.kubernetes.io/part-of": "dsh-a2a-qualification"}})
        # the broker Pod carries the label its policy selects, and the worker label is NOT on the broker
        labels = self.objects["job"]["spec"]["template"]["metadata"]["labels"]
        self.assertEqual(labels["app.kubernetes.io/component"], "qualification-broker")
        self.assertNotEqual(labels.get("app.kubernetes.io/part-of"), "dsh-a2a-qualification")
        deny = self.objects["networkpolicy-default-deny"]["spec"]
        self.assertEqual((deny["podSelector"], deny["ingress"], deny["egress"]), ({}, [], []))

    def test_attach_is_granted_only_to_the_worker_identity_and_only_to_create(self):
        worker = self.objects["role-worker-controller"]["rules"]
        self.assertIn({"apiGroups": [""], "resources": ["pods/attach"], "verbs": ["create"]}, worker)
        self.check()
        for label, change in (("observer gets attach", lambda o: o["role-observer"]["rules"].append({"apiGroups": [""], "resources": ["pods/attach"], "verbs": ["create"]})),
                              ("attach with get", lambda o: o["role-worker-controller"]["rules"][1].update(verbs=["create", "get"])),
                              ("attach mixed with pods", lambda o: o["role-worker-controller"]["rules"][0].update(resources=["pods", "pods/attach"]))):
            broken = copy.deepcopy(self.objects)
            change(broken)
            with self.subTest(label), self.assertRaises(q.SpecError):
                self.check(broken)

    def test_the_job_command_is_an_isolated_python_on_a_protected_entry_file(self):
        command = self.objects["job"]["spec"]["template"]["spec"]["containers"][0]["command"]
        self.assertEqual(command[1], "-I")
        self.assertNotIn("args", self.objects["job"]["spec"]["template"]["spec"]["containers"][0])
        ok = spec(command=["python3", "-I", "/opt/dsh/container/dsh-native-qualification-broker.py"])
        q.check_objects(q.build_objects(ok, wheel_raw=WHEEL, package_admission_raw=package_raw(ok)), ok, wheel_raw=WHEEL, package_admission_raw=package_raw(ok))
        for bad in (["python3", "/opt/dsh/container/x.py", "-I"], ["python3", "-c", "print(1)"], ["python3", "-I", "-m", "http.server"],
                    ["python3", "-I", "/tmp/x.py"], ["python3", "-I", "/opt/dsh/container/../scripts/x.py"], ["/bin/sh", "-I", "/opt/dsh/container/x.py"],
                    ["python3", "-I"], ["python3", "-I", "/opt/dsh/container/x.py", "extra"]):
            with self.subTest(bad), self.assertRaises(q.SpecError):
                q.validate_spec(spec(command=bad))

    def test_interpreter_environment_is_refused_in_a_read_back(self):
        for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "LD_PRELOAD"):
            broken = copy.deepcopy(self.objects)
            broken["job"]["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": name, "value": "/x"})
            with self.subTest(name), self.assertRaises(q.SpecError):
                self.check(broken)
        broken = copy.deepcopy(self.objects)
        broken["job"]["spec"]["template"]["spec"]["containers"][0]["args"] = ["-c", "x"]
        with self.assertRaises(q.SpecError):
            self.check(broken)

    def test_one_node_cluster_no_affinity_no_pin_and_the_only_node_cannot_be_excluded(self):
        pod = self.objects["job"]["spec"]["template"]["spec"]
        self.assertNotIn("nodeName", pod)
        self.assertNotIn("affinity", pod)
        self.assertNotIn("DSH_QUALIFICATION_EXCLUDED_NODES", {e["name"] for e in pod["containers"][0]["env"]})
        broken = copy.deepcopy(self.objects)
        broken["job"]["spec"]["template"]["spec"]["affinity"] = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [
            {"matchExpressions": [{"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["dagpu-gn-p1"]}]}]}}}
        with self.assertRaises(q.SpecError):   # an unsatisfiable affinity on a one-node cluster is refused
            self.check(broken)
        for override, code in ((dict(excludedNodes=["dagpu-gn-p1"]), "THE_ONLY_NODE_CANNOT_BE_EXCLUDED"), (dict(excludedNodes="x"), "EXCLUDED_NODES_LIST_REQUIRED"),
                               (dict(excludedNodes=["a", "a"]), "EXCLUDED_NODES_LIST_REQUIRED"), (dict(nodeName="n1", excludedNodes=["n1"]), "NODE_PIN_IS_AN_EXCLUDED_NODE")):
            with self.subTest(code), self.assertRaisesRegex(q.SpecError, code):
                q.validate_spec(spec(**override))

    def test_a_second_node_can_still_be_excluded_by_affinity_and_the_entry_env(self):
        two = spec(excludedNodes=["spare-1"])
        objects = q.build_objects(two, wheel_raw=WHEEL, package_admission_raw=package_raw(two))
        q.check_objects(objects, two, wheel_raw=WHEEL, package_admission_raw=package_raw(two))
        pod = objects["job"]["spec"]["template"]["spec"]
        self.assertEqual(pod["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"],
                         [{"matchExpressions": [{"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["spare-1"]}]}])
        self.assertIn({"name": "DSH_QUALIFICATION_EXCLUDED_NODES", "value": "spare-1"}, pod["containers"][0]["env"])
        broken = copy.deepcopy(objects)
        broken["job"]["spec"]["template"]["spec"].pop("affinity")
        with self.assertRaises(q.SpecError):
            q.check_objects(broken, two, wheel_raw=WHEEL, package_admission_raw=package_raw(two))

    def test_it_shares_the_gpu_node_without_a_gpu_priority_or_unbounded_resources(self):
        pod = self.objects["job"]["spec"]["template"]["spec"]
        container = pod["containers"][0]
        self.assertEqual(container["resources"]["requests"], container["resources"]["limits"])
        self.assertFalse(any("gpu" in k or "mig" in k for k in container["resources"]["limits"]))
        self.assertNotIn("priorityClassName", pod)
        for label, change in (("gpu limit", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"].update({"nvidia.com/gpu": "1"})),
                              ("priority class", lambda o: o["job"]["spec"]["template"]["spec"].update(priorityClassName="system-node-critical")),
                              ("unequal requests", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"].update(cpu="1")),
                              ("no requests", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["resources"].pop("requests"))):
            broken = copy.deepcopy(self.objects)
            change(broken)
            with self.subTest(label), self.assertRaises(q.SpecError):
                self.check(broken)
        with self.assertRaisesRegex(q.SpecError, "RESOURCES_ABOVE_THE_LIMITRANGE_MAX"):
            q.validate_spec(spec(resources={"cpu": 5, "memoryBytes": 4 * q.GIB, "ephemeralBytes": q.GIB}))

    def test_limitrange_quota_storage_class_and_both_api_server_egress_rules(self):
        limits = self.objects["limitrange"]["spec"]["limits"][0]
        self.assertEqual(limits["max"], {"cpu": "4", "memory": str(8 * q.GIB)})
        hard = self.objects["resourcequota"]["spec"]["hard"]
        self.assertEqual((hard["requests.cpu"], hard["limits.cpu"], hard["requests.memory"], hard["limits.memory"], hard["pods"], hard["persistentvolumeclaims"], hard["requests.storage"]),
                         ("3", "5", str(6 * q.GIB), str(8 * q.GIB), "6", "1", str(q.GIB)))
        self.assertFalse(any("ephemeral" in k for k in hard))   # the hash-bound worker containers set no ephemeral-storage
        self.assertEqual((limits["default"]["ephemeral-storage"], limits["defaultRequest"]["ephemeral-storage"]), (str(256 * 1024 ** 2), str(64 * 1024 ** 2)))
        self.assertEqual(self.objects["persistentvolumeclaim-workspace"]["spec"]["storageClassName"], "topolvm-immediate")
        egress = self.objects["networkpolicy-broker"]["spec"]["egress"]
        for cidr, port in (("192.0.2.54/32", 6443), ("192.0.2.1/32", 443)):
            self.assertIn({"to": [{"ipBlock": {"cidr": cidr}}], "ports": [{"protocol": "TCP", "port": port}]}, egress)
        for label, change in (("limitrange max raised", lambda o: o["limitrange"]["spec"]["limits"][0]["max"].update(cpu="64")),
                              ("quota raised", lambda o: o["resourcequota"]["spec"]["hard"].update(pods="50")),
                              ("ephemeral in quota", lambda o: o["resourcequota"]["spec"]["hard"].update({"requests.ephemeral-storage": "1Gi"})),
                              ("no ephemeral default", lambda o: o["limitrange"]["spec"]["limits"][0]["default"].pop("ephemeral-storage")),
                              ("disk emptyDir broker", lambda o: [v.update(emptyDir={}) for v in o["job"]["spec"]["template"]["spec"]["volumes"] if v["name"] == "workspace"]),
                              ("other class", lambda o: o["persistentvolumeclaim-workspace"]["spec"].update(storageClassName="topolvm")),
                              ("bigger claim", lambda o: o["persistentvolumeclaim-workspace"]["spec"]["resources"]["requests"].update(storage=str(2 * q.GIB))),
                              ("api egress dropped", lambda o: o["networkpolicy-broker"]["spec"]["egress"].pop())):
            broken = copy.deepcopy(self.objects)
            change(broken)
            with self.subTest(label), self.assertRaises(q.SpecError):
                self.check(broken)
        for override, code in ((dict(workspaceStorageClass="topolvm"), "STORAGE_CLASS_MUST_BE_THE_IMMEDIATE_BINDING_ONE"), (dict(workspaceStorageClass=None), "STORAGE_CLASS_MUST_BE_THE_IMMEDIATE_BINDING_ONE"),
                               (dict(workspaceBytes=2 * q.GIB), "BAD_WORKSPACE")):
            with self.subTest(code), self.assertRaisesRegex(q.SpecError, code):
                q.validate_spec(spec(**override))

    def test_reference_spec_carries_the_decided_values(self):
        ref = q.reference_spec(image="registry.example/dsh-runtime@" + DIGEST, wheel_sha256=hashlib.sha256(WHEEL).hexdigest(),
                               command=["python3", "-I", "/opt/dsh/container/dsh-native-qualification-broker.py"], client_pod_labels={"app": "c"},
                               api_server_targets=[{"cidr": "192.0.2.54/32", "port": 6443}, {"cidr": "192.0.2.1/32", "port": 443}], litellm_pod_labels={"app": "litellm"})
        q.validate_spec(ref)
        self.assertEqual((ref["namespace"], ref["podSecurity"], ref["nodeName"], ref["excludedNodes"], ref["activeDeadlineSeconds"], ref["identityRoute"]),
                         ("dsh-a2a-qual", "baseline", None, [], 300, "secret-client-certificate"))
        objects = q.build_objects(ref, wheel_raw=WHEEL, package_admission_raw=package_raw(ref))
        q.check_objects(objects, ref, wheel_raw=WHEEL, package_admission_raw=package_raw(ref))
        self.assertEqual(objects["namespace"]["metadata"]["name"], "dsh-a2a-qual")

    def test_workers_get_the_claim_the_broker_keeps_an_emptydir_with_a_static_policy_and_the_credential_is_only_named(self):
        policy = json.loads(self.objects["configmap-workspace-policy"]["data"]["a2a-workspace-policy.json"])
        self.assertEqual(policy, {"policies": {".": {"claim": "dsh-a2a-qual-workspace", "subpath": "qual", "writes": False, "brokerPath": "/workspace",
                                                      "credentialSecret": "dsh-a2a-qual-task-credential"}}})
        pvc = self.objects["persistentvolumeclaim-workspace"]
        self.assertEqual(pvc["metadata"]["name"], "dsh-a2a-qual-workspace")
        self.assertEqual(pvc["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(pvc["spec"]["storageClassName"], "topolvm-immediate")   # the survey: the only Immediate-binding class
        pod = self.objects["job"]["spec"]["template"]["spec"]
        mounts = {m["mountPath"]: m for m in pod["containers"][0]["volumeMounts"]}
        self.assertNotIn("subPath", mounts["/workspace"])
        self.assertEqual([v for v in pod["volumes"] if v["name"] == "workspace"][0]["emptyDir"]["medium"], "Memory")
        self.assertFalse(any(v.get("persistentVolumeClaim") for v in pod["volumes"]))   # only the WORKER Pods mount the claim (A2A lane D12 correction)
        self.assertTrue(mounts["/etc/dsh-native-admission/a2a-workspace-policy.json"]["readOnly"])
        self.assertNotIn("dsh-a2a-qual-task-credential", json.dumps(pod))   # the broker never sees the scoped key
        self.assertNotIn("Secret", {o["kind"] for o in self.objects.values()})
        for label, change in (("broker mounts the claim", lambda o: [v.pop("emptyDir") or v.update(persistentVolumeClaim={"claimName": "dsh-a2a-qual-workspace"}) for v in o["job"]["spec"]["template"]["spec"]["volumes"] if v["name"] == "workspace"]),
                              ("broker subPath on workspace", lambda o: [m.update(subPath="qual") for m in o["job"]["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] if m["name"] == "workspace"]),
                              ("credential mounted in the broker", lambda o: o["job"]["spec"]["template"]["spec"]["volumes"].append(
                                  {"name": "c", "secret": {"secretName": "dsh-a2a-qual-task-credential"}})),
                              ("rwx claim", lambda o: o["persistentvolumeclaim-workspace"]["spec"].update(accessModes=["ReadWriteMany"]))):
            broken = copy.deepcopy(self.objects)
            change(broken)
            with self.subTest(label), self.assertRaises(q.SpecError):
                self.check(broken)

    def test_the_task_journal_root_is_an_empty_memory_emptydir_nothing_can_be_seeded(self):
        pod = self.objects["job"]["spec"]["template"]["spec"]
        self.assertEqual([v for v in pod["volumes"] if v["name"] == "task-state"], [{"name": "task-state", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}}])
        self.assertEqual([m for m in pod["containers"][0]["volumeMounts"] if m["mountPath"].startswith("/state")], [{"name": "task-state", "mountPath": "/state"}])
        self.assertIn({"name": "DSH_TASK_STATE_ROOT", "value": "/state/web-tasks"}, pod["containers"][0]["env"])
        for label, change in (("state from a ConfigMap", lambda o: [v.update(configMap={"name": "seed"}) or v.pop("emptyDir") for v in o["job"]["spec"]["template"]["spec"]["volumes"] if v["name"] == "task-state"]),
                              ("state from a claim", lambda o: [v.update(persistentVolumeClaim={"claimName": "dsh-a2a-qual-workspace"}) or v.pop("emptyDir") for v in o["job"]["spec"]["template"]["spec"]["volumes"] if v["name"] == "task-state"]),
                              ("state on disk", lambda o: [v["emptyDir"].pop("medium") for v in o["job"]["spec"]["template"]["spec"]["volumes"] if v["name"] == "task-state"]),
                              ("subPath into state", lambda o: [m.update(subPath="web-tasks") for m in o["job"]["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] if m["name"] == "task-state"]),
                              ("second mount under state", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["volumeMounts"].append({"name": "workspace", "mountPath": "/state/web-tasks"})),
                              ("env removed", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["env"].pop())):
            broken = copy.deepcopy(self.objects)
            change(broken)
            with self.subTest(label), self.assertRaises(q.SpecError):
                self.check(broken)

    def test_the_broker_token_is_a_secret_mounted_by_name_as_a_file_and_never_generated(self):
        pod = self.objects["job"]["spec"]["template"]["spec"]
        self.assertEqual([v for v in pod["volumes"] if v["name"] == "broker-token"],
                         [{"name": "broker-token", "secret": {"secretName": "dsh-a2a-test-broker-token", "defaultMode": 0o400, "items": [{"key": "token", "path": "token", "mode": 0o400}]}}])
        self.assertIn({"name": "broker-token", "mountPath": "/runtime-tokens/token", "subPath": "token", "readOnly": True}, pod["containers"][0]["volumeMounts"])
        self.assertNotIn("Secret", {o["kind"] for o in self.objects.values()})   # no Secret object is generated
        for label, change in (("other secret", lambda o: [v["secret"].update(secretName="x") for v in o["job"]["spec"]["template"]["spec"]["volumes"] if v["name"] == "broker-token"]),
                              ("mode 0644", lambda o: [v["secret"].update(defaultMode=0o644) for v in o["job"]["spec"]["template"]["spec"]["volumes"] if v["name"] == "broker-token"]),
                              ("writable mount", lambda o: [m.update(readOnly=False) for m in o["job"]["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] if m["name"] == "broker-token"]),
                              ("whole directory mount", lambda o: [m.pop("subPath") for m in o["job"]["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] if m["name"] == "broker-token"]),
                              ("env missing", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["env"].__setitem__(slice(None), [e for e in o["job"]["spec"]["template"]["spec"]["containers"][0]["env"] if e["name"] != "DSH_TASK_TOKEN_FILE"])),
                              ("token value in env", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "DSH_TASK_TOKEN", "value": "x" * 40}))):
            broken = copy.deepcopy(self.objects)
            change(broken)
            with self.subTest(label), self.assertRaises(q.SpecError):
                self.check(broken)

    def test_traffic_spec_refusals(self):
        for override, code in ((dict(apiServerTargets=[{"cidr": "0.0.0.0/0", "port": 443}]), "NARROW_IPV4"), (dict(apiServerTargets=[{"cidr": "10.0.0.0/8", "port": 443}]), "NARROW_IPV4"),
                               (dict(apiServerTargets=[{"cidr": "nope", "port": 443}]), "BAD_API_SERVER_CIDR"), (dict(apiServerTargets=[{"cidr": "192.0.2.1/32", "port": 80}]), "API_SERVER_PORT"),
                               (dict(apiServerTargets=[]), "BAD_API_SERVER_TARGETS"), (dict(apiServerTargets=[{"cidr": "192.0.2.1/32", "port": 443}] * 2), "API_SERVER_TARGETS_DISTINCT"), (dict(clientPodLabels={}), "BAD_CLIENTPODLABELS"), (dict(litellmPodLabels={"a": ""}), "BAD_LITELLMPODLABELS")):
            with self.subTest(code), self.assertRaisesRegex(q.SpecError, code):
                q.validate_spec(spec(**override))

    def test_spec_refusals(self):
        for override, code in ((dict(namespace="dsh-openshell-test-20261102"), "A2A_OWNED_TEST_NAMESPACE_REQUIRED"),
                               (dict(activeDeadlineSeconds=301), "DEADLINE_1_TO_300_REQUIRED"), (dict(activeDeadlineSeconds=0), "DEADLINE_1_TO_300_REQUIRED"),
                               (dict(image="registry.example/dsh-runtime:latest"), "IMMUTABLE_IMAGE_REQUIRED"), (dict(podSecurity="restricted"), "BASELINE_POD_SECURITY"),
                               (dict(identityRoute="kubeconfig"), "IDENTITY_ROUTE_UNKNOWN"), (dict(wheelSha256="0" * 64), "BAD_WHEEL_SHA256")):
            with self.subTest(code):
                with self.assertRaisesRegex(q.SpecError, code):
                    q.validate_spec(spec(**override))
        with self.assertRaisesRegex(q.SpecError, "WHEEL_NOT_THE_ADMITTED_ONE"):
            q.build_objects(spec(wheelSha256="1" * 64), wheel_raw=WHEEL, package_admission_raw=package_raw(spec(wheelSha256="1" * 64)))
        with self.assertRaisesRegex(q.SpecError, "PACKAGE_ADMISSION_NOT_FOR_THIS_WHEEL"):
            q.build_objects(self.spec, wheel_raw=WHEEL, package_admission_raw=package_raw(spec(wheelSha256="2" * 64)))


class ProtectedModulesAcceptTheObjectsTests(unittest.TestCase):
    """The strongest offline check: the unmodified observer and executing-identity reader run against the generated Namespace, Job and Pod."""

    def setUp(self):
        for target, value in ((identity, "ROOT"), ):
            patcher = patch.object(identity, "ROOT", PurePosixPath("/run/dsh-executing-identity")); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(identity, "MOUNTINFO", PurePosixPath("/proc/self/mountinfo")); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(identity.sys, "platform", "linux"); patcher.start(); self.addCleanup(patcher.stop)
        self.spec = spec()
        self.package = package_raw(self.spec)
        self.objects = q.build_objects(self.spec, wheel_raw=WHEEL, package_admission_raw=self.package)
        self.pod_name = "sdk-qualification-abcde"

    def stack(self, objects=None, *, subpath=True):
        view = q.live_view(objects or self.objects, self.spec, pod_name=self.pod_name, **UIDS)
        files = {identity.ROOT / "pod-uid": UIDS["pod_uid"].encode(), identity.ROOT / "pod-name": self.pod_name.encode(),
                 identity.ROOT / "namespace": self.spec["namespace"].encode()}
        lines = []
        for index, field in enumerate(identity.FIELDS):   # the layout OBSERVED on the RKE2 node (probe 10 Nov 2026) plus the two kubelet-owned Pod-binding mounts
            lines.append(f"{index + 10} 1 0:2391 /..2026_11_10_14_37_31.3061124380/{field} {identity.ROOT / field} ro,relatime - tmpfs tmpfs rw,seclabel,size=131072k,inode64")
        lines.append(f"20 1 253:1 /var/lib/kubelet/pods/{UIDS['pod_uid']}/etc-hosts /etc/hosts rw,relatime - xfs /dev/synthetic rw")
        lines.append(f"21 1 253:1 /var/lib/kubelet/pods/{UIDS['pod_uid']}/containers/{self.spec['containerName']}/a1b2c3d4 /dev/termination-log rw,relatime - xfs /dev/synthetic rw")
        files[identity.MOUNTINFO] = ("\n".join(lines) + "\n").encode()

        def reader(path, limit):
            return files[path]

        def api(kind, version, namespace, name):
            return copy.deepcopy({"Namespace": view["namespace"], "Pod": view["pod"], "Job": view["job"]}[kind])
        attestor = identity.ExecutingPodIdentity(read_resource=api, reader=reader, namespace=self.spec["namespace"], namespace_uid=UIDS["namespace_uid"],
                                                  pod_name=self.pod_name, pod_uid=UIDS["pod_uid"], container_name=self.spec["containerName"])
        watcher = observer_module.OfficialSDKDeploymentObserver(
            read_resource=api, executing_identity=attestor, namespace=self.spec["namespace"], namespace_uid=UIDS["namespace_uid"], pod_name=self.pod_name,
            pod_uid=UIDS["pod_uid"], job_name=self.spec["jobName"], job_uid=UIDS["job_uid"], container_name=self.spec["containerName"], image_digest=DIGEST)
        return attestor, watcher, view

    def test_the_real_executing_identity_and_observer_accept_the_generated_objects(self):
        attestor, watcher, _ = self.stack()
        self.assertEqual(attestor(), {"namespace": self.spec["namespace"], "namespaceUID": UIDS["namespace_uid"], "podUID": UIDS["pod_uid"], "container": "broker"})
        binding = watcher()
        self.assertEqual(binding, {"namespace": self.spec["namespace"], "namespaceUID": UIDS["namespace_uid"], "podUID": UIDS["pod_uid"],
                                   "workloadUID": UIDS["job_uid"], "environment": "test", "workloadRole": "qualification"})

    def test_the_minted_server_admission_check_uses_the_observed_binding(self):
        _, watcher, _ = self.stack()
        binding = watcher()
        good = {"kind": "DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1", "mode": "qualification", "expiresAt": 1000 + 240, "imageDigest": DIGEST, "deploymentBinding": binding}
        self.assertTrue(q.check_server_admission(json.dumps(good).encode(), self.spec, binding, now=1000))
        for label, change in (("expired window", lambda v: v.update(expiresAt=1000 + 301)), ("past", lambda v: v.update(expiresAt=999)),
                              ("other pod", lambda v: v["deploymentBinding"].update(podUID="44444444-4444-4444-4444-444444444444")),
                              ("other image", lambda v: v.update(imageDigest="sha256:" + "b" * 64)), ("mode", lambda v: v.update(mode="production"))):
            with self.subTest(label):
                broken = copy.deepcopy(good)
                change(broken)
                with self.assertRaises(q.SpecError):
                    q.check_server_admission(json.dumps(broken).encode(), self.spec, binding, now=1000)

    def test_objects_the_modules_refuse_are_also_refused_by_the_checker(self):
        for label, change, module_code in (
                ("init container", lambda o: o["job"]["spec"]["template"]["spec"].update(initContainers=[{"name": "i"}]), "NOT_UNIQUE"),
                ("deadline", lambda o: o["job"]["spec"].update(activeDeadlineSeconds=301), "BOUNDED_ZERO_RETRY"),
                ("writable root", lambda o: o["job"]["spec"]["template"]["spec"]["containers"][0]["securityContext"].update(readOnlyRootFilesystem=False), "TAMPER")):
            with self.subTest(label):
                broken = copy.deepcopy(self.objects)
                change(broken)
                attestor, watcher, _ = self.stack(broken)
                with self.assertRaisesRegex(ValueError, module_code):
                    watcher()
                with self.assertRaises(q.SpecError):
                    q.check_objects(broken, self.spec, wheel_raw=WHEEL, package_admission_raw=self.package)

    def test_a_wrong_downward_api_mount_is_refused_by_the_real_reader(self):
        broken = copy.deepcopy(self.objects)
        mounts = broken["job"]["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
        mounts[:] = [m for m in mounts if m["name"] != identity.VOLUME]
        _, watcher, _ = self.stack(broken)
        with self.assertRaisesRegex(ValueError, "MOUNT_SPEC_MISMATCH"):
            watcher()


if __name__ == "__main__":
    unittest.main()
