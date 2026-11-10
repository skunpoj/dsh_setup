"""The package admission generator, checked with the REAL verifier and the real sealed SDK wheel (skipped when the wheel is not on this machine)."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts import make_official_sdk_package_admission as generator
from scripts import official_sdk_package_admission as package

WHEEL_SHA = "953e57ccc77eea412c709373c99f26e647986c1dced4ca707a6d8c440b975492"
WHEEL_CANDIDATES = [
    Path(r"/home/developer\outputs\w10-push-ready\wheels\deepseek_harness_sdk-0.2.2a2-py3-none-any.whl"),
    Path(__file__).resolve().parents[3].parent / "import" / "openshell-sdk-wheel-w10" / "deepseek_harness_sdk-0.2.2a2-py3-none-any.whl",
]


def find_wheel():
    for path in WHEEL_CANDIDATES:
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == WHEEL_SHA:
            return path
    return None


@unittest.skipUnless(find_wheel() is not None, "the sealed SDK wheel is not on this machine")
class PackageAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.wheel = self.root / "deepseek_harness_sdk-0.2.2a2-py3-none-any.whl"
        shutil.copy(find_wheel(), self.wheel)
        self.installed = self.root / "site-packages"
        done = subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--no-warn-script-location",
                               "--target", str(self.installed), str(self.wheel)], capture_output=True, text=True)
        if done.returncode != 0:
            self.skipTest("pip could not install the wheel offline: " + done.stderr[-200:])

    def tearDown(self):
        self.tmp.cleanup()

    def generate(self, **override):
        values = dict(wheel=self.wheel, installed=self.installed, trusted_sdk_wheel_sha256=WHEEL_SHA, out=self.root / "official-sdk-package.json")
        values.update(override)
        return generator.generate(**values)

    def test_descriptor_has_the_exact_fields_and_the_real_verifier_accepts_it(self):
        descriptor = self.generate()
        self.assertEqual(set(descriptor), {"kind", "sourceCommit", "sdkVersion", "runtimeVersion", "sdkWheelSha256", "installedRecordSha256"})
        self.assertEqual(descriptor["sdkWheelSha256"], WHEEL_SHA)
        record = self.installed / "deepseek_harness_sdk-0.2.2a2.dist-info" / "RECORD"
        self.assertEqual(descriptor["installedRecordSha256"], hashlib.sha256(record.read_bytes()).hexdigest())
        verified = package.verify_sdk_admission(admission_path=self.root / "official-sdk-package.json", installed=self.installed,
                                                wheel=self.wheel, reader=generator.plain_reader)
        self.assertEqual(verified["admissionSha256"], hashlib.sha256((self.root / "official-sdk-package.json").read_bytes()).hexdigest())

    def test_the_output_is_exclusive_and_read_only(self):
        self.generate()
        with self.assertRaisesRegex(generator.PackageAdmissionRefused, "OUTPUT_MUST_BE_NEW"):
            self.generate()
        self.assertFalse((self.root / "official-sdk-package.json.check").exists())

    def test_a_wheel_that_is_not_the_admitted_one_is_refused_and_nothing_is_written(self):
        with self.assertRaisesRegex(generator.PackageAdmissionRefused, "SDK_WHEEL_NOT_THE_ADMITTED_ONE"):
            self.generate(trusted_sdk_wheel_sha256="1" * 64)
        with self.assertRaisesRegex(generator.PackageAdmissionRefused, "UNBOUND_TRUSTED_SDK_WHEEL_SHA256"):
            self.generate(trusted_sdk_wheel_sha256="0" * 64)
        self.assertFalse((self.root / "official-sdk-package.json").exists())

    def test_an_installed_file_that_differs_from_the_wheel_is_refused_by_the_round_trip(self):
        record = (self.installed / "deepseek_harness_sdk-0.2.2a2.dist-info" / "RECORD").read_text(encoding="utf-8").splitlines()
        names = [line.split(",")[0] for line in record if ".dist-info/" not in line.split(",")[0] and not line.split(",")[0].endswith(".pyc")]
        target = self.installed / names[0]
        target.write_bytes(target.read_bytes() + b"\n# tampered\n")
        with self.assertRaises(generator.PackageAdmissionRefused):
            self.generate()
        self.assertFalse((self.root / "official-sdk-package.json").exists())

    def test_a_missing_installed_record_is_refused(self):
        (self.installed / "deepseek_harness_sdk-0.2.2a2.dist-info" / "RECORD").unlink()
        with self.assertRaises(generator.PackageAdmissionRefused):
            self.generate()

    def test_cli_exit_codes(self):
        out = self.root / "cli.json"
        argv = ["--wheel", str(self.wheel), "--installed", str(self.installed), "--trusted-sdk-wheel-sha256", WHEEL_SHA, "--out", str(out)]
        self.assertEqual(generator.main(argv), 0)
        self.assertEqual(json.loads(out.read_text())["kind"], "DSH_OFFICIAL_SDK_PACKAGE_V1")
        self.assertEqual(generator.main(argv), 2)


if __name__ == "__main__":
    unittest.main()
