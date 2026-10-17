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


def generate(users, image, fixture_source_pvc=None, fixture_approval_ref=None):
    if not users or len(users) != len(set(users)):
        raise ValueError('Supply unique approved pilot identities')
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', image):
        raise ValueError('An immutable image digest is required')
    if bool(fixture_source_pvc) != bool(fixture_approval_ref):
        raise ValueError('Read-only test fixture requires both a dedicated approved fixture PVC and owner approval reference')
    if fixture_source_pvc and (len(fixture_source_pvc) > 253 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', fixture_source_pvc)):
        raise ValueError('Invalid snapshot PVC name')
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
    # A private-user cutover must not revert the current hardened gateway and
    # admin dashboard to the older source baked into the pinned runtime image.
    gateway_source = (root / 'scripts/auth_proxy.js').read_text(encoding='utf-8')
    password_helper = (root / 'scripts/password_store.js').read_text(encoding='utf-8')
    source_hash = hashlib.sha256((gateway_source+password_helper).encode()).hexdigest()
    source_name = 'dsh-gateway-source-' + source_hash[:12]
    container['command'] = ['node', '/gateway-source/auth_proxy.js']
    container['volumeMounts'].append({'name': 'gateway-source', 'mountPath': '/gateway-source', 'readOnly': True})
    pod['volumes'].append({'name': 'gateway-source', 'configMap': {'name': source_name}})
    gateway['spec']['template']['metadata'].setdefault('annotations', {})['dsh.bot.or.th/gateway-source-sha256'] = source_hash
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
            # Private DSH frontends share GPU inference. Reserve lightweight
            # idle capacity without multiplying a full CPU per environment.
            runtime['spec']['containers'][0]['resources']['requests'] = {'cpu': '250m', 'memory': '1Gi'}
            for entry in runtime['spec']['containers'][0]['env']:
                if entry['name'] == 'DEEPSEEK_API_KEY':
                    entry['valueFrom']['secretKeyRef']['name'] = 'dsh-inference-u-' + identity
            for volume in runtime['spec']['volumes']:
                if 'persistentVolumeClaim' not in volume:
                    continue  # Read-only configuration is not a user data volume.
                old = volume['persistentVolumeClaim']['claimName']
                if old == 'dsh-package-approved':
                    continue  # Shared approved artifacts; mounted read-only.
                if environment == 'secure' and volume['name'] == 'protected-workspace':
                    if old != 'dsh-da-workspace-secure':
                        raise ValueError('Secure must preserve its central workspace claim')
                    for mount in runtime['spec']['containers'][0]['volumeMounts']:
                        if mount['name'] != 'protected-workspace':
                            continue
                        if mount['mountPath'] == '/workspace':
                            mount['subPath'] = f'dsh/private/{identity}/secure'
                        else:
                            directory = mount['mountPath'].removeprefix('/state/')
                            if directory not in {'sessions', 'attachments', 'storages', 'workspaces', 'logs'}:
                                raise ValueError('Unexpected central state mount')
                            mount['subPath'] = f'dsh/private/{identity}/state/{directory}'
                    # This shared PVC is bounded by a different bind-mount per
                    # identity; the main container never mounts its root.
                    continue
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
            # Optional filesystem fixture only. Real RDT uses Kerberos/Livy/HDFS permissions, not this mount.
            # Never mount a production root or broad shared source as the snapshot.
            if environment == 'secure' and fixture_source_pvc:
                runtime['metadata'].setdefault('annotations', {})['dsh.bot.or.th/fixture-approval'] = fixture_approval_ref
                runtime['spec']['volumes'].append({'name': 'readonly-fixture', 'persistentVolumeClaim': {
                    'claimName': fixture_source_pvc, 'readOnly': True}})
                runtime['spec']['containers'][0]['volumeMounts'].append({
                    'name': 'readonly-fixture', 'mountPath': '/data/fixtures', 'readOnly': True})
            documents.extend([deployment, {'apiVersion': 'v1', 'kind': 'Service',
                'metadata': {'name': name, 'namespace': 'llm'},
                'spec': {'clusterIP': 'None', 'selector': {'app': name}, 'ports': [
                    {'name': 'web', 'port': 3081, 'targetPort': 'web'},
                    {'name': 'terminal', 'port': 7681, 'targetPort': 'terminal'}]}}])
            routes[user][environment] = {'host': f'{name}.llm.svc.cluster.local', 'port': 3081,
                'tokenFile': f'/runtime-tokens/{identity}/{environment}/{environment}'}
    documents.extend([{'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': 'dsh-user-routing', 'namespace': 'llm'},
        'data': {'users.json': json.dumps(routes, indent=2)}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
         'metadata': {'name': source_name, 'namespace': 'llm'}, 'data': {'auth_proxy.js': gateway_source, 'password_store.js': password_helper}}, gateway])
    return documents


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--users', nargs='+', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--readonly-fixture-pvc', dest='fixture_source_pvc', help='Optional read-only filesystem test fixture; unrelated to Kerberos/datalake RDT access')
    parser.add_argument('--fixture-approval-ref', help='Operator approval reference for the synthetic filesystem fixture')
    args = parser.parse_args()
    args.output.write_text(yaml.safe_dump_all(generate(args.users, args.image, args.fixture_source_pvc, args.fixture_approval_ref), sort_keys=False), encoding='utf-8')
