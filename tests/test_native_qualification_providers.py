"""Provider runtime assembly of the native qualification broker: real controller/factory/capture/retirement classes, fake files,
fake Kubernetes API object, fake clock. No network, process or model call."""
import copy
import json
from pathlib import Path
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest

from scripts import native_qualification_inputs as inputs
from scripts import native_qualification_providers as providers
from scripts.a2a_factory_contract import BUDGET, PROVIDER, ProtectedA2AFactory

NS_UID = "11111111-1111-4111-8111-111111111111"
POD_UID = "22222222-2222-4222-8222-222222222222"
WL_UID = "33333333-3333-4333-8333-333333333333"
DIGEST = "sha256:" + "a" * 64
IMAGE = "registry.invalid/dsh@" + DIGEST
COMMIT = "b" * 40
NS = "dsh-a2a-qual"
NODE = "node-1"
PACKAGE = "c" * 64
NOW = 1000.0


def unique_json(raw):
    return json.loads(raw.decode())


class Fixture(unittest.TestCase):
    def setUp(self):
        self.binding = dict(namespace=NS, namespaceUID=NS_UID, podUID=POD_UID, workloadUID=WL_UID,
                            environment="test", workloadRole="qualification")
        self.descriptor = dict(kind="DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1", mode="qualification", subject="qualification-broker",
            generation="p3-abc", expiresAt=NOW + 250, sourceCommit=COMMIT, imageDigest=DIGEST, packageAdmissionSha256=PACKAGE,
            scopeModule="/opt/dsh/scripts/a2a_sdk_scope_factory.py", scopeSha256="d" * 64,
            sources={"controller": "e" * 64}, deploymentBinding=copy.deepcopy(self.binding))
        self.lease = dict(subject="qualification-broker", generation="p3-abc", namespace=NS, namespaceUID=NS_UID, nodeName=NODE,
            image=IMAGE, sourceCommit=COMMIT, packageAdmissionSha256=PACKAGE, provider=copy.deepcopy(PROVIDER),
            resourceBudget=copy.deepcopy(BUDGET), expiresAt=NOW + 250, modelStartsAllowed=1, rollbackOwner="operator")
        self.policy = {"policies": {"qual": dict(claim="workspace-claim", subpath="qual", writes=False,
                                                  brokerPath="/workspace", credentialSecret="cred-secret")}}
        self.files = {"/admission": self.descriptor, "/lease": self.lease, "/policy": self.policy, "/rows": {}}
        self.registry = SimpleNamespace(tasks={}, lock=RLock())

    def reader(self, path, limit):
        if path == inputs.MODULE_FILE:
            return b"module-bytes"
        return json.dumps(self.files[path]).encode()

    def build(self, **over):
        args = dict(registry=self.registry, namespace=NS, node_name=NODE, observer=lambda: copy.deepcopy(self.binding),
                    reader=self.reader, unique_json=unique_json, clock=lambda: NOW,
                    make_api=lambda ns, uid: SimpleNamespace(namespace=ns, namespace_uid=uid),
                    descriptor_path="/admission", lease_path="/lease", policy_path="/policy", rows_path="/rows")
        args.update(over)
        return providers.assemble(**args)


class AssemblyTests(Fixture):
    def test_the_factory_is_bound_once_and_its_fresh_admission_accepts_the_delivered_lease(self):
        out = self.build()
        factory = out["factory"]
        self.assertIs(type(factory), ProtectedA2AFactory)
        self.assertIs(self.registry.protected_a2a_factory, factory)
        self.assertEqual(factory._fresh()["modelStartsAllowed"], 1)
        self.assertIs(factory.dependencies["executionAdmission"], factory.sdk.execution_admission)
        self.assertIs(factory.sdk.execution_admission, factory.cli.execution_admission)
        self.assertEqual(out["cli_service"].subject, "qualification-broker")

    def test_a_second_assembly_on_the_same_registry_is_refused(self):
        self.build()
        with self.assertRaisesRegex(ValueError, "PROTECTED_FACTORY_ALREADY_BOUND_NO_REPLACEMENT"):
            self.build()

    def test_workspace_resolution_returns_only_the_admitted_broker_path_and_refuses_unknown_projects(self):
        resolver = self.build()["cli_service"].workspace_resolver
        self.assertEqual(resolver("qual"), "/workspace")
        with self.assertRaisesRegex(ValueError, "WORKSPACE_PROJECT_NOT_ADMITTED"):
            resolver("other")

    def test_foreign_node_namespace_image_commit_or_subject_are_refused(self):
        for key, value, kwargs in (("nodeName", "other", {}), ("image", "registry.invalid/dsh@sha256:" + "f" * 64, {}),
                                   ("sourceCommit", "9" * 40, {}), ("subject", "intruder", {}),
                                   ("namespaceUID", "44444444-4444-4444-8444-444444444444", {}),
                                   ("generation", "other", {})):
            with self.subTest(key=key):
                self.setUp()
                self.lease[key] = value
                self.files["/lease"] = self.lease
                with self.assertRaises(ValueError):
                    self.build()
        self.setUp()
        with self.assertRaisesRegex(ValueError, "EXACT_PLACEMENT_FOR_THIS_POD_REQUIRED"):
            self.build(node_name="other-node")
        with self.assertRaisesRegex(ValueError, "EXACT_PLACEMENT_FOR_THIS_POD_REQUIRED"):
            self.build(namespace="dsh-a2a-other")

    def test_an_expired_lease_is_refused_when_the_factory_is_asked_for_fresh_admission(self):
        factory = self.build()["factory"]
        self.lease["expiresAt"] = NOW - 1
        with self.assertRaisesRegex(ValueError, "FINITE_EXACT_PROTECTED_FACTORY_ADMISSION_REQUIRED"):
            factory._fresh()

    def test_a_changed_placement_is_refused(self):
        moved = copy.deepcopy(self.binding)
        factory = self.build(observer=lambda: moved)["factory"]
        moved["podUID"] = "55555555-5555-4555-8555-555555555555"
        with self.assertRaisesRegex(ValueError, "PROTECTED_FACTORY_PLACEMENT_CHANGED"):
            factory._fresh()

    def test_retirement_without_a_worker_record_is_refused_and_rollback_only_records(self):
        factory = self.build()["factory"]
        task = SimpleNamespace(id="a" * 32, correlation_id="b" * 32, authenticated_subject="qualification-broker",
                               request=dict(runtime="sdk", project="qual", writes=False), directory=Path(tempfile.mkdtemp()), persistence_lock=RLock())
        binding = dict(subject="qualification-broker", generation="p3-abc", taskId=task.id, correlationId=task.correlation_id,
                       project="qual", runtime="sdk", writes=False, promptSha256="0" * 64)
        with self.assertRaises(ValueError):
            factory.dependencies["retirement"](task, binding)
        record = factory.dependencies["rollback"](task, binding)
        self.assertEqual((record["mutations"], record["rollbackVerified"]), (0, False))


class GuardHandleTests(unittest.TestCase):
    def test_the_handle_matches_what_the_sdk_session_checks(self):
        from scripts.official_sdk_task import guarded_endpoint
        task = SimpleNamespace(id="a" * 32, correlation_id="b" * 32)
        with providers.guard_factory(task, dict(taskId=task.id, correlationId=task.correlation_id)) as guard:
            self.assertEqual(guarded_endpoint(guard.base_url), "http://127.0.0.1:4001/v1")
            self.assertEqual((guard.task_id, guard.correlation_id, guard.temperature), (task.id, task.correlation_id, 0))

    def test_a_foreign_binding_is_refused(self):
        task = SimpleNamespace(id="a" * 32, correlation_id="b" * 32)
        with self.assertRaisesRegex(ValueError, "EXACT_GUARD_TASK_BINDING_REQUIRED"):
            providers.guard_factory(task, dict(taskId="c" * 32, correlationId=task.correlation_id))

    def test_the_handle_does_not_swallow_a_body_error(self):
        handle = providers.WorkerGuardHandle("a" * 32, "b" * 32)
        with self.assertRaises(RuntimeError):
            with handle:
                raise RuntimeError("body")


if __name__ == "__main__":
    unittest.main()
