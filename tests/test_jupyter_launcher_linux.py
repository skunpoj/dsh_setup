import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

spec=importlib.util.spec_from_file_location('launcher',Path(__file__).resolve().parents[1]/'scripts/jupyter_launcher.py')
module=importlib.util.module_from_spec(spec)
if os.name != 'nt':spec.loader.exec_module(module)

@unittest.skipIf(os.name == 'nt', 'Linux process and flock tests are qualified in the runtime fixture')
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.lock=patch.object(module,'LOCK',str(Path(self.temp.name)/'lock'));self.lock.start();self.addCleanup(self.lock.stop)
        self.state=patch.object(module,'STATE',str(Path(self.temp.name)/'state'));self.state.start();self.addCleanup(self.state.stop)

    def test_existing_listener_never_spawns_or_stops(self):
        with patch.object(module,'listening',return_value=True),patch.object(module.subprocess,'Popen') as spawn:
            self.assertEqual(module.ensure(),{'state':'listening','reused':True});spawn.assert_not_called()

    def test_symbolic_link_lock_is_rejected_without_touching_target(self):
        target=Path(self.temp.name)/'target';target.write_text('preserved');Path(module.LOCK).symlink_to(target)
        with self.assertRaises(OSError):module.ensure()
        self.assertEqual(target.read_text(),'preserved')

    def test_publicly_readable_lock_is_rejected(self):
        Path(module.LOCK).write_text('');os.chmod(module.LOCK,0o644)
        with self.assertRaises(ValueError):module.ensure()

    def test_fifo_state_does_not_block(self):
        os.mkfifo(module.STATE,0o600)
        with self.assertRaises(ValueError):module.read_state()

    def test_hardlinked_lock_is_rejected(self):
        a=Path(self.temp.name)/'target';a.write_text('preserved');os.chmod(a,0o600);os.link(a,module.LOCK)
        with self.assertRaises(ValueError):module.ensure()

    def test_stale_pid_does_not_reuse_an_unrelated_process(self):
        fd=module.protected_open(module.STATE,os.O_CREAT|os.O_WRONLY);os.write(fd,json.dumps({'pid':os.getpid(),'stamp':'old'}).encode());os.close(fd)
        self.assertIsNone(module.read_state())

    def test_active_starting_process_is_reused_without_a_new_spawn(self):
        with patch.object(module,'read_state',return_value={'pid':123,'stamp':'valid'}),patch.object(module,'listening',side_effect=[False,True]),patch.object(module.subprocess,'Popen') as spawn:
            self.assertEqual(module.ensure(),{'state':'listening','reused':True});spawn.assert_not_called()

    def test_fixed_launcher_never_reads_user_arguments_as_commands(self):
        self.assertEqual(module.ARGV,['/opt/dsh/jupyter/bin/python','/usr/local/bin/jupyter','lab'])
        self.assertNotIn('shell=True',Path(module.__file__).read_text())
        self.assertNotIn('os.kill',Path(module.__file__).read_text())

if __name__=='__main__':unittest.main()
