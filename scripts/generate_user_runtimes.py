"""Generate reviewable per-user manifests. Does not apply or migrate any data.

Requires PyYAML. Example:
python scripts/generate_user_runtimes.py --users alice bob --image REGISTRY/IMAGE@sha256:DIGEST --output candidate.yaml
"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

import yaml


def generate(users, image):
    if not users or len(users) != len(set(users)):
        raise ValueError('Supply unique approved pilot identities')
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', image):
        raise ValueError('An immutable image digest is required')
    root = Path(__file__).resolve().parents[1]
    templates = list(yaml.safe_load_all((root / 'k8s/dsh-environment-pools.yaml').read_text()))
    deployments = {d['metadata']['name']: d for d in templates if d['kind'] == 'Deployment'}
    gateway = copy.deepcopy(next(d for d in yaml.safe_load_all(
        (root / 'k8s/dsh-environment-gateway.yaml').read_text()) if d['kind'] == 'Deployment'))
    container = gateway['spec']['template']['spec']['containers'][0]
    container['image'] = image
    container['env'] = [e for e in container['env'] if not e['name'].startswith(('DSH_OFFLINE_', 'DSH_ONLINE_'))]
    container['env'].append({'name': 'DSH_USER_TARGETS_FILE', 'value': '/routing/users.json'})
    container['volumeMounts'] = [m for m in container['volumeMounts'] if m['name'] == 'auth']
    pod = gateway['spec']['template']['spec']
    pod['automountServiceAccountToken'] = False
    pod['volumes'] = [v for v in pod['volumes'] if v['name'] == 'auth']
    container['volumeMounts'].append({'name': 'routing', 'mountPath': '/routing', 'readOnly': True})
    pod['volumes'].append({'name': 'routing', 'configMap': {'name': 'dsh-user-routing'}})
    documents, routes = [], {}
    for user in users:
        if not re.fullmatch(r'[a-z0-9_.-]{3,30}', user):
            raise ValueError('Invalid identity')
        identity = hashlib.sha256(user.encode()).hexdigest()[:16]
        routes[user] = {}
        for environment in ('secure', 'internet'):
            name = f'dsh-u-{identity}-{environment}'
            deployment = copy.deepcopy(deployments[f'dsh-{environment}'])
            deployment['metadata']['name'] = name
            deployment['spec']['selector']['matchLabels'] = {'app': name}
            runtime = deployment['spec']['template']
            runtime['metadata']['labels']['app'] = name
            runtime['metadata']['labels']['dsh.bot.or.th/owner'] = identity
            runtime['spec']['automountServiceAccountToken'] = False
            runtime['spec']['securityContext']['seccompProfile'] = {'type': 'RuntimeDefault'}
            runtime['spec']['containers'][0]['image'] = image
            for volume in runtime['spec']['volumes']:
                old = volume['persistentVolumeClaim']['claimName']
                if old == 'dsh-package-approved':
                    continue  # The only shared data volume; mounted read-only.
                claim = f'{name}-{volume["name"]}'
                volume['persistentVolumeClaim']['claimName'] = claim
                size = '100Mi' if volume['name'] == 'routing-tokens' else '5Gi'
                documents.append({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                    'metadata': {'name': claim, 'namespace': 'llm'},
                    'spec': {'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': size}}}})
                if volume['name'] == 'routing-tokens':
                    token_volume = f'token-{identity}-{environment}'
                    pod['volumes'].append({'name': token_volume, 'persistentVolumeClaim': {'claimName': claim}})
                    container['volumeMounts'].append({'name': token_volume,
                        'mountPath': f'/runtime-tokens/{identity}/{environment}', 'readOnly': True})
            documents.extend([deployment, {'apiVersion': 'v1', 'kind': 'Service',
                'metadata': {'name': name, 'namespace': 'llm'},
                'spec': {'selector': {'app': name}, 'ports': [{'name': 'web', 'port': 3081, 'targetPort': 'web'}]}}])
            routes[user][environment] = {'host': f'{name}.llm.svc.cluster.local', 'port': 3081,
                'tokenFile': f'/runtime-tokens/{identity}/{environment}/{environment}'}
    documents.extend([{'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': 'dsh-user-routing', 'namespace': 'llm'},
        'data': {'users.json': json.dumps(routes, indent=2)}}, gateway])
    return documents


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users', nargs='+', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(yaml.safe_dump_all(generate(args.users, args.image), sort_keys=False), encoding='utf-8')
