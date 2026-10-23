"""Exercise the real log CLI without a GPU, network or private log disclosure."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('gpu_trial_cli', Path(__file__).resolve().parents[1] / 'scripts/check_gpu_trial_log.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class LogCliTests(unittest.TestCase):
    def test_stdin_exit_status_and_no_raw_log_disclosure(self):
        for text, code in [('Prefill batch\nDecode batch', 0),
                           ('Prefill batch\nCUDA error: out of memory\nprivate prompt', 1),
                           ('private prompt without inference evidence', 2)]:
            with self.subTest(code=code), patch.object(gate.sys, 'stdin', io.StringIO(text)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    actual = gate.main([])
                self.assertEqual(actual, code)
                value = json.loads(output.getvalue())
                self.assertEqual(value['passed'], code == 0)
                self.assertNotIn('private prompt', output.getvalue())

    def test_missing_and_present_file_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.log'
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(gate.main([str(path)]), 2)
            self.assertEqual(json.loads(output.getvalue()), {'passed': False, 'error': 'Log unavailable'})
            self.assertNotIn(directory, output.getvalue())
            path.write_bytes(b'Prefill batch\nDecode batch\xff')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(gate.main([str(path)]), 0)


if __name__ == '__main__':
    unittest.main()
