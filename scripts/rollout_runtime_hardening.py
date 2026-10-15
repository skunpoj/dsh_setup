"""Quiesce one DSH pool, compare a coherent local archive, then replace its image.

No data deletion or central-share transfer. Source state remains in place.
"""
import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def kube(*args, payload=None):
    result = subprocess.run(['kubectl', '-n', 'llm', '--request-timeout=20s', *args],
                            input=json.dumps(payload) if payload else None,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def progress(message):
    print(json.dumps({'time': datetime.now(timezone.utc).isoformat(), 'phase': message}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', choices=['secure', 'internet'], required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--rollback-dir', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', args.image):
        raise ValueError('Immutable image required')
    name = f'dsh-{args.environment}'
    original = json.loads(kube('get', 'deploy', name, '-o', 'json'))
    if original['spec']['replicas'] != 1:
        raise ValueError('Expected one current writer')
    args.rollback_dir.mkdir(parents=True, exist_ok=True)
    # Never overwrite an earlier rollback point when repeating a command.
    with (args.rollback_dir / f'{name}-before.json').open('x', encoding='utf-8') as saved:
        saved.write(json.dumps(original, indent=2))
    volumes = {v['name']: v['persistentVolumeClaim']['claimName'] for v in original['spec']['template']['spec']['volumes']}
    workspace = volumes['protected-workspace' if args.environment == 'secure' else 'staging']
    suffix = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    backup = f'dsh-snapshot-{args.environment}-{suffix}'
    progress(f'{name}: stop current writer before coherent archive')
    kube('scale', 'deploy', name, '--replicas=0')
    try:
        for _ in range(75):
            pods = json.loads(kube('get', 'pods', '-l', f'app={name}', '-o', 'json'))['items']
            if not pods:
                break
            time.sleep(2)
        else:
            raise RuntimeError('Old writer did not terminate')
        kube('apply', '-f', '-', payload={'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
             'metadata': {'name': backup}, 'spec': {'accessModes': ['ReadWriteOnce'],
             'resources': {'requests': {'storage': '20Gi'}}}})
        command = '''set -eu
umask 077
tar --one-file-system -czf /backup/state.tar.gz -C /source-state .
tar --one-file-system -czf /backup/workspace.tar.gz -C /source-workspace .
tar -dzf /backup/state.tar.gz -C /source-state
tar -dzf /backup/workspace.tar.gz -C /source-workspace
sha256sum /backup/state.tar.gz /backup/workspace.tar.gz
printf 'ARCHIVE_CONTENT_COMPARE_OK\\n'
'''
        job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': backup},
          'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 600, 'template': {
          'metadata': {'labels': {'app': 'dsh-maintenance', 'dsh.bot.or.th/egress-mode': 'offline'}},
          'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
          'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'runAsNonRoot': True,
                              'fsGroup': 10001, 'fsGroupChangePolicy': 'OnRootMismatch',
                              'seccompProfile': {'type': 'RuntimeDefault'}},
          'containers': [{'name': 'snapshot', 'image': args.image, 'command': ['sh', '-c', command],
            'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
            'resources': {'requests': {'cpu': '500m', 'memory': '256Mi'}, 'limits': {'cpu': '2', 'memory': '1Gi'}},
            'volumeMounts': [{'name': 'state', 'mountPath': '/source-state'},
                            {'name': 'workspace', 'mountPath': '/source-workspace'},
                            {'name': 'backup', 'mountPath': '/backup'}]}],
          'volumes': [{'name': 'state', 'persistentVolumeClaim': {'claimName': volumes['state']}},
                      {'name': 'workspace', 'persistentVolumeClaim': {'claimName': workspace}},
                      {'name': 'backup', 'persistentVolumeClaim': {'claimName': backup}}]}}}}
        kube('apply', '-f', '-', payload=job)
        progress(f'{name}: creating and comparing stopped-state archive in {backup}')
        for _ in range(130):
            status = json.loads(kube('get', 'job', backup, '-o', 'json')).get('status', {})
            if status.get('failed'):
                raise RuntimeError('Snapshot job failed; inspect its private logs')
            if status.get('succeeded'):
                break
            time.sleep(5)
        else:
            raise RuntimeError('Snapshot did not complete')
        log = kube('logs', f'job/{backup}')
        if 'ARCHIVE_CONTENT_COMPARE_OK' not in log:
            raise RuntimeError('Missing actual content comparison')
        (args.rollback_dir / f'{name}-snapshot.log').write_text(log, encoding='utf-8')
        template = json.loads(json.dumps(original['spec']['template']))
        pod = template['spec']
        pod['automountServiceAccountToken'] = False
        pod['terminationGracePeriodSeconds'] = 120
        pod.setdefault('securityContext', {})['seccompProfile'] = {'type': 'RuntimeDefault'}
        container = pod['containers'][0]
        container['image'] = args.image
        probe = {'exec': {'command': ['node', '/opt/dsh/scripts/runtime_health.js']}, 'timeoutSeconds': 3}
        container['startupProbe'] = {**probe, 'periodSeconds': 5, 'failureThreshold': 120}
        container['readinessProbe'] = {**probe, 'periodSeconds': 5, 'failureThreshold': 6}
        container['livenessProbe'] = {**probe, 'periodSeconds': 15, 'failureThreshold': 3}
        kube('patch', 'deploy', name, '--type=merge', '-p', json.dumps({'spec': {
              'strategy': {'type': 'Recreate', 'rollingUpdate': None}, 'template': template, 'replicas': 1}}))
        progress(f'{name}: new image starting; waiting for application health')
        for _ in range(125):
            current = json.loads(kube('get', 'deploy', name, '-o', 'json'))
            if current['status'].get('observedGeneration', 0) >= current['metadata']['generation'] and current['status'].get('availableReplicas') == 1:
                break
            time.sleep(5)
        else:
            raise RuntimeError('Application did not recover')
        kube('exec', f'deploy/{name}', '--', 'node', '/opt/dsh/scripts/runtime_health.js')
        # Release the completed snapshot pod before reopening its backup PVC.
        kube('delete', 'job', backup, '--wait=true', '--timeout=30s')
        from verify_runtime_persistence import verify
        content = verify(args.environment, backup, args.image,
                         args.rollback_dir / f'{name}-persistence.json')
        record = {'time': datetime.now(timezone.utc).isoformat(), 'deployment': name, 'image': args.image,
                  'snapshotPVC': backup, 'archiveContentComparison': True, 'applicationHealth': True,
                  'strategy': 'Recreate', 'centralBackup': False, 'persistence': content}
        (args.rollback_dir / f'{name}-result.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(json.dumps(record), flush=True)
    except BaseException:
        # Stop maintenance readers before restoring the writer. A partial
        # archive is never declared valid or used to overwrite current data.
        try:
            kube('delete', 'job', backup, '--ignore-not-found=true', '--wait=true', '--timeout=60s')
        except RuntimeError:
            pass
        progress(f'{name}: restoring original deployment specification')
        kube('patch', 'deploy', name, '--type=json', '-p', json.dumps([
              {'op': 'replace', 'path': '/spec', 'value': original['spec']}]))
        for _ in range(125):
            restored = json.loads(kube('get', 'deploy', name, '-o', 'json'))
            if restored['status'].get('observedGeneration', 0) >= restored['metadata']['generation'] and restored['status'].get('availableReplicas') == 1:
                try:
                    kube('exec', f'deploy/{name}', '--', 'node', '-e',
                         "require('http').get('http://127.0.0.1:3080/',r=>{r.resume();process.exit([200,302,401].includes(r.statusCode)?0:1)}).on('error',()=>process.exit(1))")
                    progress(f'{name}: previous specification restored and application responds')
                    break
                except RuntimeError:
                    pass
            time.sleep(5)
        else:
            raise RuntimeError('Rollback specification restored but application recovery is unverified')
        raise


if __name__ == '__main__':
    main()
