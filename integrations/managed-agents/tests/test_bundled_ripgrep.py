import base64
import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/install_bundled_ripgrep.py"
spec = importlib.util.spec_from_file_location("bundled_rg", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RecordIntegrityTests(unittest.TestCase):
    def test_record_integrity_and_tampering(self):
        original = b"synthetic-wheel-file"
        record = SimpleNamespace(size=len(original), hash=SimpleNamespace(
            mode="sha256", value=base64.urlsafe_b64encode(
                hashlib.sha256(original).digest()).rstrip(b"=").decode()))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rg"
            source.write_bytes(original)
            self.assertEqual(module.verify_record_file(source, record),
                             hashlib.sha256(original).hexdigest())
            source.write_bytes(b"tampered-wheel-file")
            with self.assertRaisesRegex(ValueError, "differs"):
                module.verify_record_file(source, record)

    def test_missing_hash_or_incorrect_size_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rg"
            source.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "RECORD"):
                module.verify_record_file(source, SimpleNamespace(hash=None))
            record = SimpleNamespace(size=2, hash=SimpleNamespace(mode="sha256",
                value=base64.urlsafe_b64encode(hashlib.sha256(b"x").digest()).rstrip(b"=").decode()))
            with self.assertRaisesRegex(ValueError, "size"):
                module.verify_record_file(source, record)


if __name__ == "__main__":
    unittest.main()
