"""Offline resource-reference checks. Does not contact Kubernetes or print values."""
import argparse
import json
import re
from pathlib import Path

import yaml


def check(paths, external=()):
    objects = []
    errors = []
    for path in paths:
        for obj in yaml.safe_load_all(Path(path).read_text(encoding='utf-8')):
            if obj:
                objects.extend(obj.get('items', []) if obj.get('kind') == 'List' else [obj])
    identities = set()
    for obj in objects:
        meta = obj.get('metadata', {})
        identity = (obj.get('kind'), meta.get('namespace', 'default'), meta.get('name'))
        if identity in identities:
            errors.append('Duplicate object: ' + '/'.join(identity))
        identities.add(identity)
    available = identities | {tuple(value.split('/')) for value in external}
    for obj in objects:
        kind = obj.get('kind')
        meta = obj.get('metadata', {})
        ns = meta.get('namespace', 'default')
        label = f"{kind}/{ns}/{meta.get('name')}"

        def require(target_kind, name):
            if name and (target_kind, ns, name) not in available:
                errors.append(f'{label} needs {target_kind}/{ns}/{name}')

        if kind in {'Deployment', 'StatefulSet', 'DaemonSet', 'Job'}:
            pod = obj['spec']['template']['spec']
        elif kind == 'CronJob':
            pod = obj['spec']['jobTemplate']['spec']['template']['spec']
        elif kind == 'Pod':
            pod = obj['spec']
        else:
            pod = None
        if pod:
            for volume in pod.get('volumes', []):
                require('PersistentVolumeClaim', volume.get('persistentVolumeClaim', {}).get('claimName'))
                require('Secret', volume.get('secret', {}).get('secretName'))
                require('ConfigMap', volume.get('configMap', {}).get('name'))
                for source in volume.get('projected', {}).get('sources', []):
                    require('Secret', source.get('secret', {}).get('name'))
                    require('ConfigMap', source.get('configMap', {}).get('name'))
            for item in pod.get('imagePullSecrets', []):
                require('Secret', item.get('name'))
            if pod.get('serviceAccountName') not in (None, 'default'):
                require('ServiceAccount', pod['serviceAccountName'])
            for container in pod.get('initContainers', []) + pod.get('containers', []):
                if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', container.get('image', '')):
                    errors.append(f'{label} has an image without an immutable SHA256 digest')
                for env in container.get('env', []):
                    source = env.get('valueFrom', {})
                    require('Secret', source.get('secretKeyRef', {}).get('name'))
                    require('ConfigMap', source.get('configMapKeyRef', {}).get('name'))
                for source in container.get('envFrom', []):
                    require('Secret', source.get('secretRef', {}).get('name'))
                    require('ConfigMap', source.get('configMapRef', {}).get('name'))
        if kind == 'Ingress':
            for tls in obj.get('spec', {}).get('tls', []):
                require('Secret', tls.get('secretName'))
            backends = [obj.get('spec', {}).get('defaultBackend', {})]
            for rule in obj.get('spec', {}).get('rules', []):
                backends += [entry.get('backend', {}) for entry in rule.get('http', {}).get('paths', [])]
            for backend in backends:
                require('Service', backend.get('service', {}).get('name'))
    return {'passed': not errors, 'objects': len(objects), 'errors': sorted(set(errors)),
            'scope': 'Offline references and image pins only; no cluster or runtime acceptance'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, action='append', required=True)
    parser.add_argument('--external', action='append', default=[], metavar='KIND/NAMESPACE/NAME',
                        help='Existing resource name verified separately; never supply credential values')
    args = parser.parse_args()
    if any(len(value.split('/')) != 3 for value in args.external):
        parser.error('--external requires Kind/namespace/name')
    result = check(args.manifest, args.external)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
