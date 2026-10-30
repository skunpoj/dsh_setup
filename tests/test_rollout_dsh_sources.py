import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import rollout_dsh_sources as r

GATEWAY_KEYS = ['auth_proxy.js', 'capacity_policy.js', 'platform_ui.js', 'ldapts-LICENSE', 'app-supervisor.py']


class FakeApi:
    def __init__(self, ready=True):
        self.ready = ready
        self.maps = {'dsh-login-recovery-old': {'data': {k: 'old' for k in GATEWAY_KEYS}}}
        self.dep = {'metadata': {'generation': 1}, 'spec': {'replicas': 1, 'template': {'spec': {'volumes': [
            {'name': 'gateway-source', 'configMap': {'name': 'dsh-login-recovery-old'}}, {'name': 'routing', 'configMap': {'name': 'keep'}}]}}},
            'status': {'observedGeneration': 1, 'updatedReplicas': 1, 'readyReplicas': 1, 'replicas': 1}}
        self.patches, self.created = [], []

    def deployment(self, name): return copy.deepcopy(self.dep)
    def config_map(self, name): return self.maps.get(name)
    def create_config_map(self, doc): self.created.append(doc); self.maps[doc['metadata']['name']] = {'data': doc['data']}
    def patch_deployment(self, name, patch):
        self.patches.append(patch)
        volume = patch['spec']['template']['spec']['volumes'][0]
        for v in self.dep['spec']['template']['spec']['volumes']:
            if v['name'] == volume['name']:
                v['configMap'] = volume['configMap']
        self.dep['metadata']['generation'] += 1
        self.dep['status'] = {'observedGeneration': self.dep['metadata']['generation'], 'updatedReplicas': 1,
                              'readyReplicas': 1 if self.ready or len(self.patches) > 1 else 0, 'replicas': 1}


class Args:
    apply, commit, settle, public_url, public_ca_file = False, 'abc123', 0, '', None


class RolloutTests(unittest.TestCase):
    def test_bundle_comes_only_from_repo_and_adds_new_modules(self):
        name, doc = r.build_bundle('gateway', GATEWAY_KEYS)
        self.assertTrue(name.startswith('dsh-gateway-src-'))
        self.assertIn('session_demand.js', doc['data'])
        self.assertTrue(doc['immutable'])
        self.assertEqual(doc['data']['ldapts-LICENSE'], (r.ROOT / 'vendor/ldapts/LICENSE').read_text(encoding='utf-8').replace('\r\n', '\n'))
        self.assertEqual(name, r.build_bundle('gateway', GATEWAY_KEYS)[0], 'Same source, same name')
        self.assertIn('capacity_session.py', r.build_bundle('controller', ['capacity_controller.py'])[1]['data'])

    def test_unknown_live_key_fails_closed(self):
        with self.assertRaises(ValueError):
            r.build_bundle('gateway', GATEWAY_KEYS + ['unreviewed.js'])

    def test_dry_run_changes_nothing(self):
        api = FakeApi()
        self.assertEqual(r.rollout(api, 'gateway', Args(), log=lambda *_: None), 0)
        self.assertEqual((api.patches, api.created), ([], []))

    def test_apply_switches_only_the_source_volume(self):
        api, args = FakeApi(), Args()
        args.apply = True
        self.assertEqual(r.rollout(api, 'gateway', args, log=lambda *_: None), 0)
        self.assertEqual(len(api.created), 1)
        vols = {v['name']: v['configMap']['name'] for v in api.dep['spec']['template']['spec']['volumes']}
        self.assertTrue(vols['gateway-source'].startswith('dsh-gateway-src-'))
        self.assertEqual(vols['routing'], 'keep')

    def test_failed_rollout_switches_back(self):
        api, args = FakeApi(ready=False), Args()
        args.apply = True
        r.wait_ready_original = r.wait_ready
        try:
            r.wait_ready = lambda api_, name, timeout=0, settle=0: api_.dep['status']['readyReplicas'] == 1
            self.assertEqual(r.rollout(api, 'gateway', args, log=lambda *_: None), 1)
        finally:
            r.wait_ready = r.wait_ready_original
        self.assertEqual(api.dep['spec']['template']['spec']['volumes'][0]['configMap']['name'], 'dsh-login-recovery-old')
        self.assertIn('dsh-login-recovery-old', api.maps, 'The previous source is never deleted')

    def test_role_rules_are_only_added(self):
        existing = [{'apiGroups': [''], 'resources': ['services'], 'verbs': ['get', 'create']},
                    {'apiGroups': ['apps'], 'resources': ['deployments'], 'verbs': ['get', 'create']}]
        merged = r.merged_rules(existing)
        self.assertEqual(merged[:2], existing)
        self.assertIn({'apiGroups': ['apps'], 'resources': ['deployments/scale'], 'verbs': ['get', 'patch']}, merged)
        self.assertEqual(r.merged_rules(merged), merged, 'Idempotent')

    def test_requires_https_and_token(self):
        with self.assertRaises(SystemExit):
            r.main(['gateway', '--api', 'http://insecure.example'])


if __name__ == '__main__':
    unittest.main()
