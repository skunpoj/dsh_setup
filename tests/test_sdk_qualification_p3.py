"""The P3 helper: prepare writes the reviewed objects, the live checks accept API-like read-backs and refuse drift, and the delivery mints the two late-bound
files from those read-backs and installs them in the right order inside the window. No cluster, no credential: the exec is a recording fake."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import official_sdk_bootstrap as bootstrap
from scripts import make_official_sdk_server_admission as server_minter
from scripts import sdk_qualification_delivery as delivery
from scripts import sdk_qualification_k8s as q
from scripts import sdk_qualification_p3 as p3

WHEEL = b"synthetic wheel bytes for the p3 helper"
DIGEST = "sha256:" + "a" * 64
COMMIT = "c" * 40
NOW = 1_800_000_000
UIDS = {"namespace": "11111111-1111-1111-1111-111111111111", "job": "33333333-3333-3333-3333-333333333333", "pod": "22222222-2222-2222-2222-222222222222"}


def spec(**override):
    value = q.reference_spec(image="registry.example/dsh-runtime@" + DIGEST, wheel_sha256=hashlib.sha256(WHEEL).hexdigest(),
                             command=["python3", "-I", "/opt/dsh/container/dsh-native-qualification-broker.py"], client_pod_labels={"app": "a2a-client"},
                             api_server_targets=[{"cidr": "192.0.2.54/32", "port": 6443}, {"cidr": "192.0.2.1/32", "port": 443}], litellm_pod_labels={"app": "litellm"})
    value.update(override)
    return value


def package_raw(s):
    return (json.dumps({"kind": "DSH_OFFICIAL_SDK_PACKAGE_V1", "sourceCommit": COMMIT, "sdkVersion": "0.2.2a2", "runtimeVersion": "0.2.2a2",
                        "sdkWheelSha256": s["wheelSha256"], "installedRecordSha256": "d" * 64}, sort_keys=True) + "\n").encode()


def fake_reader():
    files = {path: ("source of " + path).encode() for path in bootstrap.SOURCES.values()}
    files[server_minter.SCOPE_MODULE] = files.get(server_minter.SCOPE_MODULE, b"scope")

    def read(path, limit=1024 * 1024):
        if path not in files:
            raise server_minter.MintRefused("SOURCE_MISSING:" + path)
        return files[path]
    return read


def save(path, value):
    Path(path).write_bytes((json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


class P3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = spec()
        self.package = package_raw(self.spec)
        self.run_dir = self.root / "run"
        self.hashes = p3.prepare(self.run_dir, self.spec, WHEEL, self.package)
        self.read = self.root / "readback"
        self.read.mkdir()
        objects = q.build_objects(self.spec, wheel_raw=WHEEL, package_admission_raw=self.package)
        live = q.live_view(objects, self.spec, namespace_uid=UIDS["namespace"], job_uid=UIDS["job"], pod_uid=UIDS["pod"], pod_name="sdk-qualification-abcde")
        for key, value in objects.items():
            save(self.read / (key + ".json"), live.get(key, value))
        pod = live["pod"]
        pod["spec"]["nodeName"] = "dagpu-gn-p1"
        pod["status"]["containerStatuses"][0]["imageID"] = "docker-pullable://registry.example/dsh-runtime@" + DIGEST
        save(self.read / "pod.json", pod)
        self.executed = []

    def deliver(self, now_values=None, fail_on=None, **override):
        clock = iter(now_values or [NOW] * 20)
        last = [NOW]

        def now_fn():
            try:
                last[0] = next(clock)
            except StopIteration:
                pass
            return last[0]

        def run(argv, stdin):
            self.executed.append((argv, stdin))
            return (1 if fail_on == len(self.executed) else 0), b"", b""
        values = dict(kubectl="kubectl", read_source=fake_reader(), source_commit=COMMIT, subject="qualification-broker", generation="gen-1", now_fn=now_fn, run=run)
        values.update(override)
        return p3.deliver(self.run_dir, self.read, **values)

    def test_prepare_writes_every_object_once_in_stage_order_and_refuses_reuse(self):
        order = json.loads((self.run_dir / "ORDER.json").read_text())
        self.assertEqual([e["stage"] for e in order], ["namespace"] * 3 + ["objects"] * 14 + ["job"])
        self.assertEqual({e["key"] for e in order}, set(q.build_objects(self.spec, wheel_raw=WHEEL, package_admission_raw=self.package)))
        for entry in order:
            self.assertEqual(hashlib.sha256((self.run_dir / "objects" / entry["file"]).read_bytes()).hexdigest(), self.hashes["objects/" + entry["file"]])
        self.assertTrue(self.hashes["inputs/spec.json"])
        with self.assertRaises(FileExistsError):
            p3.prepare(self.run_dir, self.spec, WHEEL, self.package)

    def test_cluster_scoped_objects_come_after_the_namespace_and_roles_before_bindings(self):
        keys = [e["key"] for e in json.loads((self.run_dir / "ORDER.json").read_text())]
        self.assertEqual(keys[0], "namespace")
        self.assertLess(keys.index("role-observer"), keys.index("rolebinding-observer"))
        self.assertLess(keys.index("clusterrole-read-namespace"), keys.index("clusterrolebinding-read-namespace"))
        self.assertLess(keys.index("persistentvolumeclaim-workspace"), keys.index("job"))

    def test_live_checks_accept_api_like_readbacks_and_refuse_drift(self):
        self.assertTrue(p3.check_live(self.run_dir, self.read))
        for key, change in (("resourcequota", lambda v: v["spec"]["hard"].update(pods="500")), ("persistentvolumeclaim-workspace", lambda v: v["spec"].update(storageClassName="topolvm")),
                            ("networkpolicy-broker", lambda v: v["spec"]["egress"].pop()), ("namespace", lambda v: v["metadata"]["labels"].update({"pod-security.kubernetes.io/enforce": "privileged"}))):
            value = json.loads((self.read / (key + ".json")).read_text())
            change(value)
            changed = self.root / "readback-drift"
            changed.mkdir(exist_ok=True)
            for item in self.read.glob("*.json"):
                (changed / item.name).write_bytes(item.read_bytes())
            save(changed / (key + ".json"), value)
            with self.subTest(key), self.assertRaises(ValueError):
                p3.check_live(self.run_dir, changed)
        (self.read / "limitrange.json").unlink()
        with self.assertRaisesRegex(p3.P3Refused, "READBACK_MISSING"):
            p3.check_live(self.run_dir, self.read)

    def test_stage_limited_live_check_only_judges_what_exists_so_far(self):
        for key in ("job", "pod"):
            (self.read / (key + ".json")).unlink()
        (self.read / "rolebinding-observer.json").unlink()
        self.assertTrue(p3.check_live(self.run_dir, self.read, ["namespace"]))
        with self.assertRaisesRegex(p3.P3Refused, "READBACK_MISSING:rolebinding-observer"):
            p3.check_live(self.run_dir, self.read, ["namespace", "objects"])
        bad = json.loads((self.read / "resourcequota.json").read_text())
        bad["spec"]["hard"]["pods"] = "99"
        save(self.read / "resourcequota.json", bad)
        with self.assertRaises(ValueError):
            p3.check_live(self.run_dir, self.read, ["namespace"])
        with self.assertRaisesRegex(p3.P3Refused, "UNKNOWN_STAGE"):
            p3.check_live(self.run_dir, self.read, ["everything"])

    def test_the_pod_check_binds_job_node_image_and_state(self):
        info = p3.check_pod(self.run_dir, self.read)
        self.assertEqual((info["podName"], info["nodeName"]), ("sdk-qualification-abcde", "dagpu-gn-p1"))
        self.assertEqual(info["binding"], {"namespace": "dsh-a2a-qual", "namespaceUID": UIDS["namespace"], "workloadUID": UIDS["job"], "podUID": UIDS["pod"]})
        pod = json.loads((self.read / "pod.json").read_text())
        for label, change in (("other owner uid", lambda p: p["metadata"]["ownerReferences"][0].update(uid="44444444-4444-4444-4444-444444444444")),
                              ("pending", lambda p: p["status"].update(phase="Pending")),
                              ("other image", lambda p: p["status"]["containerStatuses"][0].update(imageID="docker-pullable://registry.example/x@sha256:" + "b" * 64)),
                              ("spec drift", lambda p: p["spec"]["containers"][0]["securityContext"].update(privileged=True)),
                              ("unscheduled", lambda p: p["spec"].pop("nodeName")),
                              ("second container", lambda p: p["status"]["containerStatuses"].append({"name": "x", "state": {"running": {}}}))):
            broken = copy.deepcopy(pod)
            change(broken)
            save(self.read / "pod.json", broken)
            with self.subTest(label), self.assertRaises(ValueError):
                p3.check_pod(self.run_dir, self.read)

    def test_delivery_installs_the_lease_first_and_the_server_admission_last_inside_the_window(self):
        result = self.deliver()
        self.assertEqual([item["file"] for item in result["delivered"]], ["a2a-factory-lease.json", "official-sdk-server.json"])
        self.assertEqual(result["expiresAt"], NOW + 270)
        self.assertEqual(len(self.executed), 2)
        lease, admission = json.loads(self.executed[0][1]), json.loads(self.executed[1][1])
        self.assertEqual((lease["expiresAt"], lease["modelStartsAllowed"], lease["rollbackOwner"], lease["nodeName"]), (NOW + 270, 1, "operator-session", "dagpu-gn-p1"))
        self.assertEqual(admission["expiresAt"], NOW + 270)
        self.assertEqual(admission["deploymentBinding"]["podUID"], UIDS["pod"])
        for (argv, stdin), item in zip(self.executed, result["delivered"]):
            self.assertEqual(hashlib.sha256(stdin).hexdigest(), item["sha256"])
            self.assertEqual(argv[:6], ["kubectl", "-n", "dsh-a2a-qual", "exec", "-i", "sdk-qualification-abcde"])
            self.assertIn(item["sha256"], argv[-1])   # the in-Pod script refuses unless its hash matches
        self.assertIn("/a2a-factory-lease.json", self.executed[0][0][-1])
        self.assertIn("/official-sdk-server.json", self.executed[1][0][-1])
        for name in ("a2a-factory-lease.json", "official-sdk-server.json"):   # the exact delivered bytes are kept as evidence
            self.assertTrue((self.run_dir / "delivery" / name).is_file())

    def test_the_lease_carries_the_per_job_model_start_allowance(self):
        for starts in (0, 1, 2):
            self.executed.clear()
            shutil_dir = self.run_dir / "delivery"
            if shutil_dir.exists():
                for item in shutil_dir.iterdir():
                    item.unlink()
                shutil_dir.rmdir()
            self.deliver(model_starts=starts)
            self.assertEqual(json.loads(self.executed[0][1])["modelStartsAllowed"], starts)

    def test_delivery_stops_at_the_first_failure_and_never_sends_the_admission_after_a_failed_lease(self):
        with self.assertRaisesRegex(p3.P3Refused, "EXEC_FAILED:a2a-factory-lease.json"):
            self.deliver(fail_on=1)
        self.assertEqual(len(self.executed), 1)

    def test_delivery_refuses_when_the_window_is_nearly_over(self):
        with self.assertRaisesRegex(p3.P3Refused, "DELIVERY_WINDOW_ALMOST_OVER"):
            self.deliver(now_values=[NOW, NOW + 260, NOW + 261])
        self.assertEqual(self.executed, [])

    def test_delivery_refuses_before_minting_when_the_pod_is_not_the_admitted_one(self):
        pod = json.loads((self.read / "pod.json").read_text())
        pod["status"]["phase"] = "Pending"
        save(self.read / "pod.json", pod)
        with self.assertRaisesRegex(p3.P3Refused, "POD_NOT_RUNNING"):
            self.deliver()
        self.assertEqual(self.executed, [])
        self.assertFalse((self.run_dir / "delivery").exists())

    def test_a_provider_row_is_installed_per_call_with_a_hash_checked_write_once_exec(self):
        call = "11111111-1111-1111-1111-111111111111"
        row = json.dumps({"litellm_call_id": call, "spend": 0.0}).encode()
        sent = []

        def run(argv, stdin):
            sent.append((argv, stdin))
            return 0, b"", b""
        result = p3.deliver_row(self.run_dir, self.read, row, kubectl="kubectl", run=run)
        self.assertEqual((result["callId"], result["sha256"]), (call, hashlib.sha256(row).hexdigest()))
        argv, stdin = sent[0]
        self.assertEqual(stdin, row)
        target = "/etc/dsh-native-admission/a2a-provider-rows/" + call + ".json"
        self.assertIn(target, argv[-1])
        self.assertIn(result["sha256"], argv[-1])
        self.assertIn('test ! -e "' + target + '"', argv[-1])   # write-once per call
        self.assertIn('mkdir -p "$d"', argv[-1])
        for bad, code in ((b"", "ROW_FILE_SIZE"), (b"x" * (64 * 1024 + 1), "ROW_FILE_SIZE"), (b"not json", "ROW_FILE_NOT_JSON"), (b"[]", "ROW_OBJECT_WITH_CALL_ID_REQUIRED"),
                          (b"{}", "ROW_OBJECT_WITH_CALL_ID_REQUIRED"), (b'{"litellm_call_id": 5}', "ROW_OBJECT_WITH_CALL_ID_REQUIRED"),
                          (b'{"litellm_call_id": "../../etc/passwd"}', "ROW_OBJECT_WITH_CALL_ID_REQUIRED"),
                          (b'{"litellm_call_id": "11111111-1111-1111-1111-11111111111G"}', "ROW_OBJECT_WITH_CALL_ID_REQUIRED")):
            with self.subTest(code + repr(bad[:20])), self.assertRaisesRegex(p3.P3Refused, code):
                p3.deliver_row(self.run_dir, self.read, bad, kubectl="kubectl", run=run)
        self.assertEqual(len(sent), 1)
        with self.assertRaisesRegex(p3.P3Refused, "EXEC_FAILED"):
            p3.deliver_row(self.run_dir, self.read, row, kubectl="kubectl", run=lambda a, s: (1, b"", b"x"))
        pod = json.loads((self.read / "pod.json").read_text())
        pod["status"]["phase"] = "Pending"
        save(self.read / "pod.json", pod)
        with self.assertRaisesRegex(p3.P3Refused, "POD_NOT_RUNNING"):   # no row is sent to a Pod that is not the admitted running one
            p3.deliver_row(self.run_dir, self.read, row, kubectl="kubectl", run=run)
        self.assertEqual(len(sent), 1)

    def test_every_delivery_script_is_write_once(self):
        for name in delivery.ALLOWED_TARGETS:
            argv = delivery.delivery_argv(self.spec, "sdk-qualification-abcde", "e" * 64, target_name=name)
            self.assertIn('test ! -e "/etc/dsh-native-admission/' + name + '"', argv[-1])
        with self.assertRaises(delivery.DeliveryRefused):
            delivery.delivery_argv(self.spec, "sdk-qualification-abcde", "e" * 64, target_name="../etc/passwd")

    def test_the_only_commands_are_the_allow_listed_exec_with_the_given_kubectl(self):
        self.deliver(kubectl="C:/tools/kubectl.exe")
        for argv, _ in self.executed:
            self.assertEqual((argv[0], argv[3], argv[4]), ("C:/tools/kubectl.exe", "exec", "-i"))
        self.assertEqual(delivery.ALLOWED_TARGETS, ("a2a-factory-lease.json", "official-sdk-server.json"))


class ContractTests(unittest.TestCase):
    def test_p3_contract_pins_the_runner_the_helper_and_the_objects(self):
        from scripts import make_sdk_qualification_contract as contracts
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for name in ("RUN_P3.ps1", "helper.py", "spec.json"):
                (root / name).write_bytes(name.encode())
                files.append(str(root / name))
            contract = contracts.build_contract(owner_commit="a" * 40, operation_id="b" * 32, namespace="dsh-a2a-qual", files=files, worktree=str(root), source_commit="c" * 40)
            self.assertEqual((contract["worktree"], contract["sourceCommit"], contract["executionCount"], contract["productionAllowed"]), (str(root), "c" * 40, 1, False))
            self.assertTrue(contracts.verify_contract(contract))
            (root / "helper.py").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "CONTRACT_HASH_DRIFT"):
                contracts.verify_contract(contract)
            with_case = contracts.build_contract(owner_commit="a" * 40, operation_id="b" * 32, namespace="dsh-a2a-qual", files=files, case_id="L3-strict", model_starts=0)
            self.assertEqual((with_case["caseId"], with_case["modelStarts"]), ("L3-strict", 0))
            for bad in (dict(case_id="L1"), dict(model_starts=1), dict(case_id="L1", model_starts=4), dict(case_id="L1", model_starts=True), dict(case_id="bad id", model_starts=1)):
                with self.subTest(bad), self.assertRaisesRegex(ValueError, "CASE_ID_AND_MODEL_STARTS_0_TO_3_REQUIRED_TOGETHER"):
                    contracts.build_contract(owner_commit="a" * 40, operation_id="b" * 32, namespace="dsh-a2a-qual", files=files, **bad)
            for kwargs in (dict(worktree=str(root)), dict(source_commit="c" * 40), dict(worktree=str(root / "missing"), source_commit="c" * 40)):
                with self.subTest(kwargs), self.assertRaisesRegex(ValueError, "WORKTREE_AND_SOURCE_COMMIT_REQUIRED_TOGETHER"):
                    contracts.build_contract(owner_commit="a" * 40, operation_id="b" * 32, namespace="dsh-a2a-qual", files=files, **kwargs)


if __name__ == "__main__":
    unittest.main()
