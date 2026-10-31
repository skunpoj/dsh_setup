"""Trusted, fixed-template package controller; no exec or runtime updates."""
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

from capacity_kube import Kube
from capacity_controller import read_json, atomic_json


def now():
    return datetime.now(timezone.utc).isoformat()


def authorization(root, request):
    a = read_json(root / 'authorization.json')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(a['observedAt'].replace('Z', '+00:00'))).total_seconds()
    if not -5 <= age <= 30:
        raise ValueError('Authorization projection is stale')
    user = a['users'].get(request['owner'])
    if not user or not user['enabled']:
        raise ValueError('Account disabled')
    return user


def deployment(kube, host, mode, config):
    suffix = '.' + config['namespace'] + '.svc.cluster.local'
    if not host.endswith(suffix) or not re.fullmatch('[a-z0-9-]{3,63}', host[:-len(suffix)]):
        raise ValueError('Invalid private route')
    d = kube.call('GET', 'Deployment', host[:-len(suffix)])
    pod = d['spec']['template']['spec']
    labels = d['spec']['template']['metadata']['labels']
    if labels.get('dsh.example.com/egress-mode') != mode:
        raise ValueError('Route environment mismatch')
    main = next(c for c in pod['containers'] if c['name'] == 'dsh')
    if main['image'] != config['runtimeImage'] or pod.get('automountServiceAccountToken') is not False:
        raise ValueError('Runtime image or containment requires review')
    return pod, main


def job(config, request, owner, phase, secure_pod=None, secure_main=None):
    identity = hashlib.sha256((request['owner'] + '|' + owner['secure'] + '|' + owner['internet']).encode()).hexdigest()[:24]
    name = 'dsh-pkg-' + request['id'][:20] + '-' + phase
    context = {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001,
               'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
               'capabilities': {'drop': ['ALL']}, 'seccompProfile': {'type': 'RuntimeDefault'}}
    mounts = [{'name': 'source', 'mountPath': '/task', 'readOnly': True},
              {'name': 'queue', 'mountPath': '/request', 'subPath': 'jobs/' + request['id'], 'readOnly': True},
              {'name': 'queue', 'mountPath': '/result', 'subPath': 'jobs/' + request['id'] + '/' + phase},
              {'name': 'artifacts', 'mountPath': '/artifacts', 'readOnly': phase == 'install'},
              {'name': 'tmp', 'mountPath': '/tmp'}]
    volumes = [{'name': 'source', 'configMap': {'name': config['sourceConfigMap']}},
               {'name': 'queue', 'persistentVolumeClaim': {'claimName': config['queuePVC']}},
               {'name': 'artifacts', 'persistentVolumeClaim': {'claimName': 'dsh-pkg-artifacts-' + identity}},
               {'name': 'tmp', 'emptyDir': {'sizeLimit': '2Gi'}}]
    if phase == 'install':
        work = [copy.deepcopy(m) for m in secure_main['volumeMounts'] if m['mountPath'] == '/workspace' or m['mountPath'].startswith('/workspace/')]
        state = next(m for m in secure_main['volumeMounts'] if m['mountPath'] == '/state')
        work.append({'name': state['name'], 'mountPath': '/notebook',
                     'subPath': '/'.join(x for x in [state.get('subPath', '').strip('/'), 'jupyter'] if x)})
        names = {m['name'] for m in work}
        for v in secure_pod['volumes']:
            if v['name'] in names:
                if not ('persistentVolumeClaim' in v or 'emptyDir' in v):
                    raise ValueError('Unsupported workspace mask')
                volumes.append(copy.deepcopy(v))
        if len([v for v in volumes if v['name'] in names]) != len(names):
            raise ValueError('Incomplete private mounts')
        mounts.extend(work)
    pod = {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
           'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'seccompProfile': {'type': 'RuntimeDefault'}},
           'imagePullSecrets': config.get('imagePullSecrets', []),
           'volumes': volumes, 'containers': [{'name': 'task', 'image': config['runtimeImage'],
               'command': ['python3', '/task/package_task.py', phase], 'securityContext': context,
               'env': [{'name': 'PYTHONDONTWRITEBYTECODE', 'value': '1'}], 'volumeMounts': mounts,
               'resources': {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'cpu': '1', 'memory': '1Gi', 'ephemeral-storage': '2Gi'}}}]}
    if phase == 'download':
        # Initialize only the dedicated artifact PVC. An installer must not
        # trigger recursive fsGroup chmod/chown on the user's state volume.
        pod['securityContext'].update(fsGroup=10001, fsGroupChangePolicy='OnRootMismatch')
    return {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': name,
        'labels': {'app': 'dsh-package-task', 'dsh.example.com/package-owner': identity}},
        'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 600, 'ttlSecondsAfterFinished': 86400,
            'template': {'metadata': {'labels': {'app': 'dsh-package-' + phase}}, 'spec': pod}}}


def ensure(kube, kind, name, body):
    old = kube.call('GET', kind, name)
    if old:
        if old['metadata'].get('labels', {}).get('dsh.example.com/package-managed') != 'true':
            raise ValueError('Package resource collision')
        return old
    body['metadata'].setdefault('labels', {})['dsh.example.com/package-managed'] = 'true'
    return kube.call('POST', kind, body=body)


def tick(root, kube, config):
    jobs = root / 'jobs'
    # Count already started requests before admitting any new lexical ID.
    # Otherwise a newly queued ID sorting before two active requests could
    # bypass the global cap on every reconciliation.
    active = sum(read_json(folder / 'public.json')['state'] in ['downloading', 'installing']
                 for folder in jobs.iterdir() if folder.is_dir() and not folder.is_symlink()
                 and re.fullmatch('[a-f0-9]{32}', folder.name))
    for folder in sorted(jobs.iterdir()):
        if not folder.is_dir() or folder.is_symlink() or not re.fullmatch('[a-f0-9]{32}', folder.name):
            continue
        request = read_json(folder / 'request.json')
        from package_task import validate_request
        validate_request(request)
        if request['id'] != folder.name:
            raise ValueError('Request identity differs')
        state = read_json(folder / 'public.json')
        if state['state'] in ['complete', 'failed', 'cancelled']:
            continue
        try:
            owner = authorization(root, request)
            phase = 'install' if state['state'] == 'installing' else 'download'
            if phase == 'download' and not owner['internetAllowed']:
                raise ValueError('Administrator Internet approval is required')
            # Bound cluster work; existing jobs continue to be checked so
            # revocation is effective even when new requests are waiting.
            if state['state'] == 'queued' and active >= 2:
                continue
            if state['state'] == 'queued':
                active += 1
            secure_pod, secure_main = deployment(kube, owner['secure'], 'offline', config)
            deployment(kube, owner['internet'], 'online', config)
            identity = hashlib.sha256((request['owner'] + '|' + owner['secure'] + '|' + owner['internet']).encode()).hexdigest()[:24]
            ensure(kube, 'PersistentVolumeClaim', 'dsh-pkg-artifacts-' + identity,
                {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'dsh-pkg-artifacts-' + identity},
                 'spec': {'storageClassName': config['storageClass'], 'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '1Gi'}}}})
            for directory in ['download', 'install']:
                (folder / directory).mkdir(exist_ok=True, mode=0o700)
            document = job(config, request, owner, phase, secure_pod, secure_main)
            current = ensure(kube, 'Job', document['metadata']['name'], document)
            if state['state'] == 'queued':
                state.update(state='downloading', startedAt=now()); atomic_json(folder / 'public.json', state)
            result_file = folder / phase / 'result.json'
            if result_file.exists():
                result = read_json(result_file)
                if result['state'] == 'failed':
                    raise ValueError(result.get('reason', 'Package task failed'))
                if phase == 'download' and result['state'] == 'downloaded':
                    atomic_json(folder / 'download.json', result)
                    state.update(state='installing', wheelCount=len(result['wheels']), downloadBytes=result['bytes'])
                elif phase == 'install' and result['state'] == 'complete':
                    state.update(result); state['finishedAt'] = now()
                else:
                    raise ValueError('Unexpected package result')
                atomic_json(folder / 'public.json', state)
            elif current.get('status', {}).get('failed'):
                raise ValueError('Package job failed or exceeded its execution limit')
        except ValueError as error:
            if str(error) in ['Account disabled', 'Administrator Internet approval is required', 'Authorization projection is stale']:
                for phase in ['download', 'install']:
                    name = 'dsh-pkg-' + request['id'][:20] + '-' + phase
                    if kube.call('GET', 'Job', name):
                        kube.call('DELETE', 'Job', name, {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground'})
            state.update(state='failed', reason=str(error)[:180], finishedAt=now()); atomic_json(folder / 'public.json', state)


def main():
    import fcntl
    root = Path('/packages-control')
    config = json.loads(Path('/site/site.json').read_text())
    kube = Kube(config['namespace'])
    with (root / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        while True:
            try:
                tick(root, kube, config)
                atomic_json(root / 'controller-status.json', {'available': True, 'observedAt': now(), 'instance': os.environ.get('POD_UID', '')})
            except Exception as error:
                atomic_json(root / 'controller-status.json', {'available': False, 'observedAt': now(), 'error': type(error).__name__, 'instance': os.environ.get('POD_UID', '')})
            time.sleep(3)


if __name__ == '__main__':
    main()
