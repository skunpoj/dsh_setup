import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from rollout_legacy_context_transport import candidate


class LegacyContextTransportTests(unittest.TestCase):
    def fixture(self):
        return {'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
                        'template': {'spec': {'volumes': [{'name': 'private-state', 'persistentVolumeClaim': {'claimName': 'existing'}}],
                            'containers': [
                                {'name': 'dsh', 'image': 'image@sha256:'+'a'*64,
                                 'env': [{'name': 'HOME', 'value': '/root'}],
                                 'volumeMounts': [{'name': 'private-state', 'mountPath': '/root'}]},
                                {'name': 'auth-proxy', 'image': 'proxy', 'env': [{'name': 'AUTH_USER', 'value': 'owner'}]},
                            ]}}}}

    def test_budget_hook_does_not_change_existing_auth_or_storage(self):
        original = self.fixture()
        spec = candidate(original, 'qualified-source')
        before = original['spec']['template']['spec']
        after = spec['template']['spec']
        self.assertEqual(after['containers'][1], before['containers'][1])
        self.assertEqual(after['volumes'][:-1], before['volumes'])
        self.assertEqual(after['containers'][0]['volumeMounts'][:-1], before['containers'][0]['volumeMounts'])
        self.assertTrue(after['containers'][0]['volumeMounts'][-1]['readOnly'])
        self.assertEqual(original, self.fixture(), 'Input specification must remain unchanged')

    def test_conflicting_loader_or_mount_and_multiwriter_fail_closed(self):
        for mode in ['loader', 'mount', 'volume', 'replicas', 'strategy', 'image']:
            value = copy.deepcopy(self.fixture());spec=value['spec'];pod=spec['template']['spec'];worker=pod['containers'][0]
            if mode == 'loader': worker['env'].append({'name': 'NODE_OPTIONS', 'value': '--require other'})
            elif mode == 'mount': worker['volumeMounts'].append({'name': 'other', 'mountPath': '/context-runtime'})
            elif mode == 'volume': pod['volumes'].append({'name': 'context-transport'})
            elif mode == 'replicas': spec['replicas']=2
            elif mode == 'strategy': spec['strategy']['type']='RollingUpdate'
            else: worker['image']='image:latest'
            with self.assertRaises(ValueError): candidate(value, 'qualified-source')


if __name__ == '__main__': unittest.main()
