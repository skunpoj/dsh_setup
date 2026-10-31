import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_scan', ROOT / 'scripts/scan_public.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PublicScanTests(unittest.TestCase):
    def found(self, data, name='sample.txt'):
        return module.scan_bytes(name, data.encode())
    def test_token_is_found_without_returning_value(self):
        value = 'gh' + 'p_' + 'A' * 40
        result = self.found(value)
        self.assertTrue(result)
        self.assertNotIn(value, repr(result))
    def test_organization_host_is_found(self):
        self.assertTrue(self.found('private.' + 'bot' + '.or.th'))
        self.assertTrue(self.found('dso' + 'reg-private.example'))
    def test_personal_path_is_found(self):
        self.assertTrue(self.found('C:' + chr(92) + 'Users' + chr(92) + 'person' + chr(92) + 'file'))
    def test_url_credentials_are_found(self):
        self.assertTrue(self.found('https://' + 'alice:secret' + '@host.example'))
    def test_exact_invalid_public_fixture(self):
        sample = 'https://' + 'user:password' + '@gpu.example.internal'
        self.assertEqual(self.found(sample, 'gpu-stack/tests/test_portable.py'), [])
        self.assertTrue(self.found(sample, 'unreviewed.txt'))
    def test_private_key_markers_in_unknown_binary(self):
        self.assertTrue(self.found('prefix\x00' + '-----BEGIN ' + 'PRIVATE KEY-----'))
    def test_generic_addresses_and_paths_are_allowed(self):
        self.assertEqual(self.found('https://service.example.org /home/dsh/project 10.0.0.0/8'), [])

if __name__ == '__main__': unittest.main()
