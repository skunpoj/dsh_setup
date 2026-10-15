"""Compare a stopped-state archive against existing runtime mounts.

The backup reader mounts only the backup PVC. Never co-mount a live state PVC
in a second pod: CSI mount modes and SELinux relabeling can disrupt its owner.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path


def kube(*args, data=None):
    result = subprocess.run(['kubectl', '-n', 'llm', '--request-timeout=30s', *args],
                            input=data, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def verify(environment, snapshot, image, result_file):
    worker = f'{snapshot}-manifest'
    generator = r'''
import hashlib,json,tarfile,time
rows=[]
for archive,root,restricted in [('/backup/workspace.tar.gz','workspace',False),('/backup/state.tar.gz','state',True)]:
 with tarfile.open(archive,'r|gz') as source:
  for member in source:
   relative=member.name.removeprefix('./')
   if not member.isfile() or relative.endswith('.lock'):continue
   if restricted and not relative.startswith(('sessions/','attachments/','.rollout-checks/')):continue
   digest=hashlib.sha256();stream=source.extractfile(member)
   while True:
    block=stream.read(1048576)
    if not block:break
    digest.update(block)
   rows.append({'root':root,'path':relative,'size':member.size,'sha256':digest.hexdigest()})
with open('/tmp/manifest.json','w') as target:json.dump(rows,target)
print(json.dumps({'manifestReady':True,'regularFiles':len(rows)}),flush=True)
time.sleep(600)
'''
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': worker},
      'spec': {'backoffLimit': 0, 'activeDeadlineSeconds': 900, 'template': {
      'metadata': {'labels': {'app': 'dsh-maintenance', 'dsh.bot.or.th/egress-mode': 'offline'}},
      'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
      'securityContext': {'runAsUser': 10001, 'runAsGroup': 10001, 'runAsNonRoot': True, 'fsGroup': 10001,
                          'fsGroupChangePolicy': 'OnRootMismatch', 'seccompProfile': {'type': 'RuntimeDefault'}},
      'containers': [{'name': 'manifest', 'image': image, 'command': ['python3', '-c', generator],
      'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
      'resources': {'requests': {'cpu': '500m', 'memory': '256Mi'}, 'limits': {'cpu': '4', 'memory': '1Gi'}},
      'volumeMounts': [{'name': 'backup', 'mountPath': '/backup'}]}],
      'volumes': [{'name': 'backup', 'persistentVolumeClaim': {'claimName': snapshot}}]}}}}
    kube('apply', '-f', '-', data=json.dumps(job))
    try:
        print(json.dumps({'phase': 'derive private hash inventory from coherent archive', 'environment': environment}), flush=True)
        manifest = None
        for _ in range(90):
            try:
                manifest = kube('exec', f'job/{worker}', '--', 'cat', '/tmp/manifest.json')
                json.loads(manifest)
                break
            except (RuntimeError, json.JSONDecodeError):
                time.sleep(5)
        else:
            raise RuntimeError('Backup inventory not available')
        comparison = r'''
import sys,json,hashlib
from pathlib import Path
rows=json.load(sys.stdin);checked=failures=appended=total=0;by_root={}
for item in rows:
 root=Path('/workspace' if item['root']=='workspace' else '/state');current=root/item['path']
 checked+=1;total+=item['size'];by_root[item['root']]=by_root.get(item['root'],0)+1
 if not current.resolve().is_relative_to(root.resolve()):failures+=1;continue
 digest=hashlib.sha256();remaining=item['size']
 try:
  with current.open('rb') as source:
   while remaining:
    block=source.read(min(1048576,remaining))
    if not block:break
    digest.update(block);remaining-=len(block)
  if remaining or digest.hexdigest()!=item['sha256']:failures+=1
  if current.stat().st_size>item['size']:appended+=1
 except OSError:failures+=1
print(json.dumps({'regularFilesChecked':checked,'originalBytesChecked':total,'contentFailures':failures,'appendOnlyGrowth':appended,'filesByRoot':by_root,'excludes':'lock files, derived state indexes, symlinks and hardlink aliases'}),flush=True)
raise SystemExit(1 if failures else 0)
'''
        # Hash inventory is private stdin, never a command-line argument or log.
        result = json.loads(kube('exec', '-i', f'deploy/dsh-{environment}', '--', 'python3', '-c', comparison, data=manifest))
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_file.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
        return result
    finally:
        kube('delete', 'job', worker, '--wait=false')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--environment', choices=['secure', 'internet'], required=True)
    parser.add_argument('--snapshot-pvc', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--result-file', type=Path, required=True)
    args = parser.parse_args()
    verify(args.environment, args.snapshot_pvc, args.image, args.result_file)
