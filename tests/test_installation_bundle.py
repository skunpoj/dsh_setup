import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

spec = importlib.util.spec_from_file_location('bundle', Path(__file__).resolve().parents[1] / 'scripts/check_installation_bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class InstallationBundleTests(unittest.TestCase):
    def run_bundle(self, documents, external=()):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'candidate.yaml'
            target.write_text(yaml.safe_dump_all(documents), encoding='utf-8')
            return bundle.check([target], external)

    def deployment(self):
        return {'kind': 'Deployment', 'metadata': {'name': 'worker', 'namespace': 'test'},
                'spec': {'template': {'spec': {'containers': [{'name': 'app', 'image': 'example/app@sha256:' + 'a' * 64,
                'env': [{'name': 'TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'client', 'key': 'token'}}}]}]}}}}

    def test_missing_secret_is_not_ready(self):
        result = self.run_bundle([self.deployment()])
        self.assertFalse(result['passed'])
        self.assertIn('needs Secret/test/client', result['errors'][0])

    def test_external_resource_must_match_namespace(self):
        self.assertFalse(self.run_bundle([self.deployment()], ['Secret/other/client'])['passed'])
        self.assertTrue(self.run_bundle([self.deployment()], ['Secret/test/client'])['passed'])

    def test_tag_and_duplicate_are_refused(self):
        obj = self.deployment()
        obj['spec']['template']['spec']['containers'][0]['image'] = 'example/app:latest'
        result = self.run_bundle([obj, obj], ['Secret/test/client'])
        self.assertEqual(len(result['errors']), 2)

    def test_ingress_backend_and_certificate_required(self):
        obj = {'kind': 'Ingress', 'metadata': {'name': 'web', 'namespace': 'test'},
               'spec': {'tls': [{'secretName': 'tls'}], 'defaultBackend': {'service': {'name': 'gateway'}}}}
        self.assertEqual(len(self.run_bundle([obj])['errors']), 2)
        self.assertTrue(self.run_bundle([obj], ['Secret/test/tls', 'Service/test/gateway'])['passed'])


if __name__ == '__main__':
    unittest.main()
