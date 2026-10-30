"""New accounts are gated by local storage headroom, never by an account count."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import capacity_worker
from capacity_worker import Worker, SIGNUP_STORAGE_RESERVE_GIB


class FakeKube:
    def __init__(self, free_gib):
        self.free_gib = free_gib

    def call(self, method, kind, *args, **kwargs):
        if kind == 'Node':
            return {'items': [{'metadata': {'name': 'n1'}, 'status': {'allocatable': {'cpu': '64', 'memory': '1000Gi', 'pods': '250'}}}]}
        if kind == 'AllPod':
            return {'items': []}
        if kind == 'NodeMetrics':
            return {'items': [{'metadata': {'name': 'n1'}, 'timestamp': datetime.now(timezone.utc).isoformat(),
                               'usage': {'cpu': '1', 'memory': '1Gi'}}]}
        if kind == 'StorageCapacity':
            return {'items': [{'storageClassName': 'topolvm', 'capacity': f'{self.free_gib}Gi'}]}
        raise AssertionError(kind)


def pair_docs(*args, **kwargs):
    # One pair: 20 GiB of claims (the planner budgets claims + 2 GiB, minimum 23).
    claim = {'kind': 'PersistentVolumeClaim', 'spec': {'resources': {'requests': {'storage': '20Gi'}}}}
    deployment = {'kind': 'Deployment', 'spec': {'template': {'spec': {'containers': []}}}}
    return [claim, deployment], None, None


class StorageReserveTests(unittest.TestCase):
    def worker(self, free_gib, configured=None):
        w = Worker.__new__(Worker)
        w.config = {'storageClass': 'topolvm', 'sourceConfigMap': 'dsh-cap-src-x', 'serviceControlPVC': 'pvc'}
        if configured is not None:
            w.config['reserveStorageGiB'] = configured
        w.template = {'templates': [], 'claims': []}
        w.kube = FakeKube(free_gib)
        w.central = Path('/nonexistent-central')
        return w

    def storage(self, free_gib, configured=None):
        def no_central(path):
            raise OSError('central share not mounted in the test')
        with patch.object(capacity_worker, 'generate', pair_docs), \
             patch.object(capacity_worker, 'sidecar', lambda d, *a: d), \
             patch.object(capacity_worker.os, 'statvfs', no_central, create=True):
            r = self.worker(free_gib, configured).resources()
        return r['capacityInputs']['resources']['storageGiB'], r['storageGiBAfterPair']

    def test_floor_is_200_gib(self):
        self.assertEqual(SIGNUP_STORAGE_RESERVE_GIB, 200)
        row, _ = self.storage(1000)
        self.assertEqual(row['reserve'], 200)

    def test_config_can_raise_but_not_lower_the_reserve(self):
        self.assertEqual(self.storage(1000, configured=32)[0]['reserve'], 200, 'A lower site value cannot weaken the floor')
        self.assertEqual(self.storage(1000, configured=300)[0]['reserve'], 300)

    def test_new_pair_refused_only_below_the_reserve(self):
        budget = self.storage(1000)[0]['pairBudget']
        self.assertGreater(self.storage(200 + budget + 1)[1], 0, 'Enough headroom admits a new pair')
        self.assertLess(self.storage(200 + budget - 1)[1], 0, 'A pair that would cut into the reserve is refused')


if __name__ == '__main__':
    unittest.main()
