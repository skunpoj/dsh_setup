import importlib.util
import sys
from pathlib import Path
import sys
from unittest import mock
import unittest
from unittest import mock

MODULE = Path(__file__).parents[1] / "container" / "dsh-unattended.py"
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location("unattended_launcher", MODULE)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherCase(unittest.TestCase):
    def test_task_id_is_path_safe(self):
        self.assertEqual(launcher.safe_task("task_01"), "task_01")
        with self.assertRaises(ValueError):
            launcher.safe_task("../escape")

    def test_control_options_are_not_forwarded_to_client(self):
        original_argv = sys.argv
        original_guard = launcher.running_guard
        original_run = launcher.run_client
        captured = {}
        class Guard:
            def __enter__(self): return 1234
            def __exit__(self, *_): return False
        try:
            sys.argv = ["dsh-unattended", "sdk", "--cwd", "/workspace/project", "--", "hello"]
            launcher.running_guard = lambda *_: Guard()
            launcher.run_client = lambda command, env, cwd: captured.update(command=command, cwd=cwd) or 0
            with mock.patch.object(launcher.Path, "mkdir"):
                self.assertEqual(launcher.main(), 0)
            self.assertEqual(captured["command"], ["/usr/local/bin/dsh-sdk-task", "hello"])
            self.assertEqual(captured["cwd"], str(Path("/workspace/project").resolve()))
        finally:
            sys.argv = original_argv
            launcher.running_guard = original_guard
            launcher.run_client = original_run

    def test_claude_uses_guard_and_disables_nonessential_traffic(self):
        env=launcher.build_environment({"KEEP":"yes"},"claude","http://127.0.0.1:1234")
        self.assertEqual(env["ANTHROPIC_BASE_URL"],"http://127.0.0.1:1234")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"],"1")
        self.assertEqual(env["DSH_GUARDED_MODEL_BASE_URL"],"http://127.0.0.1:1234/v1")
        self.assertEqual(env["KEEP"],"yes")

    def test_kilo_exposes_only_guard_url(self):
        env=launcher.build_environment({},"kilo","http://127.0.0.1:2345")
        self.assertEqual(env["DSH_GUARDED_MODEL_BASE_URL"],"http://127.0.0.1:2345/v1")
        self.assertNotIn("ANTHROPIC_BASE_URL",env)

    @mock.patch.object(launcher.subprocess, "Popen")
    def test_child_is_started_in_its_own_posix_session(self, popen):
        child = popen.return_value
        child.wait.return_value = 0
        child.poll.return_value = 0
        self.assertEqual(launcher.run_client(["client", "arg"], {"A":"B"}), 0)
        self.assertEqual(popen.call_args.args[0], ["client", "arg"])
        self.assertEqual(popen.call_args.kwargs["cwd"], "/workspace")
        self.assertEqual(popen.call_args.kwargs["start_new_session"], launcher.os.name != "nt")


if __name__ == "__main__": unittest.main()
