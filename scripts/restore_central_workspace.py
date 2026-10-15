"""Restore the central workspace without deleting local rollback volumes.

Requires an already-tested SMB claim and private gateway maintenance probe.
Stops only Secure, reconciles while stopped, then tests actual login/content.
"""
import argparse
import json
from pathlib import Path
import subprocess
import re
import time
from datetime import datetime, timezone


def kube(*args, data=None):
    result = subprocess.run(['kubectl', '-n', 'llm', '--request-timeout=30s', *args],
                            input=data, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def wait_ready():
    for _ in range(120):
        d = json.loads(kube('get', 'deploy', 'dsh-secure', '-o', 'json'))
        if d.get('status', {}).get('observedGeneration', 0) >= d['metadata']['generation'] and d.get('status', {}).get('availableReplicas') == 1:
            return
        time.sleep(5)
    raise RuntimeError('Application availability did not recover')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--central-claim', required=True)
    parser.add_argument('--rollback-dir', type=Path, required=True)
    parser.add_argument('--gateway-probe', required=True)
    parser.add_argument('--validated-history-recovery', help='Reuse a separately restored and verified coherent central history baseline')
    args = parser.parse_args()
    if args.validated_history_recovery and not re.fullmatch(r'/central/dsh-storage-recovery/[0-9]{14}', args.validated_history_recovery):
        raise ValueError('Invalid central history baseline path')
    original = json.loads(kube('get', 'deploy', 'dsh-secure', '-o', 'json'))
    if original['spec']['replicas'] != 1:
        raise ValueError('Expected exactly one Secure writer')
    args.rollback_dir.mkdir(parents=True, exist_ok=True)
    with (args.rollback_dir / 'dsh-secure-before-central-mount.json').open('x') as f:
        json.dump(original, f, indent=2)
    image = original['spec']['template']['spec']['containers'][0]['image']
    claims = {v['name']: v['persistentVolumeClaim']['claimName']
              for v in original['spec']['template']['spec']['volumes']}
    suffix = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    name = 'dsh-cifs-reconcile-' + suffix
    recovery = '/central/dsh-storage-recovery/' + suffix
    script = (Path(__file__).parent / 'reconcile_workspace.py').read_text()
    config = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name},
              'data': {'reconcile_workspace.py': script}}
    kube('apply', '-f', '-', data=json.dumps(config))
    scratch = name + '-restore'
    kube('apply', '-f', '-', data=json.dumps({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
         'metadata': {'name': scratch}, 'spec': {'accessModes': ['ReadWriteOnce'],
         'resources': {'requests': {'storage': '20Gi'}}}}))
    code = '''
import sys,json,tarfile,hashlib,os
from pathlib import Path
sys.path.insert(0,'/maintenance')
from reconcile_workspace import reconcile,digest,restore_history_archive
recovery=Path(RECOVERY)
print(json.dumps({'phase':'reconcile stopped workspace'}),flush=True)
result=reconcile('/source-workspace','/central/dsh',recovery)
print(json.dumps({'phase':'workspace comparison passed',**result}),flush=True)
if HISTORY_BASELINE:
 baseline=Path(HISTORY_BASELINE)
 restoration=json.loads((baseline/'history-restoration-result.json').read_text())
 archive=baseline/'secure-state-history.tar.gz'
 if restoration.get('restoredStateFilesChecked',0)<=0 or digest(archive)!=restoration.get('stateArchiveSHA256'):
  raise RuntimeError('Previously restored history baseline no longer matches its verified content')
 result.update(restoration)
 result.update({'centralStateArchive':str(archive),'historyIsEarlierCoherentBaseline':True,'rollbackLocalWorkspacePreserved':True,'providerCredentialFileExcluded':True})
 (recovery/'central-restore-result.json').write_text(json.dumps(result))
 print(json.dumps({'phase':'CENTRAL_RECONCILIATION_AND_RESTORE_OK',**result}),flush=True)
 sys.exit(0)
archive=recovery/'secure-state-history.tar.gz'
with tarfile.open(archive,'x:gz') as target:
 for name in ['sessions','attachments','storages','workspaces','AGENTS.md']:
  source=Path('/source-state')/name
  if source.exists():target.add(source,arcname=name)
print(json.dumps({'phase':'central history archive created; verify copied-state restore'}),flush=True)
restored=Path('/restore/state')
restoration=restore_history_archive(archive,restored)
checked=0
for path in restored.rglob('*'):
 if path.is_file() and not path.is_symlink():
  original=Path('/source-state')/path.relative_to(restored)
  if digest(path)!=digest(original):raise RuntimeError('Restored state differs from stopped source')
  checked+=1
result.update({'centralStateArchive':str(archive),'restoredStateFilesChecked':checked,'stateArchiveSHA256':restoration['stateArchiveSHA256'],'rollbackLocalWorkspacePreserved':True,'providerCredentialFileExcluded':True})
(recovery/'central-restore-result.json').write_text(json.dumps(result))
print(json.dumps({'phase':'CENTRAL_RECONCILIATION_AND_RESTORE_OK',**result}),flush=True)
'''.replace('RECOVERY', repr(recovery)).replace('HISTORY_BASELINE', repr(args.validated_history_recovery))
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': name},
       'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 2400, 'template': {
       'metadata': {'labels': {'app': 'dsh-maintenance', 'dsh.bot.or.th/egress-mode': 'offline'}},
       'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
       'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'runAsNonRoot': True,
                           'fsGroup': 10001, 'fsGroupChangePolicy': 'OnRootMismatch',
                           'seccompProfile': {'type': 'RuntimeDefault'}},
       'containers': [{'name': 'reconcile', 'image': image, 'command': ['python3', '-c', code],
         'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
         'resources': {'requests': {'cpu': '500m', 'memory': '256Mi'}, 'limits': {'cpu': '4', 'memory': '2Gi'}},
         'volumeMounts': [{'name': 'workspace', 'mountPath': '/source-workspace'},
                         {'name': 'state', 'mountPath': '/source-state'},
                         {'name': 'central', 'mountPath': '/central'},
                         {'name': 'scratch', 'mountPath': '/restore'},
                         {'name': 'script', 'mountPath': '/maintenance', 'readOnly': True}]}],
       'volumes': [{'name': 'workspace', 'persistentVolumeClaim': {'claimName': claims['protected-workspace']}},
                   {'name': 'state', 'persistentVolumeClaim': {'claimName': claims['state']}},
                   {'name': 'central', 'persistentVolumeClaim': {'claimName': args.central_claim}},
                   {'name': 'scratch', 'persistentVolumeClaim': {'claimName': scratch}},
                   {'name': 'script', 'configMap': {'name': name}}]}}}}
    print(json.dumps({'phase': 'stop Secure writer; Internet and inference remain unchanged', 'job': name}), flush=True)
    kube('scale', 'deploy', 'dsh-secure', '--replicas=0')
    try:
        for _ in range(90):
            if not json.loads(kube('get', 'pods', '-l', 'app=dsh-secure', '-o', 'json'))['items']:
                break
            time.sleep(2)
        else:
            raise RuntimeError('Secure writer did not terminate')
        kube('apply', '-f', '-', data=json.dumps(job))
        last = None
        for _ in range(490):
            status = json.loads(kube('get', 'job', name, '-o', 'json')).get('status', {})
            try:
                log = kube('logs', 'job/' + name)
                if log != last:
                    print(log[len(last or ''):] if log.startswith(last or '') else log, flush=True)
                    last = log
            except RuntimeError:
                pass
            if status.get('failed'):
                raise RuntimeError('Reconciliation failed; private worker log requires review')
            if status.get('succeeded'):
                break
            time.sleep(5)
        else:
            raise RuntimeError('Reconciliation timeout')
        if not last or 'CENTRAL_RECONCILIATION_AND_RESTORE_OK' not in last:
            raise RuntimeError('Missing actual reconciliation/restore result')
        (args.rollback_dir / 'reconciliation.log').write_text(last)
        result = json.loads(last.strip().splitlines()[-1])
        kube('delete', 'job', name, '--wait=true', '--timeout=60s')
        template = json.loads(json.dumps(original['spec']['template']))
        for volume in template['spec']['volumes']:
            if volume['name'] == 'protected-workspace':
                volume['persistentVolumeClaim']['claimName'] = args.central_claim
        for mount in template['spec']['containers'][0]['volumeMounts']:
            if mount['name'] == 'protected-workspace':
                mount['subPath'] = 'dsh'
        template['metadata'].setdefault('annotations', {})['dsh.bot.or.th/workspace-backend'] = 'DA_WORKSPACE-CIFS'
        kube('patch', 'deploy', 'dsh-secure', '--type=merge', '-p', json.dumps({'spec': {'replicas': 1, 'template': template}}))
        wait_ready()
        kube('exec', 'deploy/dsh-secure', '--', 'node', '/opt/dsh/scripts/runtime_health.js')
        for action in ['resume', 'verify']:
            tested = json.loads(kube('exec', 'deploy/dsh-environment-gateway', '--', 'node', args.gateway_probe, action))
            (args.rollback_dir / ('login-' + action + '-after.json')).write_text(json.dumps(tested, indent=2))
        result.update({'productionMountRestored': True, 'centralClaim': args.central_claim,
                       'imageUnchanged': image, 'allocatedScratchPVC': scratch,
                       'historyRestoreReused': bool(args.validated_history_recovery),
                       'centralRecoveryDirectory': recovery, 'timeUTC': datetime.now(timezone.utc).isoformat()})
        (args.rollback_dir / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    except BaseException:
        kube('delete', 'job', name, '--ignore-not-found=true', '--wait=true', '--timeout=60s')
        kube('patch', 'deploy', 'dsh-secure', '--type=json', '-p', json.dumps([
            {'op': 'replace', 'path': '/spec', 'value': original['spec']}]))
        wait_ready()
        print(json.dumps({'rollback': 'original local workspace specification restored; central copies retained'}), flush=True)
        raise


if __name__ == '__main__':
    main()
