"""The protected entry script: thin, fail-closed, writes nothing. Real exits are tested through scripts/native_qualification_compose."""
import importlib.util
from pathlib import Path
import unittest

from scripts import official_sdk_bootstrap as bootstrap

ROOT = Path(__file__).parents[1]
ENTRY = ROOT / "container" / "dsh-native-qualification-broker.py"
spec = importlib.util.spec_from_file_location("native_qualification_entry", ENTRY)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


class EntryScriptTests(unittest.TestCase):
    def test_this_host_is_refused_without_reading_anything(self):
        # Not Linux-root here (or not root in CI): the shell must refuse before touching files or the API.
        self.assertEqual(entry.main(), entry.compose.EXIT_REFUSED)

    def test_the_provider_runtime_is_now_loadable_and_exposes_install(self):
        self.assertTrue(callable(entry.load_providers().install))

    def test_the_admission_path_is_the_one_configure_demands(self):
        self.assertEqual(entry.ADMISSION, "/etc/dsh-native-admission/official-sdk-server.json")
        source = (ROOT / "scripts" / "official_sdk_bootstrap.py").read_text(encoding="utf-8")
        self.assertIn('"/etc/dsh-native-admission/official-sdk-server.json"', source)

    def test_the_entry_script_never_writes_a_file(self):
        text = ENTRY.read_text(encoding="utf-8")
        for forbidden in ("write_text", "write_bytes", ".write(", "open(", "os.rename", "os.replace", "shutil", "subprocess"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_entry_and_composition_library_are_hash_bound_protected_sources(self):
        self.assertEqual(bootstrap.SOURCES["qualificationEntry"], "/opt/dsh/container/dsh-native-qualification-broker.py")
        self.assertEqual(bootstrap.SOURCES["nativeComposition"], "/opt/dsh/scripts/native_qualification_compose.py")
        self.assertEqual(bootstrap.SOURCES["modelGuardSidecar"], "/opt/dsh/container/dsh-task-guard-sidecar.py")
        # The entry executes the broker module (Registry, Handler): it must be hash-bound like everything it runs.
        self.assertEqual(bootstrap.SOURCES["taskBroker"], "/opt/dsh/container/dsh-task-broker.py")
        for role in ("qualificationEntry", "nativeComposition", "modelGuardSidecar", "taskBroker", "nativeInputs", "nativeProviders"):
            self.assertTrue((ROOT / bootstrap.SOURCES[role].replace("/opt/dsh/", "")).is_file(), role)
        self.assertEqual(bootstrap.SOURCES["nativeInputs"], "/opt/dsh/scripts/native_qualification_inputs.py")
        self.assertEqual(len(bootstrap.SOURCES), 50)


if __name__ == "__main__":
    unittest.main()
