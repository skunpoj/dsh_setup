"""Pure child-entry parsing/environment tests; never exec a runtime."""
import importlib.util
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("native_entry_source",
    Path(__file__).resolve().parents[1] / "container/dsh-official-sdk-runtime.py")
entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)


class RuntimeEntryTests(unittest.TestCase):
    def admission(self):
        return {"kind": "DSH_OFFICIAL_SDK_RUNTIME_V1", "sourceCommit": entry.SOURCE,
            "sdkVersion": entry.VERSION, "runtimeVersion": entry.VERSION,
            "runtimeSha256": "a" * 64}

    def environment(self):
        return {"DSH_UNATTENDED_TASK": "a" * 32, "DSH_CORRELATION_ID": "b" * 32,
            "DSH_GUARDED_MODEL_BASE_URL": "http://127.0.0.1:7777/v1",
            "HOME": "/state/web-tasks/" + "a" * 32 + "/official-sdk-home"}

    def test_exact_admission_and_no_placeholder_or_mixed_pair(self):
        self.assertEqual(entry.parse_admission(json.dumps(self.admission())), self.admission())
        for field, value in (("runtimeSha256", "0" * 64), ("sdkVersion", "0.2.1rc2"),
                             ("sourceCommit", "c" * 40), ("unexpected", True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                entry.parse_admission(json.dumps({**self.admission(), field: value}))

    def test_duplicate_admission_fields_refused(self):
        raw = json.dumps(self.admission())[:-1] + ', "runtimeVersion": "0.2.1rc2"}'
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            entry.parse_admission(raw)

    def test_child_environment_is_allowlist_not_parent_snapshot(self):
        values = {**self.environment(), "CUSTOM_TOKEN": "SYNTHETIC_PRIVATE",
                  "OPENAI_API_KEY": "SYNTHETIC_PROVIDER", "PYTHONPATH": "/untrusted"}
        child = entry.child_environment(values)
        for key in ("CUSTOM_TOKEN", "OPENAI_API_KEY", "PYTHONPATH"): self.assertNotIn(key, child)
        self.assertNotIn("SYNTHETIC_PRIVATE", str(child))
        self.assertEqual(child["DEEPSEEK_API_KEY"], "local-guard-placeholder")
        self.assertEqual(child["DEEPSEEK_BASE_URL"], values["DSH_GUARDED_MODEL_BASE_URL"])

    def test_cross_task_home_and_external_endpoint_refused(self):
        for change in ({"HOME": "/state/web-tasks/other/official-sdk-home"},
                       {"DSH_GUARDED_MODEL_BASE_URL": "https://example.com/v1"},
                       {"DSH_UNATTENDED_TASK": "../escape"}, {"DSH_CORRELATION_ID": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                entry.child_environment({**self.environment(), **change})

    def test_runtime_payload_must_match_admission_and_wheel_record_without_execution(self):
        payload = b"SYNTHETIC_NOT_AN_EXECUTABLE"
        digest = hashlib.sha256(payload).digest()
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "native-runtime"; binary.write_bytes(payload)
            record = SimpleNamespace(size=len(payload), hash=SimpleNamespace(mode="sha256",
                value=base64.urlsafe_b64encode(digest).rstrip(b"=").decode()))
            distribution = SimpleNamespace(files=[record], locate_file=lambda item: binary)
            package = SimpleNamespace(bundled_runtime_path=lambda: binary)
            metadata = SimpleNamespace(st_mode=0o100555, st_uid=0, st_size=len(payload))
            with patch.dict(sys.modules, {"deepseek_harness_runtime": package}), \
                 patch.object(entry.importlib.metadata, "version", return_value=entry.VERSION), \
                 patch.object(entry.importlib.metadata, "distribution", return_value=distribution), \
                 patch.object(entry.Path, "lstat", return_value=metadata):
                admission = {**self.admission(), "runtimeSha256": digest.hex()}
                self.assertEqual(entry.admitted_binary(admission), binary)
                binary.write_bytes(b"SYNTHETIC_TAMPERED")
                with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
                    entry.admitted_binary(admission)

    def test_runtime_user_writable_metadata_refused_before_payload_read(self):
        package = SimpleNamespace(bundled_runtime_path=lambda: "/synthetic/not-read")
        metadata = SimpleNamespace(st_mode=0o100777, st_uid=10001, st_size=1)
        with patch.dict(sys.modules, {"deepseek_harness_runtime": package}), \
             patch.object(entry.importlib.metadata, "version", return_value=entry.VERSION), \
             patch.object(entry.Path, "lstat", return_value=metadata):
            with self.assertRaisesRegex(ValueError, "UNPROTECTED"):
                entry.admitted_binary(self.admission())


if __name__ == "__main__": unittest.main()
