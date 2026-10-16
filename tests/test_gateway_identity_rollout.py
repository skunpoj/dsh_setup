"""Mocked failure-path checks; these never invoke Kubernetes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('identity_rollout', SCRIPTS / 'rollout_gateway_identity.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GatewayRolloutSafety(unittest.TestCase):
    def fixture(self, root, digest=None):
        (root / 'scripts').mkdir()
        (root / 'docs/context-evidence').mkdir(parents=True)
        (root / 'scripts/auth_proxy.js').write_text('// tested source', encoding='utf-8')
        (root / 'scripts/runtime_rollout_probe.js').write_text('// probe', encoding='utf-8')
        actual = hashlib.sha256(b'// tested source').hexdigest()
        (root / 'docs/context-evidence/user-isolation-canary-20261016.json').write_text(
            json.dumps({'gatewayOverlaySHA256': digest or actual}), encoding='utf-8')
        return actual

    def test_source_not_tested_in_canary_refused_before_kubernetes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, 'wrong')
            with patch.object(module, 'ROOT', root), patch.object(module, 'kube') as kube, \
                 patch.object(sys, 'argv', ['rollout', '--output', str(root / 'result')]):
                with self.assertRaisesRegex(RuntimeError, 'differs'):
                    module.main()
                kube.assert_not_called()

    def test_running_hash_mismatch_restores_spec_and_cleans_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            before = {'spec': {'replicas': 1, 'template': {'metadata': {}, 'spec': {
                'volumes': [], 'containers': [{'name': 'gateway', 'volumeMounts': [],
                                               'command': ['node', '/original.js']} ]}}}}
            calls = []

            def kube(*args, data=None):
                calls.append(args)
                if args[0] == 'get':
                    return json.dumps(before)
                if args[0] == 'exec':
                    if '-e' in args:
                        return 'wrong-running-hash'
                    return '{}'
                return ''

            with patch.object(module, 'ROOT', root), patch.object(module, 'kube', side_effect=kube), \
                 patch.object(module, 'legacy_fingerprint', return_value={'histories': 80}), \
                 patch.object(sys, 'argv', ['rollout', '--output', str(root / 'result')]):
                with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                    module.main()
            patches = [json.loads(c[-1]) for c in calls if c[0] == 'patch']
            self.assertEqual(patches[-1], [{'op': 'replace', 'path': '/spec', 'value': before['spec']}])
            self.assertIn('--type=json', [c for c in calls if c[0] == 'patch'][-1])
            self.assertTrue(any(c[-1] == 'cleanup' for c in calls))
            record = json.loads((root / 'result/gateway-identity-live.json').read_text())
            self.assertEqual(record['status'], 'failed')
            self.assertTrue(record['gatewaySpecificationRestored'])


if __name__ == '__main__':
    unittest.main()
