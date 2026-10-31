"""Render read-only gateway mounts and separate acceptance/live signup pools.

Input and output are private site artifacts. This command never enables signup;
only the separately verified gateway rollout may do that.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def build(pool, reserve, existing=None):
    slots = list(pool['slots'])
    old=(existing or {}).get('slots',{})
    if not 1 <= reserve <= len(slots) or (reserve == len(slots) and not old):
        raise ValueError('Reserve at least one acceptance-only pair and retain live capacity')
    if set(old)&set(slots):raise ValueError('Never replace or recycle an existing slot')
    config = {'test.json': json.dumps({'slots': {s: pool['slots'][s] for s in slots[:reserve]}}),
              'live.json': json.dumps({'slots': {**old,**{s: pool['slots'][s] for s in slots[reserve:]}}})}
    if existing:config['existing.json']=json.dumps(existing)
    name = 'dsh-signup-pool-' + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]
    document = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
        'metadata': {'name': name, 'namespace': 'llm'}, 'data': config}
    volumes = [{'name': 'signup-config', 'configMap': {'name': name}}]
    mounts = [{'name': 'signup-config', 'mountPath': '/signup-pool', 'readOnly': True}]
    for slot, targets in {**old,**pool['slots']}.items():
        identity = hashlib.sha256(slot.encode()).hexdigest()[:16]
        for environment, target in targets.items():
            vname = 'signup-' + identity + '-' + environment
            volumes.append({'name': vname, 'persistentVolumeClaim': {'claimName': target['host'].split('.')[0] + '-routing-tokens'}})
            mounts.append({'name': vname, 'mountPath': '/runtime-tokens/signup/' + identity + '/' + environment, 'readOnly': True})
    reserved = {hashlib.sha256(s.encode()).hexdigest()[:16] for s in slots[:reserve]}
    stage = {'registrationEnabled': False, 'poolFile': '/signup-pool/existing.json' if existing else None, 'volumes': volumes, 'mounts': mounts}
    live = {'registrationEnabled': True, 'poolFile': '/signup-pool/live.json',
        'volumes': [v for v in volumes if not any(i in v['name'] for i in reserved)],
        'mounts': [m for m in mounts if not any(i in m['name'] for i in reserved)]}
    return document, stage, live


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pool', type=Path, required=True)
    ap.add_argument('--reserve-test-pairs', type=int, default=2)
    ap.add_argument('--existing-live', type=Path, help='Preserve every previously published slot during replenishment')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--apply-configmap', action='store_true')
    ap.add_argument('--kubectl', default='kubectl')
    a = ap.parse_args();a.output.mkdir(parents=True, exist_ok=False)
    document, stage, live = build(json.loads(a.pool.read_text()), a.reserve_test_pairs, json.loads(a.existing_live.read_text()) if a.existing_live else None)
    for name, value in [('configmap.private.json', document), ('stage-gateway.private.json', stage), ('live-gateway.private.json', live)]:
        (a.output/name).write_text(json.dumps(value, indent=2))
    (a.output/'live-pool.private.json').write_text(document['data']['live.json'])
    if a.apply_configmap:
        subprocess.run([a.kubectl, '-n', 'llm', '--request-timeout=30s', 'apply', '-f', '-'], input=json.dumps(document), text=True, check=True, capture_output=True, timeout=60)
    print(json.dumps({'configPrepared': True, 'registrationEnabledByThisCommand': False,
        'testPairs': a.reserve_test_pairs, 'livePairs': len(json.loads(document['data']['live.json'])['slots'])}))
