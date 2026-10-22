import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'budget_overlay', ROOT / 'scripts/build_budget_qualification_overlay.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BudgetOverlayTests(unittest.TestCase):
    def setUp(self):
        self.transport = "function register(origin) { if (origin !== 'http://litellm:4000') return; }"
        self.forwarder = module.ANCHOR + '\n    await guard.acquire(key)\n    await guard.warm(tokens)\n'

    def build(self, **kwargs):
        args = dict(transport=self.transport, forwarder=self.forwarder,
                    transport_sha=module.digest(self.transport),
                    forwarder_sha=module.digest(self.forwarder),
                    canonical_origin='http://litellm:4000',
                    test_origin='http://test-proxy:4000')
        args.update(kwargs)
        return module.build(**args)

    def test_test_route_only_and_original_input_unchanged(self):
        result = self.build()
        self.assertIn('if (origin !== "http://test-proxy:4000") return;', result['transportSource'])
        self.assertIn("'http://litellm:4000'", self.transport)
        self.assertNotIn('http://litellm:4000', result['transportSource'])

    def test_refuses_before_admission_and_preparation(self):
        result = self.build()['forwarderSource']
        self.assertLess(result.index('raise HTTPException(422'), result.index('await guard.acquire'))
        self.assertLess(result.index('raise HTTPException(422'), result.index('await guard.warm'))
        self.assertIn("tokenized['count'] >= 950000", result)
        self.assertIn("data['max_tokens'] < 512", result)

    def test_changed_source_fails_closed(self):
        with self.assertRaises(ValueError):
            self.build(transport_sha='0' * 64)

    def test_missing_boundary_fails_closed(self):
        with self.assertRaises(ValueError):
            self.build(forwarder='changed', forwarder_sha=module.digest('changed'))

    def test_duplicate_fence_fails_closed(self):
        with self.assertRaises(ValueError):
            self.build(transport=self.transport * 2, transport_sha=module.digest(self.transport * 2))

    def test_same_origin_refused(self):
        with self.assertRaises(ValueError):
            self.build(test_origin='http://litellm:4000')

    def test_credentials_paths_and_wildcards_refused(self):
        for value in ['https://' + 'name:password@example.com', 'https://example.com/v1',
                      'https://*.example.com', 'https://example.com?x=1',
                      'https://example.com#fragment', 'ftp://example.com',
                      'http://example.com:invalid', "https://example.com'bad"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.build(test_origin=value)

    def test_generated_hashes_match_exact_bytes(self):
        result = self.build()
        self.assertEqual(result['outputSHA256']['transport'], module.digest(result['transportSource']))
        self.assertEqual(result['outputSHA256']['forwarder'], module.digest(result['forwarderSource']))

    def test_rejects_origins_javascript_would_normalize_differently(self):
        for value in ['http://example.com:80', 'https://example.com:443',
                      'http://EXAMPLE.com', 'http://127.1', 'http://2130706433',
                      'http://0x7f000001', 'http://[0:0:0:0:0:0:0:1]:4000',
                      'http://[fe80::1%25zone]:4000', 'http://example.com:04000']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.build(test_origin=value)

    def test_accepts_exact_canonical_origins(self):
        for value in ['https://example.com', 'http://127.0.0.1:4000',
                      'http://[::1]:4000']:
            with self.subTest(value=value):
                self.assertEqual(module.origin(value), value)

    def test_cli_fingerprints_raw_crlf_and_preserves_input_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transport = (self.transport + '\r\n').encode()
            forwarder = self.forwarder.replace('\n', '\r\n').encode()
            (root / 'transport.cjs').write_bytes(transport)
            (root / 'forwarder.py').write_bytes(forwarder)
            args = ['builder', '--transport-source', str(root / 'transport.cjs'),
                    '--forwarder-source', str(root / 'forwarder.py'),
                    '--transport-sha256', module.digest(transport.decode()),
                    '--forwarder-sha256', module.digest(forwarder.decode()),
                    '--canonical-origin', 'http://litellm:4000',
                    '--test-origin', 'http://test-proxy:4000',
                    '--output', str(root / 'output')]
            with mock.patch.object(sys, 'argv', args), contextlib.redirect_stdout(io.StringIO()):
                module.main()
            result = json.loads((root / 'output/canary-overlay.json').read_text(encoding='utf-8'))
            self.assertEqual(result['inputSHA256']['transport'], module.digest(transport.decode()))
            self.assertTrue(result['transportSource'].endswith('\r\n'))
            self.assertEqual((root / 'transport.cjs').read_bytes(), transport)
            self.assertEqual((root / 'forwarder.py').read_bytes(), forwarder)


if __name__ == '__main__':
    unittest.main()
