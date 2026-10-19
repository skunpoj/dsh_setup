import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
generator = load('user_generator', 'generate_user_runtimes.py')
pool = load('signup_generator', 'prepare_signup_pool.py')
config = load('signup_config', 'prepare_signup_config.py')


class SignupPoolTests(unittest.TestCase):
    def setUp(self):
        original = generator.generate(['existing-user'], 'registry/runtime@sha256:' + 'a' * 64)
        self.templates = {env: next(d for d in original if d['kind'] == 'Deployment' and d['metadata']['name'].endswith('-' + env)) for env in ['secure', 'internet']}
        self.claims = {d['metadata']['name']: d for d in original if d['kind'] == 'PersistentVolumeClaim'}

    def test_empty_exclusive_scopes_and_secret_names(self):
        before = copy.deepcopy(self.templates)
        docs, config, paths = pool.generate(self.templates, self.claims, 'signup-test', 3)
        self.assertEqual(self.templates, before)
        self.assertEqual(len(config['slots']), 3)
        self.assertEqual(len(paths), 18)
        self.assertEqual(len(set(paths)), 18)
        workloads = [d for d in docs if d['kind'] == 'Deployment']
        self.assertEqual(len(workloads), 6)
        claims = [d['metadata']['name'] for d in docs if d['kind'] == 'PersistentVolumeClaim']
        self.assertEqual(len(claims), len(set(claims)))
        source_names = {d['metadata']['name'] for d in self.templates.values()}
        self.assertTrue(source_names.isdisjoint(d['metadata']['name'] for d in workloads))
        endpoints = [t['host'] for pair in config['slots'].values() for t in pair.values()]
        self.assertEqual(len(endpoints), len(set(endpoints)))
        for workload in workloads:
            pod = workload['spec']['template']['spec'];container = pod['containers'][0]
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertTrue(container['securityContext']['runAsNonRoot'])
            self.assertTrue(next(e for e in container['env'] if e['name'] == 'DEEPSEEK_API_KEY')['valueFrom']['secretKeyRef']['name'].startswith('dsh-inference-signup-'))
            for mount in container['volumeMounts']:
                if mount['name'] == 'protected-workspace':
                    self.assertTrue(mount['subPath'].startswith('dsh/private/'))
                    self.assertNotEqual(mount['subPath'], 'dsh')

    def test_rejects_unsafe_templates_and_unbounded_capacity(self):
        for count in [0, 17]:
            with self.assertRaises(ValueError):pool.generate(self.templates, self.claims, 'pool', count)
        self.templates['secure']['spec']['template']['spec']['automountServiceAccountToken'] = True
        with self.assertRaises(ValueError):pool.generate(self.templates, self.claims, 'pool', 2)

    def test_replenishment_preserves_assigned_routes_and_excludes_tests(self):
        _, original, _ = pool.generate(self.templates, self.claims, 'old-pool', 2)
        _, added, _ = pool.generate(self.templates, self.claims, 'new-pool', 3)
        document, stage, live = config.build(added, 1, original)
        import json
        routes=json.loads(document['data']['live.json'])['slots']
        self.assertEqual(len(routes),4)
        for slot,pair in original['slots'].items():self.assertEqual(routes[slot],pair)
        self.assertNotIn('new-pool-01',routes)
        self.assertEqual(stage['poolFile'],'/signup-pool/existing.json')
        self.assertTrue(all(m['readOnly'] for m in live['mounts']))
        with self.assertRaises(ValueError):config.build(added,1,added)


if __name__ == '__main__':unittest.main()
