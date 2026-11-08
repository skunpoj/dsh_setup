import importlib.util
import os
import sys
from pathlib import Path
import sys
from unittest import mock
import unittest
import tempfile
from unittest import mock

MODULE = Path(__file__).parents[1] / "container" / "dsh-unattended.py"
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location("unattended_launcher", MODULE)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherCase(unittest.TestCase):
    def test_external_guard_fence_survives_reopen_without_any_upstream_start(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ledger.jsonl'
            ledger=launcher.AdmissionLedger(path,'task-test',1,task_correlation_id='a'*32)
            self.assertTrue(ledger.fence('b'*32))
            self.assertFalse(ledger.fence('c'*32))
            reopened=launcher.AdmissionLedger(path,'task-test',1,task_correlation_id='a'*32)
            result=reopened.reserve('/v1/chat/completions',b'{"model":"synthetic","messages":[]}')
            self.assertEqual(result[:2],(False,'task-fenced'))
            self.assertNotIn('upstream-start-reserved',path.read_text())

    def test_external_guard_identity_is_actual_loopback_read_without_model_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=launcher.AdmissionLedger(Path(folder)/'ledger.jsonl','task-test',1,
                                            task_correlation_id='a'*32)
            with launcher.running_guard(launcher.APPROVED_UPSTREAM,Path(folder)/'missing-token',ledger) as port:
                self.assertEqual(launcher.verify_external_guard(port,'task-test','a'*32,1),
                                 f'http://127.0.0.1:{port}')
                with self.assertRaisesRegex(ValueError,'BINDING_MISMATCH'):
                    launcher.verify_external_guard(port,'foreign','a'*32,1)
            rows = ledger.path.read_text(encoding='utf-8').splitlines()
            self.assertTrue(any('"event": "task-fenced"' in row for row in rows))
            self.assertFalse(any('"event": "upstream-start-reserved"' in row
                                 for row in rows))

    def test_external_mode_does_not_create_ledger_or_read_provider_credential(self):
        args=['dsh-unattended','claude','--task-id','task-test','--max-model-starts','1',
              '--external-guard-port','4001','--cwd','/workspace/demo','--','-p','synthetic']
        with mock.patch.object(sys,'argv',args), \
                mock.patch.dict(os.environ,{'DSH_CORRELATION_ID':'a'*32},clear=True), \
                mock.patch.object(launcher,'verify_external_guard',return_value='http://127.0.0.1:4001') as verify, \
                mock.patch.object(launcher,'AdmissionLedger') as ledger, \
                mock.patch.object(launcher,'running_guard') as guard, \
                mock.patch.object(launcher,'run_client',return_value=0) as run:
            self.assertEqual(launcher.main(),0)
            verify.assert_called_once_with(4001,'task-test','a'*32,1)
            ledger.assert_not_called();guard.assert_not_called()
            self.assertEqual(run.call_args.args[1]['ANTHROPIC_BASE_URL'],'http://127.0.0.1:4001')

    def test_group_cleanup_runs_even_after_main_child_exits(self):
        child=mock.Mock(pid=2345)
        child.wait.return_value=0;child.poll.return_value=0
        with mock.patch.object(launcher.subprocess,'Popen',return_value=child), \
                mock.patch.object(launcher.os,'name','posix'), \
                mock.patch.object(launcher,'stop_client_group') as stop:
            self.assertEqual(launcher.run_client(['synthetic'],{}),0)
        stop.assert_called_once_with(2345)

    @mock.patch.object(launcher.signal, 'SIGKILL', 9, create=True)
    def test_group_cleanup_requires_observed_absence(self):
        with mock.patch.object(launcher.os,'killpg',side_effect=[None,ProcessLookupError()],create=True) as kill:
            launcher.stop_client_group(2345)
        self.assertEqual(kill.call_args_list[-1].args,(2345,0))

    @mock.patch.object(launcher.signal, 'SIGKILL', 9, create=True)
    def test_group_cleanup_raises_when_group_survives_both_signals(self):
        with mock.patch.object(launcher.os,'killpg',return_value=None,create=True) as kill:
            with self.assertRaisesRegex(RuntimeError,'STOP_UNVERIFIED'):
                launcher.stop_client_group(2345,timeout=0)
        self.assertEqual(kill.call_count,2)

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
            os.environ["DSH_CORRELATION_ID"] = "a" * 32
            launcher.running_guard = lambda *_: Guard()
            launcher.run_client = lambda command, env, cwd: captured.update(command=command, cwd=cwd) or 0
            with mock.patch.object(launcher.Path, "mkdir"):
                self.assertEqual(launcher.main(), 0)
            self.assertEqual(captured["command"], ["/usr/local/bin/dsh-sdk-task", "hello"])
            self.assertEqual(captured["cwd"], str(Path("/workspace/project").resolve()))
        finally:
            os.environ.pop("DSH_CORRELATION_ID", None)
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
