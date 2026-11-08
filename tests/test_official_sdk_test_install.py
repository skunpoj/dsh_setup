"""Synthetic wheel intake; never runs pip, a runtime, Docker or a provider."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import test_official_sdk_producer_receipt as fixtures
from scripts.prepare_official_sdk_test_install import prepare, read_artifact, SDK_NAME, RUNTIME_NAME


class TestImageIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "input"
        self.directory.mkdir()
        fixture = fixtures.ProducerReceiptTests()
        fixture.setUp()
        self.sdk, self.runtime = fixture.sdk, fixture.runtime
        self.raw = json.dumps(fixture.receipt).encode()
        self.trusted = hashlib.sha256(self.raw).hexdigest()
        (self.directory / SDK_NAME).write_bytes(self.sdk)
        (self.directory / RUNTIME_NAME).write_bytes(self.runtime)
        (self.directory / "producer-receipt.json").write_bytes(self.raw)
        self.output = self.root / "verified"

    def run_intake(self, trusted=None):
        return prepare(self.directory, self.output, trusted or self.trusted)

    def test_verified_input_yields_pip_hash_lock_and_native_identity(self):
        result = self.run_intake()
        lock = (self.output / "requirements.txt").read_text()
        self.assertEqual(len(lock.splitlines()), 2)
        self.assertIn("--hash=sha256:" + hashlib.sha256(self.sdk).hexdigest(), lock)
        self.assertIn("--hash=sha256:" + hashlib.sha256(self.runtime).hexdigest(), lock)
        native = json.loads((self.output / "official-sdk-runtime.json").read_text())
        self.assertEqual(native["runtimeSha256"], result["runtimeSha256"])
        self.assertEqual(native["sdkVersion"], "0.2.2a2")
        self.assertFalse(result["applicationImageBound"])
        self.assertNotIn("applicationImage", result)

    def test_directory_cannot_supply_its_own_trust(self):
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_RELEASE_RECEIPT"):
            self.run_intake("f" * 64)
        self.assertFalse(self.output.exists())

    def test_changed_wheel_refused_before_any_output(self):
        (self.directory / SDK_NAME).write_bytes(self.sdk + b"changed")
        with self.assertRaises(ValueError):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_extra_inputs_are_not_silently_copied_into_image(self):
        (self.directory / "unrelated.txt").write_text("synthetic")
        with self.assertRaisesRegex(ValueError, "EXACT_TEST_WHEEL_INPUTS_REQUIRED"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_output_is_create_only_and_preserves_prior_bytes(self):
        self.output.mkdir()
        marker = self.output / "prior"
        marker.write_bytes(b"retained")
        with self.assertRaises(FileExistsError):
            self.run_intake()
        self.assertEqual(marker.read_bytes(), b"retained")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_missing_pair_cannot_generate_native_admission(self):
        (self.directory / RUNTIME_NAME).unlink()
        with self.assertRaisesRegex(ValueError, "EXACT_TEST_WHEEL_INPUTS_REQUIRED"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_artifact_read_rejects_actual_oversize_file_before_intake(self):
        path = self.root / "oversize"
        path.write_bytes(b"too large")
        with self.assertRaisesRegex(ValueError, "BOUNDED_REGULAR_ARTIFACT_REQUIRED"):
            read_artifact(path, 4)

    def test_same_version_base_must_reinstall_supplied_hashed_wheels_offline(self):
        dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile.sdk-test"
        text = dockerfile.read_text()
        install = next(line for line in text.splitlines()
                       if "pip --isolated" in line and " install " in line)
        for flag in ("--force-reinstall", "--no-cache-dir", "--no-index", "--no-deps", "--require-hashes"):
            self.assertIn(flag, install)
        self.assertIn("RUN --network=none", text)

    def test_overlay_rechecks_a2a_and_sdk_after_install(self):
        text = (Path(__file__).resolve().parents[1] / "Dockerfile.sdk-test").read_text()
        install_at = text.index("pip --isolated")
        a2a_at = text.index("-p 'test_a2a*.py'")
        sdk_at = text.index("-p 'test_official_sdk*.py'")
        cleanup_at = text.index("rm /tmp/dsh-sdk-input/*")
        self.assertLess(install_at, a2a_at)
        self.assertLess(a2a_at, sdk_at)
        self.assertLess(sdk_at, cleanup_at)
        self.assertIn("PYTHONPATH=/opt/dsh /opt/dsh/deepagents/bin/python", text)
