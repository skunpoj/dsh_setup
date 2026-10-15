"""Exercise failure recovery without touching a cluster or runtime data."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/rollout_runtime_hardening.py'
SPEC = importlib.util.spec_from_file_location('runtime_rollout', SCRIPT)
rollout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollout)


class RolloutSafetyTests(unittest.TestCase):
    def original(self):
        return {'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
                        'template': {'spec': {'volumes': [
                            {'name': 'protected-workspace', 'persistentVolumeClaim': {'claimName': 'workspace'}},
                            {'name': 'state', 'persistentVolumeClaim': {'claimName': 'state'}}]}}}}

    def test_failed_snapshot_restores_exact_spec_without_applying_new_image(self):
        original = self.original()
        calls = []

        def fake_kube(*args, **kwargs):
            calls.append(args)
            if args[:3] == ('get', 'deploy', 'dsh-secure'):
                if len([c for c in calls if c[:3] == args[:3]]) == 1:
                    return json.dumps(original)
                return json.dumps({'metadata': {'generation': 2},
                                   'status': {'observedGeneration': 2, 'availableReplicas': 1}})
            if args[:2] == ('get', 'pods'):
                return '{"items":[]}'
            if args[:2] == ('get', 'job'):
                return '{"status":{"failed":1}}'
            return ''

        with tempfile.TemporaryDirectory() as folder:
            argv = ['rollout', '--environment', 'secure', '--image', 'registry/runtime@sha256:' + 'a' * 64,
                    '--rollback-dir', folder]
            with patch.object(sys, 'argv', argv), patch.object(rollout, 'kube', fake_kube):
                with self.assertRaisesRegex(RuntimeError, 'Snapshot job failed'):
                    rollout.main()
            self.assertEqual(json.loads((Path(folder) / 'dsh-secure-before.json').read_text()), original)
        patches = [call for call in calls if call[0] == 'patch']
        self.assertEqual(len(patches), 1)
        self.assertIn('--type=json', patches[0])
        self.assertEqual(json.loads(patches[0][-1]), [
            {'op': 'replace', 'path': '/spec', 'value': original['spec']}])
        deletion = next(i for i, call in enumerate(calls) if call[:2] == ('delete', 'job'))
        restoration = next(i for i, call in enumerate(calls) if call[0] == 'patch')
        self.assertLess(deletion, restoration)
        self.assertIn('--wait=true', calls[deletion])
        self.assertTrue(any(call[0] == 'exec' for call in calls))

    def test_existing_rollback_point_is_preserved_and_writer_is_not_stopped(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            saved = Path(folder) / 'dsh-secure-before.json'
            saved.write_text('preserve me')
            argv = ['rollout', '--environment', 'secure', '--image', 'registry/runtime@sha256:' + 'a' * 64,
                    '--rollback-dir', folder]

            def fake_kube(*args, **kwargs):
                calls.append(args)
                return json.dumps(self.original())

            with patch.object(sys, 'argv', argv), patch.object(rollout, 'kube', fake_kube):
                with self.assertRaises(FileExistsError):
                    rollout.main()
            self.assertEqual(saved.read_text(), 'preserve me')
        self.assertFalse(any(call[0] == 'scale' for call in calls))


if __name__ == '__main__':
    unittest.main()
