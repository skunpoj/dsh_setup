import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import install_live_client_layer as installer


@unittest.skipUnless(os.name == 'posix', 'The production installer uses Linux file descriptors')
class PrivateReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_fifo_refused_without_waiting_for_a_writer(self):
        fifo = self.root / 'profile'
        os.mkfifo(fifo)
        code = ('import sys;sys.path.insert(0,' + repr(str(Path(installer.__file__).parent)) + ');'
                'from install_live_client_layer import regular;regular(' + repr(str(fifo)) + ')')
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Expected a private, regular owner file', result.stderr)

    def test_symlink_hardlink_and_oversize_refused(self):
        target = self.root / 'owner-file'
        target.write_bytes(b'preserve')
        link = self.root / 'link'
        link.symlink_to(target)
        with self.assertRaises(OSError):
            installer.regular(link)
        link.unlink()
        os.link(target, link)
        with self.assertRaises(ValueError):
            installer.regular(link)
        self.assertEqual(target.read_bytes(), b'preserve')
        large = self.root / 'large'
        large.write_bytes(b'x' * (installer.MAX_PRIVATE_FILE + 1))
        with self.assertRaisesRegex(ValueError, 'too large'):
            installer.regular(large)

    def test_concurrent_same_size_edit_detected(self):
        profile = self.root / 'profile'
        profile.write_bytes(b'initial')
        read = os.read
        edited = False

        def edit_after_read(fd, count):
            nonlocal edited
            result = read(fd, count)
            if not edited:
                edited = True
                old = profile.stat()
                profile.write_bytes(b'changed')
                os.utime(profile, ns=(old.st_atime_ns, old.st_mtime_ns + 1_000_000))
            return result

        with patch.object(installer.os, 'read', side_effect=edit_after_read):
            with self.assertRaisesRegex(ValueError, 'changed during read'):
                installer.regular(profile)


if __name__ == '__main__':
    unittest.main()
