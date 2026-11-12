"""Slot retirement (administrator Delete = wipe and recycle): every guard and the fail-closed behaviour, with a fake cluster.

No cluster, no network, no real credentials: the cluster is an in-memory dictionary and the storage is a temporary directory.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import capacity_retirement as cr  # noqa: E402

if os.name == 'nt':
    # The controller's own file helpers use POSIX-only flags; behave the same with plain file access on a laptop.
    def _read_json(path, limit=262144):
        data = Path(path).read_bytes()
        if len(data) > limit:
            raise ValueError('Capacity input exceeded bound')
        return json.loads(data)

    def _atomic_json(path, value):
        temp = Path(str(path) + '.tmp')
        temp.write_text(json.dumps(value), encoding='utf8')
        os.replace(temp, path)
    cr.read_json, cr.atomic_json = _read_json, _atomic_json

OWNED = {'metadata': {'labels': {cr.OWNED_LABEL: 'true'}}}
SLOT_A, SLOT_B, SLOT_BANK = 'cap-' + 'a' * 16 + '-01', 'cap-' + 'b' * 16 + '-01', 'cap-' + 'c' * 16 + '-01'


def ident(slot):
    return hashlib.sha256(slot.encode()).hexdigest()[:16]


def sid(slot, env):
    return hashlib.sha256((slot + env).encode()).hexdigest()[:24]


def names(slot):
    i = ident(slot)
    return {'deployments': ['dsh-u-' + i + '-secure', 'dsh-u-' + i + '-internet'],
            'services': ['dsh-u-' + i + '-secure', 'dsh-u-' + i + '-internet'],
            'claims': ['dsh-u-' + i + '-home', 'dsh-app-status-' + sid(slot, 'secure'), 'dsh-app-status-' + sid(slot, 'internet')],
            'secrets': ['dsh-inference-signup-' + i, 'dsh-harness-signup-' + i + '-secure', 'dsh-harness-signup-' + i + '-internet']}


class FakeCtx(cr.Context):
    def __init__(self, tmp, slots):
        self.central, self.services = tmp / 'central', tmp / 'services'
        self.objects = {}
        self.pod_names = {}
        self.calls = []
        self.fail_keys = False
        self.stuck_pods = False
        self.undeletable = set()
        self.clock = 0
        for slot in slots:
            for group, kind in [('deployments', 'Deployment'), ('services', 'Service'), ('claims', 'PersistentVolumeClaim'), ('secrets', 'Secret')]:
                for name in names(slot)[group]:
                    self.objects[(kind, name)] = json.loads(json.dumps(OWNED))
            for name in names(slot)['deployments']:
                self.pod_names[name] = [{'metadata': {'name': name + '-pod'}}]

    def sleep(self, seconds):
        self.clock += seconds

    def monotonic(self):
        self.clock += 10
        return self.clock

    def names(self, slot):
        return names(slot)

    def get(self, kind, name):
        return self.objects.get((kind, name))

    def delete(self, kind, name):
        self.calls.append(('delete', kind, name))
        if (kind, name) not in self.undeletable:
            self.objects.pop((kind, name), None)

    def scale_zero(self, name):
        self.calls.append(('scale', name))
        if not self.stuck_pods:
            self.pod_names[name] = []

    def pods(self, name):
        return self.pod_names.get(name, [])

    def revoke_keys(self, slot):
        self.calls.append(('revoke', slot))
        if self.fail_keys:
            raise RuntimeError('issuer says no, with details that must never leak: /secret/path')


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='retire-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / 'capacity'
        for sub in ['policy/retirements', 'inventory/runtime-status', 'inventory/runtime-tokens']:
            (self.root / sub).mkdir(parents=True)
        slots = [SLOT_A, SLOT_B, SLOT_BANK]
        (self.root / 'inventory' / 'inventory.json').write_text(json.dumps({'slots': {s: {'state': 'ready'} for s in slots}}))
        (self.root / 'inventory' / 'pool.json').write_text(json.dumps({'slots': {s: {'secure': {}, 'internet': {}} for s in slots}}))
        (self.root / 'policy' / 'assignments.json').write_text(json.dumps({'version': 1, 'assignedSlots': sorted(slots), 'deletedSlots': [SLOT_A, SLOT_B]}))
        self.ctx = FakeCtx(self.tmp, slots)
        for slot in slots:
            private = self.ctx.central / 'dsh' / 'private' / ident(slot)
            (private / 'secure' / 'docs').mkdir(parents=True)
            (private / 'secure' / 'docs' / 'note.txt').write_text('private ' + slot)
            (private / 'state' / 'sessions').mkdir(parents=True)
            (private / 'state' / 'sessions' / 's.json').write_text('{}')
            for env in ['secure', 'internet']:
                (self.ctx.services / sid(slot, env)).mkdir(parents=True)
                (self.ctx.services / sid(slot, env) / 'config.json').write_text('{}')
                (self.root / 'inventory' / 'runtime-status' / sid(slot, env)).mkdir()
            (self.root / 'inventory' / 'runtime-tokens' / ident(slot) / 'secure').mkdir(parents=True)
            (self.root / 'inventory' / 'runtime-tokens' / ident(slot) / 'secure' / 'token').write_text('x')
        self.config = {'protectedSlots': [SLOT_BANK]}

    def request(self, filename, **override):
        value = {'slot': filename, 'user': 'dana', 'requestedBy': 'admin', 'requestedAt': '2026-11-12T10:00:00Z', **override}
        (self.root / 'policy' / 'retirements' / (filename + '.json')).write_text(json.dumps(value))

    def service_ids(self, slot):
        return [sid(slot, 'secure'), sid(slot, 'internet')]

    def run_all(self):
        return cr.process_retirements(self.root, self.ctx, self.config, self.service_ids)

    def result(self, slot):
        return cr.read_result(self.root, slot)

    def inventory(self):
        return json.loads((self.root / 'inventory' / 'inventory.json').read_text())

    def pool(self):
        return json.loads((self.root / 'inventory' / 'pool.json').read_text())['slots']

    def exists(self, slot):
        return (self.ctx.central / 'dsh' / 'private' / ident(slot)).exists()

    def test_happy_path_wipes_everything_of_one_slot_and_nothing_else(self):
        self.request(SLOT_A)
        out = self.run_all()
        self.assertEqual(out[SLOT_A]['state'], 'done')
        self.assertEqual(self.result(SLOT_A)['account'], 'dana')
        self.assertEqual(self.inventory()['slots'][SLOT_A]['state'], 'retired')
        self.assertNotIn(SLOT_A, self.pool())
        self.assertFalse(self.exists(SLOT_A))
        for group_kind in [('Deployment', 'deployments'), ('Service', 'services'), ('PersistentVolumeClaim', 'claims'), ('Secret', 'secrets')]:
            for name in names(SLOT_A)[group_kind[1]]:
                self.assertIsNone(self.ctx.get(group_kind[0], name), name)
        for service_id in self.service_ids(SLOT_A):
            self.assertFalse((self.ctx.services / service_id).exists())
            self.assertFalse((self.root / 'inventory' / 'runtime-status' / service_id).exists())
        self.assertFalse((self.root / 'inventory' / 'runtime-tokens' / ident(SLOT_A)).exists())
        self.assertIn(('revoke', SLOT_A), self.ctx.calls)
        # Other slots are untouched, including their objects and files.
        for other in (SLOT_B, SLOT_BANK):
            self.assertTrue(self.exists(other))
            self.assertIn(other, self.pool())
            self.assertEqual(self.inventory()['slots'][other]['state'], 'ready')
            self.assertIsNotNone(self.ctx.get('Deployment', names(other)['deployments'][0]))
            self.assertTrue((self.ctx.services / self.service_ids(other)[0]).exists())

    def test_order_is_stop_then_revoke_then_objects_then_files(self):
        self.request(SLOT_A)
        self.run_all()
        kinds = [c[0] for c in self.ctx.calls]
        self.assertLess(kinds.index('scale'), kinds.index('revoke'))
        self.assertLess(kinds.index('revoke'), kinds.index('delete'))

    def test_protected_slot_is_refused_and_nothing_changes(self):
        self.request(SLOT_BANK)
        out = self.run_all()
        self.assertEqual(out[SLOT_BANK]['state'], 'refused')
        self.assertEqual(self.result(SLOT_BANK)['error'], 'Slot is protected')
        self.assertTrue(self.exists(SLOT_BANK))
        self.assertIn(SLOT_BANK, self.pool())
        self.assertEqual(self.inventory()['slots'][SLOT_BANK]['state'], 'ready')
        self.assertEqual(self.ctx.calls, [])

    def test_unassigned_unknown_and_malformed_requests_are_refused(self):
        (self.root / 'policy' / 'assignments.json').write_text(json.dumps({'assignedSlots': [SLOT_B], 'deletedSlots': [SLOT_B]}))
        self.request(SLOT_A)
        self.assertEqual(self.run_all()[SLOT_A]['error'], 'Slot is not held by a deleted account')
        unknown = 'cap-' + 'd' * 16 + '-01'
        self.request(unknown)
        self.assertEqual(self.run_all()[unknown]['error'], 'Slot is not a ready provisioned slot')
        self.request(SLOT_B, slot=SLOT_A)
        self.assertEqual(self.run_all()[SLOT_B]['error'], 'Retirement request is malformed')
        self.request(SLOT_B, user='Bad Name')
        os.remove(cr.result_path(self.root, SLOT_B))
        self.assertEqual(self.run_all()[SLOT_B]['error'], 'Retirement request is malformed')
        self.assertEqual(self.ctx.calls, [])
        self.assertTrue(self.exists(SLOT_A) and self.exists(SLOT_B))

    def test_a_live_accounts_slot_is_refused_even_with_a_request(self):
        # Assigned to an account, but the gateway does not list it as deleted: the account is alive.
        (self.root / 'policy' / 'assignments.json').write_text(json.dumps({'assignedSlots': [SLOT_A, SLOT_B], 'deletedSlots': [SLOT_B]}))
        self.request(SLOT_A)
        out = self.run_all()
        self.assertEqual((out[SLOT_A]['state'], out[SLOT_A]['error']), ('refused', 'Slot is not held by a deleted account'))
        self.assertTrue(self.exists(SLOT_A))
        self.assertIn(SLOT_A, self.pool())
        self.assertEqual(self.ctx.calls, [])

    def test_files_are_never_deleted_when_an_earlier_step_fails_and_the_slot_stays_out_of_the_pool(self):
        self.ctx.objects[('Secret', names(SLOT_A)['secrets'][0])] = {'metadata': {'labels': {}}}   # not owned
        self.request(SLOT_A)
        out = self.run_all()
        self.assertEqual(out[SLOT_A]['state'], 'quarantined')
        self.assertEqual(out[SLOT_A]['phase'], 'objects')
        self.assertEqual(out[SLOT_A]['error'], 'Object is not owned by the provisioner')
        self.assertTrue(self.exists(SLOT_A), 'files must survive a failed object step')
        self.assertNotIn(SLOT_A, self.pool(), 'a failed retirement must never leave the slot assignable')
        self.assertEqual(self.inventory()['slots'][SLOT_A]['state'], 'retiring')

    def test_pods_that_do_not_stop_quarantine_before_anything_is_deleted(self):
        self.ctx.stuck_pods = True
        self.request(SLOT_A)
        out = self.run_all()
        self.assertEqual((out[SLOT_A]['state'], out[SLOT_A]['phase'], out[SLOT_A]['error']), ('quarantined', 'stop', 'Runtime pods did not stop'))
        self.assertFalse([c for c in self.ctx.calls if c[0] == 'delete'])
        self.assertTrue(self.exists(SLOT_A))

    def test_credential_revocation_failure_quarantines_without_leaking_its_text(self):
        self.ctx.fail_keys = True
        self.request(SLOT_A)
        out = self.run_all()
        self.assertEqual((out[SLOT_A]['state'], out[SLOT_A]['phase']), ('quarantined', 'credentials'))
        self.assertNotIn('secret', json.dumps(self.result(SLOT_A)))
        self.assertFalse([c for c in self.ctx.calls if c[0] == 'delete'])
        self.assertTrue(self.exists(SLOT_A))

    def test_an_object_that_survives_deletion_quarantines(self):
        self.ctx.undeletable.add(('Service', names(SLOT_A)['services'][0]))
        self.request(SLOT_A)
        out = self.run_all()
        self.assertEqual((out[SLOT_A]['state'], out[SLOT_A]['error']), ('quarantined', 'Objects remain after deletion'))
        self.assertTrue(self.exists(SLOT_A))

    def test_links_are_removed_not_followed(self):
        outside = self.tmp / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('must survive')
        link = self.ctx.central / 'dsh' / 'private' / ident(SLOT_A) / 'secure' / 'escape'
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links are not available here')
        self.request(SLOT_A)
        self.assertEqual(self.run_all()[SLOT_A]['state'], 'done')
        self.assertEqual((outside / 'keep.txt').read_text(), 'must survive')
        self.assertFalse(self.exists(SLOT_A))

    def test_identity_directory_that_is_a_link_is_unlinked_only(self):
        outside = self.tmp / 'elsewhere'
        outside.mkdir()
        (outside / 'keep.txt').write_text('must survive')
        target = self.ctx.central / 'dsh' / 'private' / ident(SLOT_A)
        shutil.rmtree(target)
        try:
            os.symlink(outside, target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links are not available here')
        self.request(SLOT_A)
        self.assertEqual(self.run_all()[SLOT_A]['state'], 'done')
        self.assertEqual((outside / 'keep.txt').read_text(), 'must survive')

    def test_final_results_are_not_reprocessed_and_a_crashed_run_resumes(self):
        self.request(SLOT_A)
        self.run_all()
        self.ctx.calls.clear()
        self.assertEqual(self.run_all(), {})
        self.assertEqual(self.ctx.calls, [])
        # Simulated crash after the objects were deleted: the slot is retiring and out of the pool.
        self.request(SLOT_B)
        inventory = self.inventory()
        inventory['slots'][SLOT_B]['state'] = 'retiring'
        (self.root / 'inventory' / 'inventory.json').write_text(json.dumps(inventory))
        pool = self.pool()
        del pool[SLOT_B]
        (self.root / 'inventory' / 'pool.json').write_text(json.dumps({'slots': pool}))
        cr.write_result(self.root, SLOT_B, 'retiring', phase='files')
        self.assertEqual(self.run_all()[SLOT_B]['state'], 'done')
        self.assertFalse(self.exists(SLOT_B))

    def test_quarantined_slots_wait_for_an_operator(self):
        self.ctx.stuck_pods = True
        self.request(SLOT_A)
        self.run_all()
        self.ctx.stuck_pods = False
        self.ctx.calls.clear()
        self.assertEqual(self.run_all(), {})
        self.assertEqual(self.result(SLOT_A)['state'], 'quarantined')
        self.assertEqual(self.ctx.calls, [])

    def test_only_well_formed_request_names_are_considered(self):
        (self.root / 'policy' / 'retirements' / 'admin.json').write_text('{}')
        (self.root / 'policy' / 'retirements' / ('cap-' + 'a' * 16 + '-01.json.bak')).write_text('{}')
        (self.root / 'policy' / 'retirements' / 'cap-../x-01.json').parent.mkdir(exist_ok=True)
        self.assertEqual(self.run_all(), {})

    def test_the_banking_and_admin_directories_are_never_named_by_a_request(self):
        # remove_tree only accepts a plain identity-shaped name below its fixed parent.
        with self.assertRaises(cr.StepFailed):
            cr.remove_tree(self.ctx.central / 'dsh' / 'private', '../private')
        with self.assertRaises(cr.StepFailed):
            cr.remove_tree(self.ctx.central / 'dsh' / 'private', '8c6976e5b5410415/secure')
        self.assertTrue(self.exists(SLOT_BANK))


if __name__ == '__main__':
    unittest.main()
