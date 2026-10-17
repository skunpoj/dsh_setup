import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import isolation_canary_resources as canary


class CanaryResources(unittest.TestCase):
    def setUp(self):
        self.namespace = 'dsh-iso-20261016-010203'
        self.docs = canary.build(self.namespace, 'registry/runtime@sha256:' + 'a' * 64)

    def test_only_synthetic_subpaths_and_distinct_private_state(self):
        paths = []
        for d in self.docs:
            if d['kind'] != 'Deployment' or not d['metadata']['name'].endswith('-secure'):
                continue
            mounts = d['spec']['template']['spec']['containers'][0]['volumeMounts']
            private = {m['subPath'] for m in mounts if m['name'] == 'protected-workspace'}
            self.assertEqual(len(private), 6)
            self.assertTrue(all(p.startswith('dsh-isolation-tests/' + self.namespace + '/private/') for p in private))
            paths.append(private)
            source = next(m for m in mounts if m['name'] == 'synthetic-source')
            self.assertTrue(source['readOnly'])
            self.assertTrue(source['subPath'].endswith('/source'))
        self.assertEqual(len(paths), 2)
        self.assertTrue(paths[0].isdisjoint(paths[1]))

    def test_rejects_production_namespace_claim_and_legacy_subpath(self):
        with self.assertRaises(ValueError):
            canary.build('llm', 'registry/runtime@sha256:' + 'a' * 64)
        for mode in ['claim', 'path']:
            docs = copy.deepcopy(self.docs)
            d = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-secure'))
            pod = d['spec']['template']['spec']
            if mode == 'claim':
                pod['volumes'][0]['persistentVolumeClaim']['claimName'] = 'dsh-secure-state'
            else:
                next(m for m in pod['containers'][0]['volumeMounts'] if m['name'] == 'protected-workspace')['subPath'] = 'dsh/dsh_storage'
            with self.assertRaises(ValueError):
                canary.validate(docs, self.namespace, 'dsh-isolation-tests/' + self.namespace)

    def test_gateway_migrates_fixture_credentials_out_of_readonly_secret(self):
        gateway = next(d for d in self.docs if d['kind'] == 'Deployment'
                       and d['metadata']['name'] == 'dsh-environment-gateway')
        pod = gateway['spec']['template']['spec']
        container = pod['containers'][0]
        store = next(e['value'] for e in container['env']
                     if e['name'] == 'DSH_USER_STORE_PATH')
        self.assertEqual(store, '/auth/users.json')
        auth = next(m for m in container['volumeMounts'] if m['mountPath'] == '/auth')
        self.assertFalse(auth.get('readOnly', False))
        seed = next(c for c in pod['initContainers']
                    if c['name'] == 'synthetic-hashed-auth')
        source = next(m for m in seed['volumeMounts']
                      if m['mountPath'] == '/test-identities')
        self.assertTrue(source['readOnly'])
        self.assertIn('migrateUsers', seed['command'][2])
        self.assertIn('writeAtomicUsers', seed['command'][2])


if __name__ == '__main__':
    unittest.main()
