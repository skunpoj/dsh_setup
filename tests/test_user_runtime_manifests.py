import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('generator', Path(__file__).resolve().parents[1] / 'scripts/generate_user_runtimes.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class IsolationManifests(unittest.TestCase):
    def test_volume_and_route_boundaries(self):
        docs = generator.generate(['alice', 'bob'], 'registry/runtime@sha256:' + 'a' * 64)
        workloads = [d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] != 'dsh-environment-gateway']
        self.assertEqual(len(workloads), 4)
        private_claims = set()
        services = {d['metadata']['name']: d for d in docs if d['kind'] == 'Service'}
        for workload in workloads:
            pod = workload['spec']['template']['spec']
            self.assertFalse(pod['automountServiceAccountToken'])
            for volume in pod['volumes']:
                claim = volume['persistentVolumeClaim']['claimName']
                if claim == 'dsh-package-approved':
                    mount = next(m for m in pod['containers'][0]['volumeMounts'] if m['name'] == volume['name'])
                    self.assertTrue(mount['readOnly'])
                else:
                    self.assertNotIn(claim, private_claims)
                    private_claims.add(claim)
            self.assertEqual(services[workload['metadata']['name']]['spec']['selector'], workload['spec']['selector']['matchLabels'])
        config = next(d for d in docs if d['kind'] == 'ConfigMap')
        routes = json.loads(config['data']['users.json'])
        endpoints = [t['host'] for targets in routes.values() for t in targets.values()]
        self.assertEqual(len(set(endpoints)), 4)
        gateway = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'dsh-environment-gateway')
        mounts = gateway['spec']['template']['spec']['containers'][0]['volumeMounts']
        self.assertFalse(any(m['mountPath'] in ('/state', '/workspace') for m in mounts))
        self.assertTrue(all(m['readOnly'] for m in mounts if m['name'].startswith('token-')))

    def test_rejects_invalid_provisioning(self):
        for users in (['../alice'], ['alice', 'alice'], []):
            with self.assertRaises(ValueError):
                generator.generate(users, 'registry/runtime@sha256:' + 'a' * 64)
        with self.assertRaises(ValueError):
            generator.generate(['alice'], 'registry/runtime:latest')

    def test_approved_snapshot_is_secure_only_and_read_only(self):
        image = 'registry/runtime@sha256:' + 'a' * 64
        for source, approval in [('rdt-snapshot', None), (None, 'OWNER-TEST'), ('../source', 'OWNER-TEST')]:
            with self.assertRaises(ValueError):
                generator.generate(['alice'], image, source, approval)
        docs = generator.generate(['alice', 'bob'], image, 'rdt-snapshot', 'OWNER-TEST')
        for workload in (d for d in docs if d['kind'] == 'Deployment' and '-u-' in d['metadata']['name']):
            template = workload['spec']['template']
            volumes = [v for v in template['spec']['volumes'] if v['name'] == 'rdt-source']
            mounts = [m for m in template['spec']['containers'][0]['volumeMounts'] if m['name'] == 'rdt-source']
            if workload['metadata']['name'].endswith('-secure'):
                self.assertTrue(volumes[0]['persistentVolumeClaim']['readOnly'])
                self.assertTrue(mounts[0]['readOnly'])
                self.assertEqual(mounts[0]['mountPath'], '/data/rdt')
                self.assertEqual(template['metadata']['annotations']['dsh.bot.or.th/rdt-approval'], 'OWNER-TEST')
            else:
                self.assertFalse(volumes)
                self.assertFalse(mounts)


if __name__ == '__main__':
    unittest.main()
