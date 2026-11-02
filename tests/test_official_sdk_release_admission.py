import csv
import hashlib
import io
import json
import stat
import unittest
import zipfile

from scripts.official_sdk_release_admission import (
    RUNTIME_NAME, SDK_NAME, SOURCE, VERSION, verify_release_pair)


def wheel(distribution, payloads, requirements=(), tag="py3-none-any", duplicate_record=False):
    prefix = distribution.replace("-", "_") + f"-{VERSION}.dist-info/"
    metadata = [f"Name: {distribution}", f"Version: {VERSION}"]
    metadata += [f"Requires-Dist: {item}" for item in requirements]
    files = dict(payloads)
    files[prefix + "METADATA"] = ("\n".join(metadata) + "\n").encode()
    files[prefix + "WHEEL"] = f"Wheel-Version: 1.0\nTag: {tag}\n".encode()
    rows = []
    for name, raw in files.items():
        digest = hashlib.sha256(raw).digest()
        rows.append([name, "sha256=" + __import__("base64").urlsafe_b64encode(digest).rstrip(b"=").decode(), str(len(raw))])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
        record = io.StringIO(); writer = csv.writer(record)
        writer.writerows(rows + [[prefix + "RECORD", "", ""]])
        if duplicate_record: writer.writerow(rows[0])
        archive.writestr(prefix + "RECORD", record.getvalue())
    return output.getvalue()


class ReleaseAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.sdk = wheel("deepseek-harness-sdk", {"deepseek_harness/__init__.py": b"pass\n"},
                         [f"deepseek-harness-runtime-bin=={VERSION}"])
        elf = bytearray(64); elf[:7] = b"\x7fELF\x02\x01\x01"; elf[18:20] = (62).to_bytes(2, "little")
        self.runtime = wheel("deepseek-harness-runtime-bin", {
            "deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64": bytes(elf)
        }, tag="py3-none-manylinux_2_28_x86_64")
        self.receipt = {
            "kind": "DSH_OFFICIAL_SDK_RELEASE_V1", "sourceCommit": SOURCE,
            "version": VERSION, "platform": "manylinux_2_28_x86_64",
            "builderImage": "registry.example/builder@sha256:" + "1" * 64,
            "applicationImage": "registry.example/dsh@sha256:" + "2" * 64,
            "sdkWheel": SDK_NAME, "runtimeWheel": RUNTIME_NAME,
            "sdkWheelSha256": hashlib.sha256(self.sdk).hexdigest(),
            "runtimeWheelSha256": hashlib.sha256(self.runtime).hexdigest(),
            "sdkWheelSize": len(self.sdk), "runtimeWheelSize": len(self.runtime),
        }

    def verify(self, **changes):
        receipt = dict(self.receipt); receipt.update(changes)
        raw = json.dumps(receipt).encode()
        return verify_release_pair(receipt_raw=raw, trusted_receipt_sha256=hashlib.sha256(raw).hexdigest(),
                                   sdk_raw=self.sdk, runtime_raw=self.runtime)

    def test_matched_pair_binds_source_wheels_images_and_runtime(self):
        result = self.verify()
        self.assertEqual(result["sourceCommit"], SOURCE)
        self.assertEqual(result["sdkVersion"], VERSION)
        self.assertEqual(result["runtimeVersion"], VERSION)
        self.assertNotEqual(result["runtimeSha256"], "0" * 64)

    def test_source_version_platform_and_mutable_images_fail_closed(self):
        for change in ({"sourceCommit": "0" * 40}, {"version": "0.2.1rc2"},
                       {"platform": "win_amd64"}, {"builderImage": "latest"},
                       {"applicationImage": "registry.example/dsh:latest"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(**change)

    def test_repacked_or_mismatched_wheel_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "SDK_RELEASE_HASH"):
            verify_release_pair(receipt_raw=json.dumps(self.receipt).encode(),
                                trusted_receipt_sha256=hashlib.sha256(json.dumps(self.receipt).encode()).hexdigest(),
                                sdk_raw=self.sdk[:-1] + bytes([self.sdk[-1] ^ 1]), runtime_raw=self.runtime)

    def test_sdk_must_require_exact_runtime_pair(self):
        self.sdk = wheel("deepseek-harness-sdk", {"deepseek_harness/__init__.py": b"pass\n"},
                         ["deepseek-harness-runtime-bin>=0.2"])
        self.receipt["sdkWheelSha256"] = hashlib.sha256(self.sdk).hexdigest()
        self.receipt["sdkWheelSize"] = len(self.sdk)
        with self.assertRaisesRegex(ValueError, "DEPENDENCY_MISMATCH"):
            self.verify()

    def test_receipt_requires_independent_trusted_hash(self):
        with self.assertRaisesRegex(ValueError, "UNTRUSTED"):
            verify_release_pair(receipt_raw=json.dumps(self.receipt).encode(),
                                trusted_receipt_sha256="f" * 64,
                                sdk_raw=self.sdk, runtime_raw=self.runtime)

    def test_wheel_tag_record_and_runtime_identity_are_exact(self):
        self.sdk = wheel("deepseek-harness-sdk", {"deepseek_harness/__init__.py": b"pass\n"},
                         [f"deepseek-harness-runtime-bin=={VERSION}"], tag="py2.py3-none-any")
        self.receipt["sdkWheelSha256"] = hashlib.sha256(self.sdk).hexdigest()
        self.receipt["sdkWheelSize"] = len(self.sdk)
        with self.assertRaisesRegex(ValueError, "TAG_MISMATCH"): self.verify()
        self.setUp()
        self.runtime = wheel("deepseek-harness-runtime-bin", {
            "deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64": b"not an elf"
        }, tag="py3-none-manylinux_2_28_x86_64")
        self.receipt["runtimeWheelSha256"] = hashlib.sha256(self.runtime).hexdigest()
        self.receipt["runtimeWheelSize"] = len(self.runtime)
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"): self.verify()

    def test_duplicate_or_incomplete_record_is_refused(self):
        self.sdk = wheel("deepseek-harness-sdk", {"deepseek_harness/__init__.py": b"pass\n"},
                         [f"deepseek-harness-runtime-bin=={VERSION}"], duplicate_record=True)
        self.receipt["sdkWheelSha256"] = hashlib.sha256(self.sdk).hexdigest()
        self.receipt["sdkWheelSize"] = len(self.sdk)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_RELEASE_WHEEL_RECORD"): self.verify()

    def test_receipt_binds_exact_artifact_sizes_and_sdk_package_entry(self):
        with self.assertRaisesRegex(ValueError, "INVALID_RELEASE_RECEIPT"):
            self.verify(sdkWheelSize=len(self.sdk) + 1)
        self.sdk = wheel("deepseek-harness-sdk", {"other/__init__.py": b"pass\n"},
                         [f"deepseek-harness-runtime-bin=={VERSION}"])
        self.receipt["sdkWheelSha256"] = hashlib.sha256(self.sdk).hexdigest()
        self.receipt["sdkWheelSize"] = len(self.sdk)
        with self.assertRaisesRegex(ValueError, "SDK_PACKAGE_ENTRY_REQUIRED"): self.verify()

    def update_sdk(self, raw):
        self.sdk = raw
        self.receipt["sdkWheelSha256"] = hashlib.sha256(raw).hexdigest()
        self.receipt["sdkWheelSize"] = len(raw)

    def test_full_record_integrity_not_only_trusted_archive_hash(self):
        source = zipfile.ZipFile(io.BytesIO(self.sdk)); output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for entry in source.infolist():
                data = source.read(entry)
                if entry.filename == "deepseek_harness/__init__.py": data = b"changed after record\n"
                target.writestr(entry, data)
        self.update_sdk(output.getvalue())
        with self.assertRaisesRegex(ValueError, "RECORD_MISMATCH"): self.verify()

    def test_record_missing_payload_coverage_refused(self):
        source = zipfile.ZipFile(io.BytesIO(self.sdk)); output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for entry in source.infolist():
                data = source.read(entry)
                if entry.filename.endswith("/RECORD"):
                    rows = list(csv.reader(io.StringIO(data.decode())))
                    rows = [row for row in rows if row[0] != "deepseek_harness/__init__.py"]
                    changed = io.StringIO(); csv.writer(changed).writerows(rows); data = changed.getvalue().encode()
                target.writestr(entry, data)
        self.update_sdk(output.getvalue())
        with self.assertRaisesRegex(ValueError, "COVERAGE_MISMATCH"): self.verify()

    def test_symlink_sdk_payload_refused(self):
        source = zipfile.ZipFile(io.BytesIO(self.sdk)); output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for entry in source.infolist():
                data = source.read(entry)
                if entry.filename == "deepseek_harness/__init__.py":
                    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                target.writestr(entry, data)
        self.update_sdk(output.getvalue())
        with self.assertRaisesRegex(ValueError, "WHEEL_PATH"): self.verify()

    def test_runtime_substring_path_is_not_exact_runtime(self):
        source = zipfile.ZipFile(io.BytesIO(self.runtime))
        binary = source.read("deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64")
        self.runtime = wheel("deepseek-harness-runtime-bin", {
            "other/deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64": binary},
            tag="py3-none-manylinux_2_28_x86_64")
        self.receipt.update(runtimeWheelSha256=hashlib.sha256(self.runtime).hexdigest(), runtimeWheelSize=len(self.runtime))
        with self.assertRaisesRegex(ValueError, "EXECUTABLE_REQUIRED"): self.verify()

    def test_other_elf_architecture_refused(self):
        binary = bytearray(64); binary[:7] = b"\x7fELF\x02\x01\x01"; binary[18:20] = (183).to_bytes(2, "little")
        self.runtime = wheel("deepseek-harness-runtime-bin", {
            "deepseek_harness_runtime/runtime/deepseek-harness-sdk-runtime-linux-x64": bytes(binary)},
            tag="py3-none-manylinux_2_28_x86_64")
        self.receipt.update(runtimeWheelSha256=hashlib.sha256(self.runtime).hexdigest(), runtimeWheelSize=len(self.runtime))
        with self.assertRaisesRegex(ValueError, "IDENTITY_MISMATCH"): self.verify()


if __name__ == "__main__":
    unittest.main()
