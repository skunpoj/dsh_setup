"""Mock a failed central reconciliation and verify exact runtime rollback."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('central_restore', Path(__file__).resolve().parents[1] / 'scripts/restore_central_workspace.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CentralRestoreRollback(unittest.TestCase):
    def test_worker_failure_restores_original_spec_without_deleting_any_pvc(self):
        original = {'spec': {'replicas': 1, 'template': {'spec': {
            'containers': [{'image': 'registry/runtime@sha256:' + 'a' * 64}],
            'volumes': [
                {'name': 'protected-workspace', 'persistentVolumeClaim': {'claimName': 'original-local'}},
                {'name': 'state', 'persistentVolumeClaim': {'claimName': 'state'}}]}}}}
        calls = []

        def fake_kube(*args, **kwargs):
            calls.append(args)
            if args[:3] == ('get', 'deploy', 'dsh-secure'):
                return json.dumps(original)
            if args[:2] == ('get', 'pods'):
                return '{"items":[]}'
            if args[:2] == ('get', 'job'):
                return '{"status":{"failed":1}}'
            return ''

        with tempfile.TemporaryDirectory() as directory:
            argv = ['restore', '--central-claim', 'central', '--rollback-dir', directory, '--gateway-probe', '/auth/test.js']
            with patch.object(sys, 'argv', argv), patch.object(module, 'kube', fake_kube), patch.object(module, 'wait_ready') as ready:
                with self.assertRaisesRegex(RuntimeError, 'Reconciliation failed'):
                    module.main()
                ready.assert_called_once()
            self.assertEqual(json.loads((Path(directory) / 'dsh-secure-before-central-mount.json').read_text()), original)
        patched = [call for call in calls if call[0] == 'patch']
        self.assertEqual(len(patched), 1)
        self.assertIn('--type=json', patched[0])
        self.assertEqual(json.loads(patched[0][-1]), [{'op': 'replace', 'path': '/spec', 'value': original['spec']}])
        self.assertFalse(any(call[:2] == ('delete', 'pvc') for call in calls))


if __name__ == '__main__':
    unittest.main()
