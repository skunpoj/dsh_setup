"""Run the presentation/credential/transport Node contracts in Python CI discovery."""
from pathlib import Path
import shutil
import subprocess
import unittest

class PresentationRuntimeTests(unittest.TestCase):
    def test_presentation_and_legacy_identity_boundaries(self):
        root=Path(__file__).resolve().parents[1]
        node=shutil.which('node')
        self.assertIsNotNone(node,'Node is required; do not silently skip runtime contracts')
        result=subprocess.run([node,'--test','--test-reporter=tap',
            'tests/test_credential_broker.cjs','tests/test_credential_identity.cjs',
            'tests/test_credential_theme.cjs','tests/test_legacy_jupyter_gateway.js'],
            cwd=root,capture_output=True,text=True,encoding='utf8',timeout=45)
        print(result.stdout,end='')
        if result.stderr:print(result.stderr,end='')
        self.assertEqual(result.returncode,0,'Node presentation/transport contracts failed')
        self.assertIn('larger HTML health allowance does not expand the identity-response limit',result.stdout)

if __name__=='__main__':unittest.main()
