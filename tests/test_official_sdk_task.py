import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts.official_sdk_task import qualify, guarded_endpoint


class OfficialSDKTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.calls = []

    def factory(self, **config):
        self.calls.append(config)
        parent = self
        class Harness:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def run(self, prompt, session_id):
                parent.calls.append((prompt, session_id))
                return SimpleNamespace(finish_reason="completed", final_response="CHECKED")
        return Harness()

    def run_candidate(self, **overrides):
        kwargs = dict(task_id="sdk-check", project=self.project,
                      state_root=self.root, guard_url="http://127.0.0.1:12345/v1",
                      harness_factory=self.factory, version=lambda _: "0.2.1rc2")
        kwargs.update(overrides)
        return qualify("Return CHECKED", **kwargs)

    def test_official_factory_receives_private_full_profile_and_guard_only(self):
        self.assertEqual(self.run_candidate(), "CHECKED")
        config = self.calls[0]
        self.assertEqual(config["profile"], "sdk")
        self.assertEqual(config["base_url"], "http://127.0.0.1:12345/v1")
        self.assertEqual(config["api_key"], "local-guard-placeholder")
        self.assertTrue(Path(config["dsh_home"]).is_dir())
        patch = Path(config["patches"][0]).read_text()
        self.assertIn("mode: read-only", patch)
        self.assertIn("id: llm-retry\n  disabled: true", patch)
        saved = json.loads((self.root / "sdk-check/invocation.json").read_text())
        self.assertNotIn("prompt", saved)
        self.assertFalse(saved["automaticReplay"])

    def test_second_adapter_start_refused_before_factory(self):
        self.run_candidate()
        with self.assertRaises(FileExistsError): self.run_candidate()
        self.assertEqual(len(self.calls), 2)

    def test_mismatched_runtime_version_refuses_before_reservation(self):
        with self.assertRaisesRegex(ValueError, "VERSION_MISMATCH"):
            self.run_candidate(version=lambda _: "0.2.1")
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / "sdk-check").exists())

    def test_external_or_credential_bearing_endpoint_refused(self):
        for url in ("https://api.deepseek.com/v1", "http://localhost:12/v1",
                    "http://secret@127.0.0.1:12/v1", "http://127.0.0.1:12/v1?x=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                guarded_endpoint(url)

    def test_failed_start_cannot_be_automatically_replayed(self):
        def fail(**config): raise RuntimeError("synthetic initialization failure")
        with self.assertRaises(RuntimeError): self.run_candidate(harness_factory=fail)
        with self.assertRaises(FileExistsError): self.run_candidate()
        self.assertEqual(self.calls, [])


if __name__ == "__main__": unittest.main()
