"""The delivery argv is fixed text with one validated hash; the contract refuses drift. Nothing is executed against a cluster."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import make_sdk_qualification_contract as contract_tool
from scripts import sdk_qualification_delivery as delivery
from scripts import sdk_qualification_k8s as q


def spec(**override):
    value = {"namespace": "dsh-a2a-qual", "jobName": "sdk-qualification", "containerName": "broker",
             "image": "registry.example/dsh-runtime@sha256:" + "a" * 64, "command": ["python3", "-I", "/opt/dsh/container/dsh-native-qualification-broker.py"], "identityRoute": "secret-client-certificate",
             "observerSubject": "sdk-qualification-observer", "podSecurity": "baseline", "activeDeadlineSeconds": 300,
             "resources": {"cpu": 2, "memoryBytes": 4 * q.GIB, "ephemeralBytes": 2 * q.GIB}, "wheelSha256": "1" * 64, "nodeName": None, "excludedNodes": [], "workspaceStorageClass": "topolvm-immediate",
             "workspaceBytes": q.GIB, "clientPodLabels": {"app": "c"}, "apiServerTargets": [{"cidr": "192.0.2.54/32", "port": 6443}, {"cidr": "192.0.2.1/32", "port": 443}],
             "litellmPodLabels": {"app": "l"}}
    value.update(override)
    return value


class DeliveryTests(unittest.TestCase):
    def test_argv_is_a_single_exec_with_a_fixed_script(self):
        s = spec()
        digest = hashlib.sha256(b"x").hexdigest()
        argv = delivery.delivery_argv(s, "sdk-qualification-abcde", digest)
        self.assertEqual(argv[:9], ["kubectl", "-n", "dsh-a2a-qual", "exec", "-i", "sdk-qualification-abcde", "-c", "broker", "--"])
        script = argv[-1]
        for needle in ("chmod 0755", "sha256sum", digest, "chmod 0444", "mv ", "/etc/dsh-native-admission/official-sdk-server.json"):
            self.assertIn(needle, script)
        self.assertNotIn(";;", script)
        self.assertEqual(script.count(digest), 1)

    def test_script_is_valid_shell_and_installs_only_the_matching_content(self):
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("no bash")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            body = b'{"kind": "DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1"}\n'
            digest = hashlib.sha256(body).hexdigest()
            script = delivery.delivery_argv(spec(), "p", digest)[-1].replace("/etc/dsh-native-admission", root.as_posix())
            ok = subprocess.run([bash, "-c", script], input=body, capture_output=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual((root / "official-sdk-server.json").read_bytes(), body)
            self.assertFalse((root / ".incoming").exists())
            os.chmod(root / "official-sdk-server.json", 0o644)   # 0444 is right in the Pod; Windows cannot delete a read-only file
            (root / "official-sdk-server.json").unlink()
            bad = subprocess.run([bash, "-c", script], input=body + b" ", capture_output=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse((root / "official-sdk-server.json").exists())   # a body with another hash is never installed

    def test_plan_delivers_the_lease_first_and_the_server_admission_last(self):
        s = spec()
        lease_sha, server_sha = hashlib.sha256(b"lease").hexdigest(), hashlib.sha256(b"server").hexdigest()
        plan = delivery.delivery_plan(s, "pod", [(delivery.LEASE, lease_sha), (delivery.SERVER_ADMISSION, server_sha)])
        self.assertEqual(len(plan), 2)
        self.assertIn("/etc/dsh-native-admission/a2a-factory-lease.json", plan[0][-1])
        self.assertIn(lease_sha, plan[0][-1])
        self.assertIn("/etc/dsh-native-admission/official-sdk-server.json", plan[1][-1])
        for bad in ([(delivery.SERVER_ADMISSION, server_sha), (delivery.LEASE, lease_sha)], [(delivery.LEASE, lease_sha)],
                    [(delivery.SERVER_ADMISSION, server_sha), (delivery.SERVER_ADMISSION, server_sha)],
                    [("other.json", lease_sha), (delivery.SERVER_ADMISSION, server_sha)]):
            with self.assertRaises(delivery.DeliveryRefused):
                delivery.delivery_plan(s, "pod", bad)
        with self.assertRaisesRegex(delivery.DeliveryRefused, "TARGET_NOT_ALLOWED"):
            delivery.delivery_argv(s, "pod", lease_sha, target_name="../etc/passwd")

    def test_refusals(self):
        s = spec()
        for pod in ("Bad_Name", "x; rm -rf /", "", "a" * 70):
            with self.assertRaises(delivery.DeliveryRefused):
                delivery.delivery_argv(s, pod, "1" * 64)
        for digest in ("0" * 64, "zz", "1" * 63, None):
            with self.assertRaises(delivery.DeliveryRefused):
                delivery.delivery_argv(s, "pod", digest)


class ContractTests(unittest.TestCase):
    def test_build_verify_and_drift(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.json"
            b = Path(folder) / "b.sh"
            a.write_bytes(b"1")
            b.write_bytes(b"2")
            contract = contract_tool.build_contract(owner_commit="a" * 40, operation_id="b" * 32, namespace="dsh-a2a-qual", files=[a, b])
            self.assertTrue(contract_tool.verify_contract(contract))
            b.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "CONTRACT_HASH_DRIFT"):
                contract_tool.verify_contract(contract)
            for kwargs in (dict(owner_commit="short"), dict(operation_id="0" * 32), dict(namespace="dsh-openshell-x"), dict(files=[])):
                values = dict(owner_commit="a" * 40, operation_id="b" * 32, namespace="dsh-a2a-qual", files=[a])
                values.update(kwargs)
                with self.assertRaises(ValueError):
                    contract_tool.build_contract(**values)

    def test_cli_is_exclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.json"
            a.write_bytes(b"1")
            out = Path(folder) / "c.json"
            argv = ["--owner-commit", "a" * 40, "--operation-id", "b" * 32, "--namespace", "dsh-a2a-qual", "--out", str(out), str(a)]
            self.assertEqual(contract_tool.main(argv), 0)
            self.assertEqual(json.loads(out.read_text())["kind"], contract_tool.KIND)
            self.assertEqual(contract_tool.main(argv), 2)


if __name__ == "__main__":
    unittest.main()
