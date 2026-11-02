import contextlib
import io
import json
import stat
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
from scripts import openshell_worker_entry as worker
from scripts.agent_runtime_commands import command_for


class WorkerEntryTests(unittest.TestCase):
    def test_stdin_envelope_uses_protected_assignment_and_guarded_commands(self):
        envelope={'prompt':'synthetic'};assigned={'bindingId':'a'*32}
        runner=Mock(return_value={'exitCode':0})
        with patch.object(worker,'read_assignment',return_value=assigned):
            self.assertEqual(worker.main(io.BytesIO(json.dumps(envelope).encode()),runner=runner),0)
        self.assertEqual(runner.call_args.args[:2],(envelope,assigned))
        self.assertIs(runner.call_args.args[3],command_for)

    def test_invalid_or_oversize_input_cannot_launch_or_echo_content(self):
        runner=Mock();err=io.StringIO()
        with contextlib.redirect_stderr(err),patch.object(worker,'read_assignment') as assignment:
            self.assertEqual(worker.main(io.BytesIO(b'PRIVATE_MARKER'),runner=runner),70)
            self.assertEqual(worker.main(io.BytesIO(b'x'*(worker.MAX_INPUT+1)),runner=runner),70)
        runner.assert_not_called();assignment.assert_not_called()
        self.assertNotIn('PRIVATE_MARKER',err.getvalue())

    def test_user_writable_assignment_is_refused(self):
        with patch.object(worker.os,'open',return_value=9),patch.object(worker.os,'close') as close,\
             patch.object(worker.os,'fstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o666,st_uid=0)):
            with self.assertRaisesRegex(ValueError,'UNPROTECTED_WORKER_ASSIGNMENT'):worker.read_assignment()
        close.assert_called_once_with(9)

    def test_unknown_runtime_never_becomes_claude_fallback(self):
        with self.assertRaisesRegex(ValueError,'INVALID_RUNTIME'):command_for('unknown','x',False,'.','a'*32)
        for runtime in ('sdk','claude','deepagents','kilo'):
            command=command_for(runtime,'x',False,'.','a'*32)
            self.assertEqual(command[:2],['/usr/local/bin/dsh-unattended',runtime])
            self.assertEqual(command[command.index('--max-model-starts')+1],'1')


if __name__=='__main__':unittest.main()
