"""Linux-only local process fixture; no agents, model, network or cluster API."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "linux", "requires real Linux process groups")
class LinuxCLIQualification(unittest.TestCase):
    def test_exited_leader_does_not_hide_a_surviving_descendant(self):
        # A separate fixture supervisor adopts/reaps the synthetic descendant.
        # This avoids changing the qualification runner's process policy.
        launcher = Path(__file__).parents[1] / "container/dsh-unattended.py"
        fixture = r'''
import ctypes,importlib.util,os,signal,subprocess,sys,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parents[1]/'scripts'))
import dsh_correlation,unattended_model_guard
spec=importlib.util.spec_from_file_location('qualified_launcher',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
with tempfile.TemporaryDirectory() as directory:
    # The launcher (run as root in the image build) now runs the client as the fixed agent uid 10001 (banking_process_identity.agent_kwargs), so the synthetic client
    # and its descendant cannot write into this root-created 0700 directory. The qualification is about process-group/descendant tracking, not identity: let ANY uid
    # create the marker here and keep the real uid drop in place. The fixture (root) still reads the marker and the launcher's stop_client_group still has to kill
    # the descendant, which is exactly what is asserted below.
    os.chmod(directory,0o777)
    marker=Path(directory)/'descendant'
    program="import os,time;from pathlib import Path;pid=os.fork();Path(%r).write_text(str(os.getpid())) if pid==0 else None;time.sleep(30) if pid==0 else time.sleep(.2)" % str(marker)
    done=threading.Event()
    def reap():
        while not done.is_set():
            if marker.exists():
                try:os.waitpid(int(marker.read_text()),os.WNOHANG)
                except ChildProcessError:pass
            time.sleep(.01)
    thread=threading.Thread(target=reap);thread.start()
    try:
        assert m.run_client([sys.executable,'-c',program],dict(os.environ),cwd=directory)==0
        assert marker.exists()
        pid=int(marker.read_text())
        try:os.kill(pid,0)
        except ProcessLookupError:pass
        else:raise AssertionError('synthetic descendant survived')
        print('LINUX_OWNED_CLI_DESCENDANT_ABSENCE_VERIFIED')
    finally:done.set();thread.join(2)
'''
        result = subprocess.run([sys.executable, "-c", fixture, str(launcher)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LINUX_OWNED_CLI_DESCENDANT_ABSENCE_VERIFIED", result.stdout)
