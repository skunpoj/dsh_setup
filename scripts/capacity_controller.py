"""Single-writer automatic capacity reconciler, separate from the login gateway.

Only an operator-installed immutable worker creates infrastructure. Dashboard
policy supplies bounded integers and an enable flag, never commands or images.
Existing accounts, assigned workloads, files and histories are never removed.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import stat
import time

from capacity_planner import plan


def read_json(path, limit=262144):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
            raise ValueError('Invalid capacity input')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            value = stream.read(limit + 1)
        if len(value) > limit:
            raise ValueError('Capacity input exceeded bound')
        return json.loads(value)
    finally:
        os.close(fd)


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name('.' + path.name + '.' + secrets.token_hex(6))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def read_config(path, limit=262144):
    # Immutable Kubernetes ConfigMaps use kubelet-managed symlink generations.
    # Resolve only inside the dedicated read-only config mount; mutable policy,
    # inventory and worker status retain descriptor-level no-symlink reads.
    root=Path('/capacity-source').resolve()
    resolved=Path(path).resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('ConfigMap path escaped its read-only mount')
    return read_json(resolved,limit)


def reconcile(root, worker):
    root = Path(root)
    policy = read_json(root / 'policy' / 'policy.json')
    assignments = read_json(root / 'policy' / 'assignments.json')
    inventory = read_json(root / 'inventory' / 'inventory.json')
    # Recover a crash between the durable qualification receipt and route
    # publication. Never re-run empty-history checks after a slot is allocated.
    published = read_json(root / 'inventory' / 'pool.json')
    changed=False
    for name,record in inventory['slots'].items():
        if record.get('state')!='ready' or record.get('qualification',{}).get('status')!='passed':
            continue
        if name in published['slots']:
            if published['slots'][name]!=record['routes']:
                raise RuntimeError('Published private route differs from its receipt')
        else:
            published['slots'][name]=record['routes'];changed=True
    if changed:
        atomic_json(root / 'inventory' / 'pool.json',published)
    resources = worker.resources()
    decision = plan(policy, assignments, inventory, resources)
    from capacity_report import capacity_report
    report = capacity_report(resources.get('capacityInputs'), assignments, inventory)
    if report is not None:
        decision['capacity'] = report
    if decision['action'] == 'provision':
        slot = 'cap-' + secrets.token_hex(8) + '-01'
        inventory['slots'][slot] = {'state': 'preparing', 'createdAt': utc()}
        atomic_json(root / 'inventory' / 'inventory.json', inventory)
    elif decision['action'] == 'resume':
        slot = next(name for name, record in inventory['slots'].items() if record['state'] in ['preparing', 'qualifying'])
    else:
        return decision
    # The worker is idempotent by slot identity. A failed qualification never
    # publishes a destination or permits another slot to hide the failure.
    routes, receipt = worker.prepare_and_qualify(slot)
    if receipt.get('status') != 'passed' or set(routes) != {'secure', 'internet'}:
        raise RuntimeError('New private pair failed qualification')
    inventory = read_json(root / 'inventory' / 'inventory.json')
    inventory['slots'][slot].update(state='ready', routes=routes, qualification=receipt, qualifiedAt=utc())
    atomic_json(root / 'inventory' / 'inventory.json', inventory)
    # Gateway reads this append-only route inventory dynamically. Old slots
    # remain present even when disabled or above the new desired spare count.
    published = read_json(root / 'inventory' / 'pool.json')
    if slot in published['slots'] and published['slots'][slot] != routes:
        raise RuntimeError('Refusing to replace a published private route')
    published['slots'][slot] = routes
    atomic_json(root / 'inventory' / 'pool.json', published)
    return {**decision, 'action': 'published', 'slot': slot, 'qualification': receipt}


def sessions(root, worker, idle_timeout):
    """Start demanded private runtimes first come, first served; stop idle ones.

    Runs every round, separately from provisioning, so a paused provisioner
    never blocks sign-in starts or idle release. Storage is never touched.
    """
    from capacity_session import runtime_units, session_plan
    root = Path(root)
    try:
        demand = read_json(root / 'policy' / 'demand.json')
    except (OSError, ValueError):
        demand = {}
    runtimes = worker.runtimes()
    # A pair still being prepared or qualified must stay up until its receipt.
    import hashlib
    try:
        inventory = read_json(root / 'inventory' / 'inventory.json')
        for slot, record in inventory['slots'].items():
            if record.get('state') in ['preparing', 'qualifying']:
                identity = hashlib.sha256(slot.encode()).hexdigest()[:16]
                for env in ['secure', 'internet']:
                    runtimes.pop('dsh-u-' + identity + '-' + env, None)
    except (OSError, ValueError, KeyError):
        return {'starting': 0, 'waiting': 0}
    decision = session_plan(demand, runtimes, runtime_units(worker.resources()), datetime.now(timezone.utc), idle_timeout)
    for name in decision['scaleDown']:
        worker.kube.scale(name, 0)
    for name in decision['scaleUp']:
        worker.kube.scale(name, 1)
    # Spawn progress for the sign-in waiting page: queued users see their
    # position; starting runtimes report the pod's current stage and percent.
    from capacity_session import pod_progress, STAGE_PERCENT
    for name, state in decision['runtimes'].items():
        if state['state'] == 'waiting':
            state['progress'] = {'stage': 'queued', 'percent': STAGE_PERCENT['queued'], 'detail': 'Waiting for shared resources'}
        elif state['state'] == 'starting':
            try:
                state['progress'] = pod_progress(worker.kube.call('GET', 'Pod', selector='app=' + name)['items'])
            except (RuntimeError, KeyError, TypeError):
                state['progress'] = {'stage': 'scheduling', 'percent': 10, 'detail': 'Starting your workspace'}
    atomic_json(root / 'inventory' / 'sessions.json', {'version': 1, 'observedAt': utc(), 'available': True,
        'runtimes': decision['runtimes'], 'summary': decision['summary']})
    return decision['summary']


def utc():
    return datetime.now(timezone.utc).isoformat()


def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='/capacity')
    parser.add_argument('--config', default='/capacity-source/site.json')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    root = Path(args.root)
    from capacity_worker import Worker
    config = read_config(args.config)
    worker = Worker(config, root)
    idle_timeout = config.get('sessionIdleTimeoutSeconds', 3600)
    with (root / 'inventory' / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        delay=15
        while True:
            busy = False
            try:
                summary = sessions(root, worker, idle_timeout)
                busy = summary['starting'] > 0 or summary['waiting'] > 0
            except Exception as error:
                atomic_json(root / 'inventory' / 'sessions.json', {'version': 1, 'observedAt': utc(), 'available': False,
                    'reason': type(error).__name__})
            try:
                result = reconcile(root, worker)
                delay=15
                atomic_json(root / 'inventory' / 'status.json', {'observedAt': utc(), 'available': True, **result})
            except Exception as error:
                # Avoid credentials, site data and API response bodies in logs.
                atomic_json(root / 'inventory' / 'status.json', {'observedAt': utc(), 'available': False,
                    'action': 'paused', 'reason': type(error).__name__, 'stage':getattr(worker,'phase','initialization')})
                delay=min(300,delay*2)
                if args.once:
                    raise SystemExit('Capacity reconciliation paused: ' + type(error).__name__)
            if args.once:
                break
            # Someone is waiting for a cold start: check again quickly.
            time.sleep(5 if busy else delay)


if __name__ == '__main__':
    main()
