"""Bounded, non-destructive signup replenishment decisions; no cluster credentials."""
from datetime import datetime, timezone
import math


def plan(policy, assignments, inventory, resources, now=None):
    now = now or datetime.now(timezone.utc)
    required = {'version', 'enabled', 'maxAccounts', 'warmSpareSlots'}
    if set(policy) != required or policy['version'] != 1 or type(policy['enabled']) is not bool:
        raise ValueError('Invalid policy')
    maximum, spare = policy['maxAccounts'], policy['warmSpareSlots']
    if type(maximum) is not int or not 1 <= maximum <= 32 or type(spare) is not int or not 0 <= spare <= min(8, maximum):
        raise ValueError('Invalid capacity bounds')
    age = (now - datetime.fromisoformat(assignments['observedAt'].replace('Z', '+00:00'))).total_seconds()
    if age < -5 or age > 60:
        return {'action': 'wait', 'reason': 'assignment-state-stale'}
    count = assignments['registeredAccounts']
    used = assignments['assignedSlots']
    if type(count) is not int or count < 0 or count > 10000 or not isinstance(used, list) or len(set(used)) != len(used):
        raise ValueError('Invalid assignment projection')
    slots = inventory['slots']
    if not isinstance(slots, dict) or len(slots) > 32 or not set(used).issubset(slots):
        raise ValueError('Assigned inventory must never disappear')
    ready = sum(s.get('state') == 'ready' for name, s in slots.items() if name not in used)
    pending = sum(s.get('state') in ['preparing', 'qualifying'] for s in slots.values())
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
    if len(slots) >= 32:
        return {**base, 'action': 'wait', 'reason': 'inventory-limit'}
    for key in ['cpuAfterPair', 'memoryGiBAfterPair', 'podsAfterPair', 'storageGiBAfterPair']:
        value = resources.get(key)
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value < 0):
            return {**base, 'action': 'wait', 'reason': 'insufficient-or-unknown-' + key}
    return {**base, 'action': 'provision', 'count': 1, 'reason': 'replenish-one-private-pair'}
