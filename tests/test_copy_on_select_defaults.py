"""Platform defaults that stop select-to-copy: Claude Code copyOnSelect=false seeded only when absent; ttyd HTML guarded against execCommand('copy')."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ENV = Path(__file__).resolve().parents[1]


def load_seed():
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed_claude_defaults", ENV / "scripts" / "seed_claude_defaults.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class SeedClaudeDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.file = Path(self.temp.name) / ".claude.json"
        self.seed = load_seed().seed

    def test_creates_the_file_with_the_default_when_missing(self):
        self.assertEqual(self.seed(self.file), "seeded: copyOnSelect")
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), {"copyOnSelect": False})

    def test_adds_the_key_to_an_existing_file_without_touching_other_keys(self):
        self.file.write_text(json.dumps({"hasCompletedOnboarding": True, "theme": "dark"}), encoding="utf-8")
        self.assertEqual(self.seed(self.file), "seeded: copyOnSelect")
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), {"hasCompletedOnboarding": True, "theme": "dark", "copyOnSelect": False})

    def test_a_choice_the_user_made_always_wins_and_the_file_is_not_rewritten(self):
        self.file.write_text(json.dumps({"copyOnSelect": True}), encoding="utf-8")
        before = self.file.stat().st_mtime_ns
        self.assertEqual(self.seed(self.file), "unchanged")
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), {"copyOnSelect": True})
        self.assertEqual(self.file.stat().st_mtime_ns, before)

    def test_unreadable_or_foreign_content_is_left_alone_and_never_raises(self):
        for text in ("{not json", "[1, 2]", ""):
            self.file.write_text(text, encoding="utf-8")
            self.assertTrue(self.seed(self.file).startswith("skipped"))
            self.assertEqual(self.file.read_text(encoding="utf-8"), text)
        self.assertTrue(self.seed(Path(self.temp.name) / "no-such-dir" / ".claude.json").startswith("skipped"))

    def test_start_script_runs_it_after_the_state_link_and_never_fails_start_up(self):
        text = (ENV / "container" / "start-dsh.sh").read_text(encoding="utf-8")
        self.assertIn("seed_claude_defaults.py", text)
        self.assertRegex(text, r"seed_claude_defaults\.py[^\n]*\|\| true")
        self.assertLess(text.index('ln -s /state/claude "$HOME/.claude"'), text.index("seed_claude_defaults.py"))
        self.assertIn("seed_claude_defaults.py", (ENV / "Dockerfile").read_text(encoding="utf-8") + (ENV / "container" / "start-dsh.sh").read_text(encoding="utf-8"))


class TtydCopyGuardTests(unittest.TestCase):
    def test_node_unit_tests_pass(self):
        done = subprocess.run(["node", str(ENV / "tests" / "test_ttyd_copy_guard.cjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
