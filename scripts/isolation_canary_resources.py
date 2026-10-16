"""Build a synthetic-only namespace from the real per-user deployment generator.

Does not apply resources, migrate users or access production histories.
"""
import copy
import hashlib
import json
import re
from pathlib import Path

import yaml
from generate_user_runtimes import generate

USERS = ('iso_alice', 'iso_bob')
DURABLE = ('sessions', 'attachments', 'storages', 'workspaces', 'logs')


def build(namespace, image):
    if not re.fullmatch(r'dsh-iso-[0-9]{8}-[0-9]{6}', namespace):
        raise ValueError('A new, explicitly bounded test namespace is required')
    prefix = 'dsh-isolation-tests/' + namespace
    claim = 'synthetic-central'
    documents = generate(list(USERS), image)
    for d in documents:
        d['metadata']['namespace'] = namespace
        d['metadata'].setdefault('labels', {})['dsh.bot.or.th/synthetic-test'] = namespace
        if d['kind'] == 'Deployment':
            pod = d['spec']['template']['spec']
            container = pod['containers'][0]
            # This disposable namespace tests synthetic storage and identity.
            # Production's datalake-aware DNS is tested separately on all workers.
            pod['dnsPolicy'] = 'ClusterFirst'
            pod.pop('dnsConfig', None)
            pod['volumes'] = [v for v in pod.get('volumes', []) if v['name'] != 'kerberos-config']
            container['volumeMounts'] = [v for v in container.get('volumeMounts', []) if v['name'] != 'kerberos-config']
            container['env'] = [e for e in container.get('env', []) if e['name'] != 'KRB5_CONFIG']
            for e in container.get('env', []):
                if e['name'] == 'DSH_TRUSTED_HOST':
                    e['value'] = 'dsh-isolation.test'
                if e['name'] == 'DEEPSEEK_API_KEY':
                    e['valueFrom']['secretKeyRef']['name'] = 'dsh-runtime-secrets'
            pod['volumes'].append({'name': 'test-scripts', 'configMap': {'name': 'canary-scripts'}})
            container['volumeMounts'].append({'name': 'test-scripts', 'mountPath': '/synthetic-tests', 'readOnly': True})
            if d['metadata']['name'] == 'dsh-environment-gateway':
                # Test the reviewed source overlay without restarting or
                # changing the existing Production gateway image/process.
                container['command'] = ['node', '/synthetic-tests/auth_proxy.js']
                container['env'].append({'name': 'DSH_COOKIE_NAME', 'value': 'dsh_isolation_test'})
                pod['securityContext'] = {'fsGroup': 10001, 'fsGroupChangePolicy': 'OnRootMismatch',
                                          'seccompProfile': {'type': 'RuntimeDefault'}}
                # Never reuse the Production auth claim or account store.
                for v in pod['volumes']:
                    if v['name'] == 'auth':
                        v['persistentVolumeClaim']['claimName'] = 'synthetic-auth'
                pod['volumes'].append({'name': 'test-identities', 'secret': {'secretName': 'synthetic-identities'}})
                container['volumeMounts'].append({'name': 'test-identities', 'mountPath': '/test-identities', 'readOnly': True})
                for e in container['env']:
                    if e['name'] == 'DSH_USER_STORE_PATH':
                        e['value'] = '/test-identities/users.json'
                continue
            owner = d['spec']['template']['metadata']['labels']['dsh.bot.or.th/owner']
            mode = next(e['value'] for e in container['env'] if e['name'] == 'DSH_ENVIRONMENT')
            container['env'].extend([
                {'name': 'CANARY_IDENTITY', 'value': owner},
                {'name': 'CANARY_ENVIRONMENT', 'value': mode},
            ])
            container['command'] = ['bash', '-c', 'python3 /synthetic-tests/report_server.py & exec /usr/local/bin/start-dsh']
            for v in pod['volumes']:
                if v['name'] == 'protected-workspace':
                    v['persistentVolumeClaim']['claimName'] = claim
                elif v['name'] == 'package-cache':
                    # Package installation is outside this canary's scope. An
                    # immutable empty fixture avoids sharing a Production cache
                    # or depending on a fresh read-only local disk's initialization.
                    v.pop('persistentVolumeClaim')
                    v['configMap'] = {'name': 'synthetic-approved-cache'}
            for m in container['volumeMounts']:
                if m['name'] == 'protected-workspace':
                    m['subPath'] = m['subPath'].replace('dsh/private/', prefix + '/private/', 1)
            if mode == 'secure':
                pod['volumes'].append({'name': 'synthetic-source', 'persistentVolumeClaim': {'claimName': 'synthetic-source', 'readOnly': True}})
                container['volumeMounts'].append({'name': 'synthetic-source', 'mountPath': '/data/synthetic-source', 'subPath': prefix + '/source', 'readOnly': True})
        elif d['kind'] == 'ConfigMap' and 'users.json' in d.get('data', {}):
            routes = json.loads(d['data']['users.json'])
            for targets in routes.values():
                for target in targets.values():
                    target['host'] = target['host'].replace('.llm.svc.', '.' + namespace + '.svc.')
            d['data']['users.json'] = json.dumps(routes, indent=2)

    def pvc(name, size):
        return {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                'metadata': {'name': name, 'namespace': namespace},
                'spec': {'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': size}}}}
    documents.extend([pvc('synthetic-auth', '100Mi'),
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'synthetic-approved-cache', 'namespace': namespace},
         'data': {'README.txt': 'Empty synthetic approved-cache fixture; package installation is not tested.'}}])
    pv = next(d for d in yaml.safe_load_all((Path(__file__).resolve().parents[1] / 'k8s/dsh-da-workspace.yaml').read_text()) if d['kind'] == 'PersistentVolume')
    pv = copy.deepcopy(pv)
    pv['metadata']['name'] = namespace + '-pv'
    pv['spec']['csi']['volumeHandle'] = namespace + '-synthetic-only'
    documents.extend([pv, {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
        'metadata': {'name': claim, 'namespace': namespace},
        'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '', 'volumeName': namespace + '-pv',
                 'resources': {'requests': {'storage': '10Gi'}}}}])
    # Distinct CSI identity for the read-only view: do not alias a writable
    # private workspace claim under a second, read-only pod volume name.
    reader = copy.deepcopy(pv)
    reader['metadata']['name'] = namespace + '-source-pv'
    reader['spec']['csi']['volumeHandle'] = namespace + '-synthetic-source-reader'
    documents.extend([reader, {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
        'metadata': {'name': 'synthetic-source', 'namespace': namespace},
        'spec': {'accessModes': ['ReadWriteMany'], 'storageClassName': '', 'volumeName': namespace + '-source-pv',
                 'resources': {'requests': {'storage': '10Gi'}}}}])
    policies = list(yaml.safe_load_all((Path(__file__).resolve().parents[1] / 'k8s/dsh-egress-policies.yaml').read_text()))
    for p in policies:
        p['metadata']['namespace'] = namespace
        if p['metadata']['name'] == 'dsh-offline-egress':
            # Synthetic acceptance namespace has no production datalake access.
            p['spec']['egress'] = [
                {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}},
                         'podSelector': {'matchLabels': {'k8s-app': 'kube-dns'}}}],
                 'ports': [{'protocol': 'UDP', 'port': 53}, {'protocol': 'TCP', 'port': 53}]},
                {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'llm'}},
                         'podSelector': {'matchLabels': {'app': 'litellm'}}}],
                 'ports': [{'protocol': 'TCP', 'port': 4000}]}]
    documents.extend(policies)
    validate(documents, namespace, prefix)
    return documents


def validate(documents, namespace, prefix):
    allowed_prefix = prefix + '/'
    for d in documents:
        if d['kind'] != 'PersistentVolume' and d['metadata'].get('namespace') != namespace:
            raise ValueError('Resource escapes the test namespace')
        if d['kind'] != 'Deployment':
            continue
        pod = d['spec']['template']['spec']
        if pod.get('automountServiceAccountToken') is not False:
            raise ValueError('No Kubernetes identity may be mounted into test workloads')
        for v in pod['volumes']:
            c = v.get('persistentVolumeClaim', {}).get('claimName', '')
            if c in {'dsh-auth-state', 'dsh-secure-state', 'dsh-internet-state', 'dsh-da-workspace-secure'}:
                raise ValueError('A Production claim must never be reused')
        for m in pod['containers'][0]['volumeMounts']:
            if m['name'] in {'protected-workspace', 'synthetic-source'} and not m.get('subPath', '').startswith(allowed_prefix):
                raise ValueError('A test runtime must never mount the legacy tree or share root')


def identity(user):
    return hashlib.sha256(user.encode()).hexdigest()[:16]
