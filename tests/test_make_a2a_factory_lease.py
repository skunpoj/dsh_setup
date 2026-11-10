"""The lease minter: what it returns is accepted by the REAL ProtectedA2AFactory._fresh; every drift is refused. No cluster, no credential."""
import copy
import json
import unittest

from scripts import a2a_factory_contract as factory
from scripts import make_a2a_factory_lease as minter

NOW = 1_800_000_000
ARGS = dict(subject="qualification-broker", generation="gen-1", namespace="dsh-a2a-qual", namespace_uid="11111111-1111-1111-1111-111111111111",
            node_name="worker-2", image="registry.example/dsh-runtime@sha256:" + "a" * 64, source_commit="c" * 40, package_admission_sha256="d" * 64, now=NOW)


def mint(**override):
    values = dict(ARGS)
    values.update(override)
    return minter.mint(**values)


class LeaseTests(unittest.TestCase):
    def test_exact_keys_constants_and_window(self):
        raw, lease = mint()
        self.assertEqual(set(lease), {"subject", "generation", "namespace", "namespaceUID", "nodeName", "image", "sourceCommit", "packageAdmissionSha256", "provider",
                                      "resourceBudget", "expiresAt", "modelStartsAllowed", "rollbackOwner"})
        self.assertEqual(lease["provider"], factory.PROVIDER)
        self.assertEqual(lease["resourceBudget"], factory.BUDGET)
        self.assertEqual((lease["expiresAt"], lease["modelStartsAllowed"], lease["rollbackOwner"]), (NOW + 270, 1, "operator-session"))
        self.assertEqual(json.loads(raw), lease)

    def test_real_factory_refuses_every_drift_the_minter_would_never_emit(self):
        raw, lease = mint()
        cases = {"window above 300": lambda v: v.update(expiresAt=NOW + 301), "expired": lambda v: v.update(expiresAt=NOW - 1),
                 "extra key": lambda v: v.update(extra=1), "missing key": lambda v: v.pop("rollbackOwner"),
                 "other namespace UID": lambda v: v.update(namespaceUID="44444444-4444-4444-4444-444444444444"),
                 "other node": lambda v: v.update(nodeName="dagpu-gn-p1"), "other image": lambda v: v.update(image="registry.example/other@sha256:" + "b" * 64),
                 "other provider": lambda v: v["provider"].update(model="other-model"), "fallback on": lambda v: v["provider"].update(externalFallback=True),
                 "budget changed": lambda v: v["resourceBudget"].update(workerCPU="4"), "starts 4": lambda v: v.update(modelStartsAllowed=4),
                 "starts bool": lambda v: v.update(modelStartsAllowed=True), "owner bad": lambda v: v.update(rollbackOwner="bad owner!")}
        for label, change in cases.items():
            with self.subTest(label):
                broken = copy.deepcopy(lease)
                change(broken)
                with self.assertRaises(minter.LeaseRefused):
                    minter.selfcheck((json.dumps(broken, sort_keys=True) + "\n").encode(), **{k: v for k, v in ARGS.items()})

    def test_the_minter_refuses_bad_inputs_before_building(self):
        for override, code in ((dict(namespace="dsh-openshell-test-20261102"), "A2A_OWNED_TEST_NAMESPACE_REQUIRED"), (dict(namespace_uid="nope"), "NAMESPACE_UID_REQUIRED"),
                               (dict(node_name=""), "NODE_NAME_REQUIRED"), (dict(image="registry.example/x:latest"), "IMAGE_REFERENCE_REQUIRED"),
                               (dict(source_commit="short"), "SOURCE_COMMIT_REQUIRED"), (dict(package_admission_sha256="0" * 64), "PACKAGE_ADMISSION_SHA256_REQUIRED"),
                               (dict(model_starts=4), "MODEL_STARTS_0_TO_3_REQUIRED"), (dict(model_starts=-1), "MODEL_STARTS_0_TO_3_REQUIRED"),
                               (dict(rollback_owner=""), "INVALID_ROLLBACK_OWNER"), (dict(ttl=296), "TTL_1_TO_295_REQUIRED"), (dict(subject="a b"), "INVALID_SUBJECT_OR_GENERATION")):
            with self.subTest(code), self.assertRaisesRegex(minter.LeaseRefused, code):
                mint(**override)

    def test_model_starts_and_a_shorter_window_are_accepted_by_the_factory(self):
        for starts in (0, 1, 2, 3):
            _, lease = mint(model_starts=starts)
            self.assertEqual(lease["modelStartsAllowed"], starts)
        _, short = mint(ttl=240)
        self.assertEqual(short["expiresAt"], NOW + 240)

    def test_node_comes_from_the_live_pod_and_never_from_an_excluded_node(self):
        pod = {"kind": "Pod", "spec": {"nodeName": "worker-2"}}
        self.assertEqual(minter.node_from_pod(pod, excluded_nodes=["dagpu-gn-p1"]), "worker-2")
        for bad, code in (({"kind": "Pod", "spec": {}}, "POD_NOT_SCHEDULED"), ({"kind": "Pod", "spec": {"nodeName": "dagpu-gn-p1"}}, "POD_ON_AN_EXCLUDED_NODE"),
                          ({"kind": "Node"}, "POD_READBACK_REQUIRED")):
            with self.subTest(code), self.assertRaisesRegex(minter.LeaseRefused, code):
                minter.node_from_pod(bad, excluded_nodes=["dagpu-gn-p1"])


if __name__ == "__main__":
    unittest.main()
