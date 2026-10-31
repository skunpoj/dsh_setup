"""First-come, first-reserved private runtimes: start on demand, stop when idle.

Pure decisions only. The gateway publishes which private runtime Deployments its
signed-in users are using; the controller applies the bounded scale changes.
Nothing here deletes a workload, claim, credential, file or history. A stopped
runtime keeps all private storage and resumes where the user left off.
"""
from datetime import datetime, timezone
import math
import re

RUNTIME = re.compile(r'dsh-u-[0-9a-f]{16}-(secure|internet)')
MAX_STARTS_PER_ROUND = 4
DEMAND_STALE_SECONDS = 60


def parse_time(value):
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('Timezone required')
    return moment


def runtime_units(resources):
    """Single-runtime starts that fit now, after protected headroom.

    A pair budget covers both environments. Users run one environment at a
    time, so one start needs half a pair. Unknown measurements start nothing.
    """
    try:
        rows = resources['capacityInputs']['resources']
        units = []
        for name in ['cpu', 'memoryGiB', 'pods', 'storageGiB']:
            row = rows[name]
            values = [row[k] for k in ['available', 'reserve', 'pairBudget']]
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in values):
                return 0
            if row['pairBudget'] <= 0:
                return 0
            # Storage is already claimed by every provisioned runtime; starting
            # one does not create new claims, so disk never blocks a start.
            if name == 'storageGiB':
                continue
            units.append(math.floor((max(0, row['available'] - row['reserve']) + 1e-9) / (row['pairBudget'] / 2)))
        return max(0, min(units))
    except (KeyError, TypeError):
        return 0


def session_plan(demand, runtimes, units, now, idle_timeout, keep_warm=()):
    """Return bounded starts, idle stops and every runtime's visible state.

    keep_warm: unassigned spare runtimes held running so the next new sign-in
    lands on a Ready workspace. They are never idle-stopped and are started only
    with start budget left after every signed-in user.

    demand: gateway projection {'observedAt', 'runtimes': {name: {'requestedAt', 'lastActivityAt'}}}
    runtimes: {name: {'replicas': int, 'ready': int}} for private runtime Deployments.
    """
    if not isinstance(idle_timeout, int) or not 300 <= idle_timeout <= 86400:
        raise ValueError('Idle timeout must be 5 minutes to 24 hours')
    for name, value in runtimes.items():
        if not RUNTIME.fullmatch(name) or not isinstance(value.get('replicas'), int) or value['replicas'] < 0:
            raise ValueError('Unexpected runtime')
    fresh = False
    wanted = {}
    try:
        age = (now - parse_time(demand['observedAt'])).total_seconds()
        fresh = -5 <= age <= DEMAND_STALE_SECONDS
        for name, entry in demand.get('runtimes', {}).items():
            if name not in runtimes:
                continue
            requested, active = parse_time(entry['requestedAt']), parse_time(entry['lastActivityAt'])
            if (now - active).total_seconds() <= idle_timeout:
                wanted[name] = requested
    except (KeyError, TypeError, ValueError, AttributeError):
        fresh = False
    keep_warm = [n for n in keep_warm if n in runtimes and n not in wanted]
    states, starts, stops = {}, [], []
    # A missing or stale gateway report never stops a user's runtime; it only
    # prevents new starts until the gateway reports demand again.
    for name, value in sorted(runtimes.items()):
        if value['replicas'] >= 1:
            if fresh and name not in wanted and name not in keep_warm:
                stops.append(name)
                states[name] = {'state': 'stopping'}
            else:
                states[name] = {'state': 'running' if value.get('ready', 0) >= 1 else 'starting'}
            if name in keep_warm:
                states[name]['warm'] = True
        else:
            states[name] = {'state': 'stopped'}
    if fresh:
        queue = sorted((t, n) for n, t in wanted.items() if runtimes[n]['replicas'] == 0)
        budget = min(units, MAX_STARTS_PER_ROUND)
        for position, (_, name) in enumerate(queue, start=1):
            if budget > 0:
                starts.append(name)
                budget -= 1
                states[name] = {'state': 'starting'}
            else:
                states[name] = {'state': 'waiting', 'position': position - len(starts)}
        for name in keep_warm:
            if runtimes[name]['replicas'] == 0 and budget > 0:
                starts.append(name)
                budget -= 1
                states[name] = {'state': 'starting', 'warm': True}
    summary = {'running': sum(s['state'] == 'running' for s in states.values()),
               'starting': sum(s['state'] == 'starting' for s in states.values()),
               'waiting': sum(s['state'] == 'waiting' for s in states.values()),
               'stopped': sum(s['state'] in ['stopped', 'stopping'] for s in states.values()),
               'startsAvailable': max(0, units - len(starts)),
               'warm': sum(1 for s in states.values() if s.get('warm')),
               'idleTimeoutSeconds': idle_timeout, 'demandFresh': fresh}
    return {'scaleUp': starts, 'scaleDown': stops, 'runtimes': states, 'summary': summary}


STAGES = ['queued', 'scheduling', 'preparing', 'pulling-image', 'starting-containers', 'starting-dsh', 'ready']
STAGE_PERCENT = {'queued': 5, 'scheduling': 15, 'preparing': 35, 'pulling-image': 45,
                 'starting-containers': 65, 'starting-dsh': 85, 'ready': 100}
FAILED_REASONS = {'ErrImagePull', 'ImagePullBackOff', 'CrashLoopBackOff', 'CreateContainerConfigError',
                  'CreateContainerError', 'InvalidImageName', 'RunContainerError'}


def pod_progress(pods):
    """Spawn progress from a runtime's pods, JupyterHub style: stage and percent.

    Uses only pod phase, conditions and container states; no logs or events.
    """
    live = [p for p in pods or [] if not p.get('metadata', {}).get('deletionTimestamp')]
    if not live:
        return {'stage': 'scheduling', 'percent': 10, 'detail': 'Creating the workspace pod'}
    pod = sorted(live, key=lambda p: p['metadata'].get('creationTimestamp', ''))[-1]
    status = pod.get('status', {})
    conditions = {c.get('type'): c for c in status.get('conditions', [])}
    containers = status.get('initContainerStatuses', []) + status.get('containerStatuses', [])
    for c in containers:
        reason = (c.get('state', {}).get('waiting') or {}).get('reason', '')
        if reason in FAILED_REASONS:
            return {'stage': 'failed', 'percent': STAGE_PERCENT['starting-containers'], 'detail': reason}
    if conditions.get('PodScheduled', {}).get('status') != 'True':
        reason = conditions.get('PodScheduled', {}).get('reason', '')
        return {'stage': 'scheduling', 'percent': STAGE_PERCENT['scheduling'],
                'detail': 'Waiting for node capacity' if reason == 'Unschedulable' else 'Placing the workspace on the node'}
    if conditions.get('Ready', {}).get('status') == 'True':
        return {'stage': 'ready', 'percent': 100, 'detail': 'Workspace is ready'}
    waiting = [(c.get('state', {}).get('waiting') or {}).get('reason', '') for c in containers]
    if conditions.get('Initialized', {}).get('status') != 'True':
        if any(w == 'ContainerCreating' for w in waiting) and not status.get('initContainerStatuses'):
            return {'stage': 'pulling-image', 'percent': STAGE_PERCENT['pulling-image'], 'detail': 'Loading the workspace image'}
        return {'stage': 'preparing', 'percent': STAGE_PERCENT['preparing'], 'detail': 'Mounting your files and preparing settings'}
    regular = status.get('containerStatuses', [])
    if not regular or any((c.get('state', {}).get('waiting') or {}).get('reason') in ('ContainerCreating', 'PodInitializing') for c in regular):
        return {'stage': 'pulling-image', 'percent': STAGE_PERCENT['pulling-image'], 'detail': 'Loading the workspace image'}
    if not all('running' in c.get('state', {}) for c in regular):
        return {'stage': 'starting-containers', 'percent': STAGE_PERCENT['starting-containers'], 'detail': 'Starting workspace processes'}
    return {'stage': 'starting-dsh', 'percent': STAGE_PERCENT['starting-dsh'], 'detail': 'Starting DSH and checking it responds'}


def utc():
    return datetime.now(timezone.utc).isoformat()
