"""The workspace start script must save the launch token but never log it."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'container' / 'start-dsh.sh'


def token_loop(source):
    # The reader loop that copies `dsh web` output to the container log.
    match = re.search(r'while IFS= read -r line; do\n.*?\ndone <"\$fifo" &', source, re.S)
    if not match:
        raise AssertionError('start-dsh.sh token loop not found')
    return match.group(0).replace(' &', '')


@unittest.skipUnless(shutil.which('bash'), 'bash required')
class StartDshTokenRedaction(unittest.TestCase):
    def test_token_saved_but_not_logged(self):
        token = 'Ab9_-' + 'x' * 38
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'runtime-tokens').mkdir()
            fifo = tmp / 'fifo'
            script = token_loop(SCRIPT.read_text(encoding='utf-8')).replace('/runtime-tokens/', str(tmp / 'runtime-tokens').replace('\\', '/') + '/')
            program = ('set -euo pipefail\nfifo="$1"\nmkfifo "$fifo"\n'
                       f'printf \'%s\\n\' "dsh web: http://127.0.0.1:3080/?token={token}" "ready" >"$fifo" &\n'
                       + script + '\n')
            result = subprocess.run(['bash', '-c', program, 'test', str(fifo).replace('\\', '/')],
                                    env={'DSH_ENVIRONMENT': 'secure', 'PATH': '/usr/bin:/bin'},
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(token, result.stdout, 'The launch token must never reach the log')
            self.assertIn('token=<redacted>', result.stdout)
            self.assertIn('ready', result.stdout, 'Other output still reaches the log')
            self.assertEqual((tmp / 'runtime-tokens' / 'secure').read_text(), token, 'The token file still gets the real token')


if __name__ == '__main__':
    unittest.main()
