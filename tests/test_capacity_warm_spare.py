"""The controller keeps the gateway's next unassigned slot warm, in pool order."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
# The controller runs on Linux; on a Windows test host these open flags do not exist.
for flag in ['O_NOFOLLOW', 'O_NONBLOCK']:
    if not hasattr(os, flag):
        setattr(os, flag, 0)
from capacity_controller import warm_spares


def route(identity):
    return {env: {'host': f'dsh-u-{identity}-{env}.llm.svc.cluster.local', 'port': 3081,
                  'tokenFile': f'/runtime-tokens/capacity/{identity}/{env}/token'} for env in ['secure', 'internet']}


class WarmSpareTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / 'inventory').mkdir()
        (self.root / 'policy').mkdir()
        self.pool = {'slots': {'cap-1-01': route('1' * 16), 'cap-2-01': route('2' * 16), 'cap-3-01': route('3' * 16)}}
        (self.root / 'inventory' / 'pool.json').write_text(json.dumps(self.pool))

    def assigned(self, slots):
        (self.root / 'policy' / 'assignments.json').write_text(json.dumps({'version': 1, 'assignedSlots': slots}))

    def test_next_unassigned_slot_in_gateway_order(self):
        self.assigned(['cap-1-01'])
        self.assertEqual(warm_spares(self.root, 1), ['dsh-u-' + '2' * 16 + '-secure'])
        self.assertEqual(warm_spares(self.root, 2), ['dsh-u-' + '2' * 16 + '-secure', 'dsh-u-' + '3' * 16 + '-secure'])

    def test_claiming_the_spare_moves_warmth_to_the_next_slot(self):
        self.assigned(['cap-1-01', 'cap-2-01'])
        self.assertEqual(warm_spares(self.root, 1), ['dsh-u-' + '3' * 16 + '-secure'])
        self.assigned(['cap-1-01', 'cap-2-01', 'cap-3-01'])
        self.assertEqual(warm_spares(self.root, 1), [], 'No unassigned slot: nothing is kept warm')

    def test_missing_files_or_zero_count_keep_nothing_warm(self):
        self.assertEqual(warm_spares(self.root, 1), [], 'No assignments file yet')
        self.assigned([])
        self.assertEqual(warm_spares(self.root, 0), [])
        (self.root / 'inventory' / 'pool.json').write_text('not json')
        self.assertEqual(warm_spares(self.root, 1), [])

    def test_foreign_hosts_are_never_warmed(self):
        self.pool['slots']['cap-0-01'] = {'secure': {'host': 'litellm.llm.svc.cluster.local'}, 'internet': {'host': 'x'}}
        (self.root / 'inventory' / 'pool.json').write_text(json.dumps({'slots': {'cap-0-01': self.pool['slots']['cap-0-01']}}))
        self.assigned([])
        self.assertEqual(warm_spares(self.root, 1), [])


if __name__ == '__main__':
    unittest.main()
