"""Protected SDK server composition fixtures; no SDK, process or model calls."""
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from scripts import official_sdk_bootstrap as bootstrap


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.path = "/etc/dsh-native-admission/official-sdk-server.json"
        self.module = "/opt/dsh/scripts/admitted_official_sdk_scope.py"
        self.files = {path: ("synthetic " + role).encode() for role, path in bootstrap.SOURCES.items()}
        self.files[self.module] = b"# Synthetic protected factory source; not executed\n"
        self.config = {"kind": "DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1", "mode": "qualification",
            "subject": "owner", "generation": "g1", "expiresAt": 1100,
            "sourceCommit": "a" * 40, "imageDigest": "sha256:" + "b" * 64,
            "packageAdmissionSha256": "c" * 64, "scopeModule": self.module,
            "deploymentBinding": {"namespace": "llm", "namespaceUID": "11111111-1111-1111-1111-111111111111",
                "podUID": "22222222-2222-2222-2222-222222222222", "workloadUID": "33333333-3333-3333-3333-333333333333",
                "environment": "test", "workloadRole": "qualification"},
            "scopeSha256": hashlib.sha256(self.files[self.module]).hexdigest(),
            "sources": {role: hashlib.sha256(self.files[path]).hexdigest()
                for role, path in bootstrap.SOURCES.items()}}
        self.server = SimpleNamespace(); self.registry = SimpleNamespace(tasks={})
        self.observed = dict(self.config["deploymentBinding"])
        self.package = Mock(return_value={"admissionSha256": "c" * 64})
        self.scope = SimpleNamespace(admission_state=lambda subject, generation: {
            "sourceCommit": self.config["sourceCommit"], "imageDigest": self.config["imageDigest"],
            "controllerSha256": self.config["sources"]["controller"], "scopeSha256": self.config["scopeSha256"]})
        self.factory = Mock(return_value={"scope": self.scope, "guardFactory": Mock()})
        self.loader = Mock(return_value=self.factory)
        self.service = SimpleNamespace(qualified=True, recover_task=Mock())
        self.runner = Mock(return_value=self.service)
    def reader(self, path, limit):
        raw = json.dumps(self.config).encode() if path == self.path else self.files[path]
        if len(raw) > limit: raise ValueError("synthetic size refusal")
        return raw
    def configure(self, **kwargs):
        return bootstrap.configure(self.server, self.registry, self.path,
            qualification_allowed=True, reader=self.reader, package_check=self.package,
            factory_loader=self.loader, runner_factory=self.runner, clock=lambda: self.now,
            deployment_observer=lambda: dict(self.observed), **kwargs)
    def test_no_descriptor_does_not_load_or_enable(self):
        self.assertFalse(bootstrap.configure(self.server, self.registry, None, factory_loader=self.loader))
        self.loader.assert_not_called(); self.assertFalse(hasattr(self.server, "sdk_service"))
    def test_default_and_production_refuse_before_factory(self):
        with self.assertRaisesRegex(ValueError, "TEST_ADMISSION_REQUIRED"):
            bootstrap.configure(self.server, self.registry, self.path, factory_loader=self.loader)
        self.config["mode"] = "production"
        with self.assertRaisesRegex(ValueError, "INVALID_OFFICIAL"): self.configure()
        self.loader.assert_not_called()
    def test_exact_source_composition_attaches_only_injected_runner(self):
        self.assertTrue(self.configure())
        self.assertIs(self.server.sdk_service, self.service)
        self.loader.assert_called_once_with(self.module, self.files[self.module])
        self.factory.assert_called_once_with(registry=self.registry, admission=self.config)
        self.assertEqual(self.runner.call_args.kwargs["subject"], "owner")
    def test_wrong_child_or_scope_source_prevents_factory_execution(self):
        self.files[bootstrap.SOURCES["controller"]] += b"changed"
        with self.assertRaisesRegex(ValueError, "CONTROLLER_SOURCE_MISMATCH"): self.configure()
        self.loader.assert_not_called()
        self.files[bootstrap.SOURCES["controller"]] = b"synthetic controller"
        self.files[self.module] += b"changed"
        with self.assertRaisesRegex(ValueError, "SCOPE_SOURCE_MISMATCH"): self.configure()
        self.loader.assert_not_called()
    def test_package_change_prevents_factory(self):
        self.package.return_value = {"admissionSha256": "d" * 64}
        with self.assertRaisesRegex(ValueError, "PACKAGE_BINDING_CHANGED"): self.configure()
        self.loader.assert_not_called()
    def test_expired_and_long_admission_refused(self):
        for expiry in (999, 1000, 1301, float("nan")):
            self.config["expiresAt"] = expiry
            with self.assertRaises(ValueError): self.configure()
        self.loader.assert_not_called()
    def test_current_descriptor_replacement_revokes_configured_runner(self):
        self.configure(); check = self.runner.call_args.kwargs["admission_check"]
        self.assertEqual(check()["admissionSha256"], "c" * 64)
        self.config["generation"] = "g2"
        with self.assertRaisesRegex(ValueError, "REVOKED"): check()
    def test_current_descriptor_expiry_revokes_configured_runner(self):
        self.configure(); check = self.runner.call_args.kwargs["admission_check"]
        self.now = 1100
        with self.assertRaisesRegex(ValueError, "REVOKED"): check()
    def test_recovery_is_owner_bound_and_does_not_create_task(self):
        own = SimpleNamespace(native_sdk={"subject": "owner"})
        other = SimpleNamespace(native_sdk={"subject": "other"})
        plain = SimpleNamespace(native_sdk=None)
        self.registry.tasks = {"own": own, "other": other, "plain": plain}
        self.configure(); self.service.recover_task.assert_called_once_with("owner", own)
        self.assertEqual(len(self.registry.tasks), 3)
    def test_unqualified_runner_not_exposed(self):
        self.service.qualified = False
        with self.assertRaisesRegex(ValueError, "NOT_FRESHLY_QUALIFIED"): self.configure()
        self.assertFalse(hasattr(self.server, "sdk_service"))
    def test_changed_supervisor_image_observation_revokes_runner(self):
        self.configure(); check = self.runner.call_args.kwargs["admission_check"]
        self.scope.admission_state = lambda subject, generation: {"imageDigest": "sha256:" + "e" * 64}
        with self.assertRaisesRegex(ValueError, "IMAGE_BINDING_MISMATCH"): check()
    def test_scope_outside_protected_image_refused(self):
        for path in ("/workspace/agent.py", "/opt/dsh/scripts/../agent.py", "/opt/dsh/scripts/fake.txt"):
            self.config["scopeModule"] = path
            with self.assertRaises(ValueError): self.configure()
        self.loader.assert_not_called()
    def test_flag_and_descriptor_alone_cannot_enable_sdk(self):
        with self.assertRaisesRegex(ValueError, "INDEPENDENT_TEST_DEPLOYMENT_OBSERVER_REQUIRED"):
            bootstrap.configure(self.server, self.registry, self.path, qualification_allowed=True,
                reader=self.reader, factory_loader=self.loader)
        self.loader.assert_not_called()
    def test_actual_production_identity_refused_despite_test_flag_and_descriptor(self):
        self.observed["environment"] = "production"
        with self.assertRaisesRegex(ValueError, "NON_TEST_OR_FOREIGN"): self.configure()
        self.loader.assert_not_called()
    def test_replaced_pod_or_namespace_revokes_configured_sdk(self):
        self.configure(); check = self.runner.call_args.kwargs["admission_check"]
        self.observed["podUID"] = "44444444-4444-4444-4444-444444444444"
        with self.assertRaisesRegex(ValueError, "NON_TEST_OR_FOREIGN"): check()
        self.observed = dict(self.config["deploymentBinding"])
        self.observed["namespaceUID"] = "55555555-5555-5555-5555-555555555555"
        with self.assertRaisesRegex(ValueError, "NON_TEST_OR_FOREIGN"): check()
    def test_each_direct_bound_source_mutation_revokes_configured_sdk(self):
        self.configure(); check = self.runner.call_args.kwargs["admission_check"]
        for role, path in bootstrap.SOURCES.items():
            with self.subTest(role=role):
                original = self.files[path]; self.files[path] += b"changed after composition"
                with self.assertRaisesRegex(ValueError, "CONTROLLER_SOURCE_MISMATCH"): check()
                self.files[path] = original
        self.files[self.module] += b"changed after composition"
        with self.assertRaisesRegex(ValueError, "SCOPE_SOURCE_MISMATCH"): check()


if __name__ == "__main__": unittest.main()
