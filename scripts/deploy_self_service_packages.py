"""Render package jobs/controller plus a preserving gateway overlay.

Uses a dedicated trusted queue/PVC; user runtimes are never restarted or given
Kubernetes permissions. Apply only after synthetic live acceptance.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from gateway_sources import gateway_sources, gateway_sources_sha256, gateway_configmap_items
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def resources(gateway, source, namespace, storage_class, prefix='dsh-packages'):
    if not re.fullmatch('[a-z0-9-]{3,40}', prefix):
        raise ValueError('Invalid resource prefix')
    image = gateway['spec']['template']['spec']['containers'][0]['image']
    source = copy.deepcopy(source)
    source['metadata'] = {'name': prefix + '-source-' + hashlib.sha256(json.dumps(source['data'], sort_keys=True).encode()).hexdigest()[:12]}
    source.pop('status', None); source['immutable'] = True
    queue = prefix + '-queue'
    config = {'namespace': namespace, 'queuePVC': queue, 'sourceConfigMap': source['metadata']['name'],
              'runtimeImage': image, 'storageClass': storage_class,
              'imagePullSecrets': gateway['spec']['template']['spec'].get('imagePullSecrets', [])}
    site = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
            'metadata': {'name': prefix + '-site-' + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]},
            'data': {'site.json': json.dumps(config)}}
    context = {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001,
               'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
               'capabilities': {'drop': ['ALL']}, 'seccompProfile': {'type': 'RuntimeDefault'}}
    controller = {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': prefix + '-controller'},
        'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': {'app': prefix + '-controller'}},
          'template': {'metadata': {'labels': {'app': prefix + '-controller'}}, 'spec': {
            'serviceAccountName': prefix + '-controller', 'securityContext': {'fsGroup': 10001},
            'imagePullSecrets': config['imagePullSecrets'], 'volumes': [
                {'name': 'source', 'configMap': {'name': source['metadata']['name']}},
                {'name': 'site', 'configMap': {'name': site['metadata']['name']}},
                {'name': 'queue', 'persistentVolumeClaim': {'claimName': queue}}],
            'containers': [{'name': 'controller', 'image': image, 'command': ['python3', '/controller/package_controller.py'],
                'securityContext': context, 'env': [{'name': 'PYTHONDONTWRITEBYTECODE', 'value': '1'},
                    {'name': 'POD_UID', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.uid'}}}],
                'readinessProbe': {'exec': {'command': ['python3', '-c',
                    "import json,os,time,datetime;from pathlib import Path;p=Path('/packages-control/controller-status.json');v=json.loads(p.read_text());assert v.get('available') is True and v.get('instance')==os.environ['POD_UID'] and time.time()-datetime.datetime.fromisoformat(v['observedAt']).timestamp()<15"]},
                    'periodSeconds': 5, 'timeoutSeconds': 2},
                'resources': {'requests': {'cpu': '25m', 'memory': '64Mi'}, 'limits': {'cpu': '500m', 'memory': '256Mi'}},
                'volumeMounts': [{'name': 'source', 'mountPath': '/controller', 'readOnly': True},
                    {'name': 'site', 'mountPath': '/site', 'readOnly': True}, {'name': 'queue', 'mountPath': '/packages-control'}]}]}}}}
    spec = copy.deepcopy(gateway['spec'])
    pod = spec['template']['spec']; main = pod['containers'][0]
    if any(v['name'] == 'package-control' for v in pod['volumes']):
        raise ValueError('Already installed; use a reviewed explicit upgrade')
    pod['volumes'].append({'name': 'package-control', 'persistentVolumeClaim': {'claimName': queue}})
    main['volumeMounts'].append({'name': 'package-control', 'mountPath': '/packages-control'})
    main['env'] = [e for e in main['env'] if e['name'] != 'DSH_PACKAGES_ROOT'] + [{'name': 'DSH_PACKAGES_ROOT', 'value': '/packages-control'}]
    next(v for v in pod['volumes'] if v['name'] == 'gateway-source')['configMap']['name'] = source['metadata']['name']
    next(v for v in pod['volumes'] if v['name'] == 'gateway-source')['configMap']['items'] = gateway_configmap_items(source['data'])
    # Initialize only the NEW queue volume separately. Never add fsGroup to
    # an existing gateway: kubelet could chmod its protected account volume.
    documents = [source, site, {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': queue},
        'spec': {'storageClassName': storage_class, 'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '100Mi'}}}},
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': prefix + '-controller'}},
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'Role', 'metadata': {'name': prefix + '-controller'}, 'rules': [
            {'apiGroups': ['apps'], 'resources': ['deployments'], 'verbs': ['get']},
            {'apiGroups': ['batch'], 'resources': ['jobs'], 'verbs': ['get', 'create', 'delete']},
            {'apiGroups': [''], 'resources': ['persistentvolumeclaims'], 'verbs': ['get', 'create']}]},
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding', 'metadata': {'name': prefix + '-controller'},
         'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': prefix + '-controller'},
         'subjects': [{'kind': 'ServiceAccount', 'name': prefix + '-controller', 'namespace': namespace}]}, controller,
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'dsh-package-install-no-network'},
         'spec': {'podSelector': {'matchLabels': {'app': 'dsh-package-install'}}, 'policyTypes': ['Ingress', 'Egress'], 'ingress': [], 'egress': []}},
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'dsh-package-download-public-only'},
         'spec': {'podSelector': {'matchLabels': {'app': 'dsh-package-download'}}, 'policyTypes': ['Ingress', 'Egress'], 'ingress': [], 'egress': [
             {'to': [{'ipBlock': {'cidr': '0.0.0.0/0', 'except': ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '127.0.0.0/8', '169.254.0.0/16']}}], 'ports': [{'protocol': 'TCP', 'port': 443}]},
             {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}}, 'podSelector': {'matchLabels': {'k8s-app': 'kube-dns'}}}], 'ports': [{'protocol': 'UDP', 'port': 53}, {'protocol': 'TCP', 'port': 53}]}]}}]
    documents.append({'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': prefix + '-queue-init'},
        'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 120, 'template': {
            'metadata': {'labels': {'app': 'dsh-package-install'}}, 'spec': {
                'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                'imagePullSecrets': config['imagePullSecrets'],
                'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'fsGroup': 10001, 'fsGroupChangePolicy': 'OnRootMismatch'},
                'containers': [{'name': 'initialize', 'image': image, 'securityContext': context,
                    'command': ['python3', '-c', "from pathlib import Path;p=Path('/queue/jobs');p.mkdir(exist_ok=True);p.chmod(0o2770)"],
                    'volumeMounts': [{'name': 'queue', 'mountPath': '/queue'}]}],
                'volumes': [{'name': 'queue', 'persistentVolumeClaim': {'claimName': queue}}]}}}})
    return documents, spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway', default='dsh-environment-gateway'); parser.add_argument('--namespace', default='llm')
    parser.add_argument('--storage-class', required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prefix', default='dsh-packages'); parser.add_argument('--kubectl', default='kubectl')
    parser.add_argument('--apply', action='store_true'); parser.add_argument('--acceptance', type=Path)
    args = parser.parse_args()
    def k(*a, data=None):
        p = subprocess.run([args.kubectl, '-n', args.namespace, *a], input=data, capture_output=True, text=True, encoding='utf-8', timeout=180)
        if p.returncode: raise RuntimeError(p.stderr[-500:])
        return p.stdout
    gateway = json.loads(k('get', 'deployment', args.gateway, '-o', 'json'))
    cm = next(v['configMap']['name'] for v in gateway['spec']['template']['spec']['volumes'] if v['name'] == 'gateway-source')
    source = json.loads(k('get', 'configmap', cm, '-o', 'json'))
    files = {'auth_proxy.js': 'scripts/auth_proxy.js', 'package_portal.js': 'scripts/package_portal.js',
        'package_task.py': 'container/package_task.py', 'package_controller.py': 'scripts/package_controller.py',
        'capacity_kube.py': 'scripts/capacity_kube.py', 'capacity_controller.py': 'scripts/capacity_controller.py', 'capacity_planner.py': 'scripts/capacity_planner.py'}
    for key, name in files.items(): source['data'][key] = (ROOT / name).read_text(encoding='utf-8')
    source['data'].update(gateway_sources(ROOT))
    documents, spec = resources(gateway, source, args.namespace, args.storage_class, args.prefix)
    # Isolate the trusted controller to the Kubernetes API endpoints only.
    api = json.loads(k('get', 'service', 'kubernetes', '-n', 'default', '-o', 'json'))
    endpoints = json.loads(k('get', 'endpoints', 'kubernetes', '-n', 'default', '-o', 'json'))
    addresses = [api['spec']['clusterIP']] + [v['ip'] for s in endpoints.get('subsets', []) for v in s.get('addresses', [])]
    documents.append({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': args.prefix + '-controller'},
        'spec': {'podSelector': {'matchLabels': {'app': args.prefix + '-controller'}}, 'policyTypes': ['Ingress', 'Egress'], 'ingress': [],
                 'egress': [{'to': [{'ipBlock': {'cidr': ip + '/32'}}], 'ports': [{'protocol': 'TCP', 'port': p} for p in [443, 6443]]} for ip in addresses]}})
    args.output.mkdir(parents=True, exist_ok=False)
    fingerprint = hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest()
    feature_hash = hashlib.sha256(json.dumps({k: source['data'][k] for k in
        ['auth_proxy.js', 'package_portal.js', 'package_controller.py', 'package_task.py']}, sort_keys=True).encode()).hexdigest()
    (args.output / 'gateway-before.private.json').write_text(json.dumps(gateway))
    (args.output / 'gateway-spec.private.json').write_text(json.dumps(spec))
    (args.output / 'resources.private.json').write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': documents}))
    (args.output / 'fingerprint.json').write_text(json.dumps({'fingerprint': fingerprint, 'featureSourceSHA256': feature_hash,
        'sourceHash': hashlib.sha256(json.dumps(documents[0]['data'], sort_keys=True).encode()).hexdigest()}))
    if args.apply:
        acceptance = json.loads(args.acceptance.read_text()) if args.acceptance else {}
        expected_image = json.loads(documents[1]['data']['site.json'])['runtimeImage']
        required = ['twoUserIsolationPassed', 'wheelInstallationPassed', 'installerNetworkDenied',
                    'tamperDenied', 'revokeDenied', 'persistencePassed', 'jupyterKernelPassed', 'cifsInstallationPassed']
        if (acceptance.get('status') != 'passed' or acceptance.get('featureSourceSHA256') != feature_hash
                or acceptance.get('runtimeImage') != expected_image
                or not all(acceptance.get(k) is True for k in required)):
            raise ValueError('Synthetic live acceptance is required')
        k('apply', '--server-side', '--field-manager=dsh-package-operator', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': documents}))
        k('wait', '--for=condition=complete', 'job/' + args.prefix + '-queue-init', '--timeout=130s')
        current = json.loads(k('get', 'deployment', args.gateway, '-o', 'json'))
        if current['spec'] != gateway['spec']: raise ValueError('Concurrent gateway change')
        try:
            patch_file = args.output / 'gateway-patch.private.json'
            patch_file.write_text(json.dumps([{'op': 'test', 'path': '/spec', 'value': gateway['spec']},
                {'op': 'replace', 'path': '/spec', 'value': spec}]), encoding='utf-8')
            k('patch', 'deployment', args.gateway, '--type=json', '--patch-file', str(patch_file))
            k('rollout', 'status', 'deployment/' + args.gateway, '--timeout=180s')
            k('rollout', 'status', 'deployment/' + args.prefix + '-controller', '--timeout=90s')
        except BaseException:
            observed = json.loads(k('get', 'deployment', args.gateway, '-o', 'json'))
            if observed['spec'] == gateway['spec']:
                raise RuntimeError('Gateway patch did not apply; existing gateway is unchanged')
            if observed['spec'] != spec:
                raise RuntimeError('Concurrent gateway change; preserve it and inspect before rollback')
            rollback_file = args.output / 'gateway-rollback.private.json'
            rollback_file.write_text(json.dumps([{'op': 'test', 'path': '/spec', 'value': spec},
                {'op': 'replace', 'path': '/spec', 'value': gateway['spec']}]), encoding='utf-8')
            k('patch', 'deployment', args.gateway, '--type=json', '--patch-file', str(rollback_file))
            k('rollout', 'status', 'deployment/' + args.gateway, '--timeout=180s')
            k('scale', 'deployment/' + args.prefix + '-controller', '--replicas=0')
            raise
    print(json.dumps({'rendered': True, 'fingerprint': fingerprint, 'applied': args.apply, 'userRuntimesChanged': False}))


if __name__ == '__main__':
    main()
