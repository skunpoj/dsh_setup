import io
import json
import stat
import unittest
import zipfile

from scripts.official_sdk_release_admission import (
    RUNTIME_EXE,
    RUNTIME_ROOT,
    _runtime_payload,
)


def elf64_x86_64():
    raw = bytearray(64)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    raw[18:20] = (62).to_bytes(2, "little")
    return bytes(raw)


def runtime_archive(*, missing=None, target="linux-x64", executable=True,
                    extra=None):
    payloads = {
        RUNTIME_ROOT + RUNTIME_EXE: elf64_x86_64(),
        RUNTIME_ROOT + RUNTIME_EXE + "-rg": elf64_x86_64(),
        RUNTIME_ROOT + "linux-x64/downloads.json": json.dumps({
            "target": target,
            "identity": "a" * 64,
            "office": ["retained"],
            "pnpm": {},
        }).encode(),
    }
    for kind in ("docx", "pptx", "xlsx"):
        payloads[RUNTIME_ROOT + f"linux-x64/office-skills/office-{kind}/SKILL.md"] = b"retained\n"
    if missing:
        payloads.pop(missing)
    if extra:
        payloads[extra] = b"unexpected"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in payloads.items():
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            mode = 0o755 if executable and name in (
                RUNTIME_ROOT + RUNTIME_EXE,
                RUNTIME_ROOT + RUNTIME_EXE + "-rg",
            ) else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(entry, raw)
    return zipfile.ZipFile(io.BytesIO(output.getvalue()))


class RuntimePayloadTests(unittest.TestCase):
    def test_complete_payload_is_bound(self):
        binaries, identity = _runtime_payload(runtime_archive())
        self.assertEqual(set(binaries), {RUNTIME_EXE, RUNTIME_EXE + "-rg"})
        self.assertEqual(identity, "a" * 64)

    def test_companion_binary_is_required(self):
        with self.assertRaisesRegex(ValueError, "PAYLOAD_CLOSURE_REQUIRED"):
            _runtime_payload(runtime_archive(missing=RUNTIME_ROOT + RUNTIME_EXE + "-rg"))

    def test_resource_manifest_is_required(self):
        with self.assertRaisesRegex(ValueError, "DOWNLOAD_MANIFEST_REQUIRED"):
            _runtime_payload(runtime_archive(missing=RUNTIME_ROOT + "linux-x64/downloads.json"))

    def test_all_office_skill_entries_are_required(self):
        with self.assertRaisesRegex(ValueError, "OFFICE_SKILL_REQUIRED"):
            _runtime_payload(runtime_archive(
                missing=RUNTIME_ROOT + "linux-x64/office-skills/office-pptx/SKILL.md"))

    def test_target_and_execute_mode_are_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "DOWNLOAD_MANIFEST_MISMATCH"):
            _runtime_payload(runtime_archive(target="linux-arm64"))
        with self.assertRaisesRegex(ValueError, "EXECUTABLE_MODE_REQUIRED"):
            _runtime_payload(runtime_archive(executable=False))

    def test_foreign_top_level_payload_is_refused(self):
        with self.assertRaisesRegex(ValueError, "PAYLOAD_CLOSURE_REQUIRED"):
            _runtime_payload(runtime_archive(extra=RUNTIME_ROOT + "foreign-engine"))


if __name__ == "__main__":
    unittest.main()
