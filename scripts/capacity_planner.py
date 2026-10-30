"""Bounded, non-destructive signup replenishment decisions; no cluster credentials.

Accounts no longer reserve compute: a ready spare is a stopped private pair
(storage only), started at sign-in only when resources allow. Retired slots
are kept for audit but never count against the active inventory.
"""
from datetime import datetime, timezone
import math

ACCOUNT_LIMIT_MAX = 100000      # effectively unlimited; admission happens at sign-in
ACTIVE_SLOTS_MAX = 200          # bounded by the inventory file size
INVENTORY_ENTRIES_MAX = 400


def active_slots(slots):
    return {name: s for name, s in slots.items() if s.get('state') != 'retired'}


def plan(policy, assignments, inventory, resources, now=None):
    now = now or datetime.now(timezone.utc)
    required = {'version', 'enabled', 'maxAccounts', 'warmSpareSlots'}
    if set(policy) != required or policy['version'] != 1 or type(policy['enabled']) is not bool:
        raise ValueError('Invalid policy')
    maximum, spare = policy['maxAccounts'], policy['warmSpareSlots']
    if type(maximum) is not int or not 1 <= maximum <= ACCOUNT_LIMIT_MAX or type(spare) is not int or not 0 <= spare <= min(8, maximum):
        raise ValueError('Invalid capacity bounds')
    age = (now - datetime.fromisoformat(assignments['observedAt'].replace('Z', '+00:00'))).total_seconds()
    if age < -5 or age > 60:
        return {'action': 'wait', 'reason': 'assignment-state-stale'}
    count = assignments['registeredAccounts']
    used = assignments['assignedSlots']
    if type(count) is not int or count < 0 or count > 10000 or not isinstance(used, list) or len(set(used)) != len(used):
        raise ValueError('Invalid assignment projection')
    slots = inventory['slots']
    if not isinstance(slots, dict) or len(slots) > INVENTORY_ENTRIES_MAX or not set(used).issubset(slots):
        raise ValueError('Assigned inventory must never disappear')
    active = active_slots(slots)
    ready = sum(s.get('state') == 'ready' for name, s in active.items() if name not in used)
    pending = sum(s.get('state') in ['preparing', 'qualifying'] for s in active.values())
    desired = max(0, min(spare, maximum - count))
    base = {'readySpares': ready, 'pendingSlots': pending, 'desiredSpares': desired,
            'registeredAccounts': count, 'maxAccounts': maximum,
            'existingSlotsToDelete': []}
    if not policy['enabled']:
        return {**base, 'action': 'wait', 'reason': 'automatic-provisioning-disabled'}
    if pending:
        return {**base, 'action': 'resume', 'reason': 'finish-existing-slot-before-creating-another'}
    if ready >= desired:
        return {**base, 'action': 'wait', 'reason': 'spare-target-satisfied'}
    if len(active) >= ACTIVE_SLOTS_MAX or len(slots) >= INVENTORY_ENTRIES_MAX:
        return {**base, 'action': 'wait', 'reason': 'inventory-limit'}
    # A spare is stopped after qualification, so only storage is committed
    # long term; qualification itself still needs a brief compute start.
    for key in ['cpuAfterPair', 'memoryGiBAfterPair', 'podsAfterPair', 'storageGiBAfterPair']:
        value = resources.get(key)
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value < 0):
            return {**base, 'action': 'wait', 'reason': 'insufficient-or-unknown-' + key}
    return {**base, 'action': 'provision', 'count': 1, 'reason': 'replenish-one-private-pair'}
