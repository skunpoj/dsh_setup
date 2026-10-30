"""Reservation-based infrastructure ceiling; never an inference throughput promise."""
import math


def capacity_report(inputs, assignments, inventory):
    if not isinstance(inputs, dict):
        return None
    used = set(assignments['assignedSlots'])
    ready = sum(v.get('state') == 'ready' for k, v in inventory['slots'].items() if k not in used and v.get('state') != 'retired')
    rows = []
    for name in ['cpu', 'memoryGiB', 'pods', 'storageGiB']:
        v = inputs['resources'][name]
        if any(isinstance(v[k], bool) or not isinstance(v[k], (float, int)) or
               not math.isfinite(v[k]) or v[k] < 0 for k in ['available', 'reserve', 'pairBudget']):
            raise ValueError('Invalid capacity measurement')
        if v['pairBudget'] <= 0:
            raise ValueError('Missing private pair budget')
        remaining = max(0, v['available'] - v['reserve'])
        rows.append({'resource': name, **v, 'afterReserve': remaining,
                     'additionalPairs': max(0, math.floor((remaining + 1e-9) / v['pairBudget']))})
    from capacity_planner import ACTIVE_SLOTS_MAX, active_slots
    remaining_inventory = max(0, ACTIVE_SLOTS_MAX - len(active_slots(inventory['slots'])))
    added = min([r['additionalPairs'] for r in rows] + [remaining_inventory])
    registered = assignments['registeredAccounts']
    ceiling = min(ACTIVE_SLOTS_MAX, registered + ready + added)
    legacy = inputs.get('additionalDeployments', [])
    extra = sum(x['accounts'] for x in legacy)
    # Never infer missing external account counts as zero.
    complete = inputs.get('additionalDeploymentsComplete') is True
    return {'version': 1, 'basis': 'current reservations with protected headroom',
            'mainRegistered': registered, 'additionalAccounts': extra if complete else None,
            'totalRegistered': registered + extra if complete else None,
            'additionalDeployments': legacy, 'additionalDeploymentsComplete': complete,
            'readyPairs': ready, 'additionalPairsPossible': added,
            'mainPlanningCeiling': ceiling if complete else None,
            'totalPlanningCeiling': ceiling + extra if complete else None,
            'inventoryEntriesRemaining': remaining_inventory,
            'limitingResources': [r['resource'] for r in rows if r['additionalPairs'] == added] +
                                 (['inventory'] if remaining_inventory == added else []),
            'resources': rows, 'centralStorageFreeGiB': inputs.get('centralStorageFreeGiB'),
            'observedUsage': inputs.get('observedUsage'),
            'inferenceCapacityIncluded': False,
            'explanation': 'All cluster workloads, including additional DSH deployments, consume the available budget. Ready pairs are already reserved and counted once. Account counts do not guarantee simultaneous agent, notebook or 1M inference throughput.'}
