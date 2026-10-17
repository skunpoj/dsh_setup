"""Wire installed legacy clients to scoped inference and existing private storage.

Requires a previously verified legacy transport rollout and an idle agent. The
new /state alias is the same owner's existing private home volume; no workspace,
history or credential file is copied or reassigned. Keep normal owner acceptance
and durable-file checks as final release gates.
"""
import argparse
import copy
import json
from pathlib import Path
from provision_harness_credentials import provision
from rollout_legacy_context_transport import kube
from rollout_managed_budget import SNAPSHOT

ROOT = Path(__file__).resolve().parents[1]


def candidate(original, secret, policy):
    spec = copy.deepcopy(original['spec']);pod=spec['template']['spec']
    if spec['replicas'] != 1 or spec['strategy']['type'] != 'Recreate':
        raise ValueError('Single owner/writer required')
    worker=next(c for c in pod['containers'] if c['name']=='dsh')
    if '@sha256:'not in worker['image']:raise ValueError('Pinned runtime image required')
    if worker.get('securityContext',{}).get('runAsUser') != 10001:
        raise ValueError('Non-root worker required')
    if any(v['name'] in ['harness-credentials','managed-client-policy'] for v in pod['volumes']):
        raise ValueError('Existing harness configuration requires explicit review')
    paths=['/state','/harness-credentials','/etc/claude-code/managed-settings.json','/opt/dsh/container/trueforge-managed.sh']
    if any(m['mountPath'] in paths for m in worker['volumeMounts']):
        raise ValueError('Conflicting state or policy mount')
    home=next(m for m in worker['volumeMounts'] if m['mountPath']=='/root')
    state={**home,'mountPath':'/state'}
    pod['volumes'] += [
        # This legacy pod deliberately has no volume-wide fsGroup mutation.
        # Only its owner worker mounts this read-only model-scoped Secret.
        {'name':'harness-credentials','secret':{'secretName':secret,'defaultMode':0o444}},
        {'name':'managed-client-policy','configMap':{'name':policy,'defaultMode':0o444,
          'items':[{'key':'claude-managed-settings.json','path':'claude-managed-settings.json','mode':0o444},
                   {'key':'trueforge-managed.sh','path':'trueforge-managed.sh','mode':0o555}]}}]
    worker['volumeMounts'] += [state,{'name':'harness-credentials','mountPath':'/harness-credentials','readOnly':True},
        {'name':'managed-client-policy','mountPath':paths[2],'subPath':'claude-managed-settings.json','readOnly':True},
        {'name':'managed-client-policy','mountPath':paths[3],'subPath':'trueforge-managed.sh','readOnly':True}]
    pod.setdefault('initContainers',[]).append({'name':'private-harness-state','image':worker['image'],
        'command':['python3','-c',"from pathlib import Path;p=Path('/state/trueforge');p.mkdir(mode=0o700,exist_ok=True)"],
        'securityContext':copy.deepcopy(worker['securityContext']),'volumeMounts':[state]})
    return spec


def repair_key_mode(original, secret):
    spec=copy.deepcopy(original['spec']);pod=spec['template']['spec']
    if spec['replicas']!=1 or spec['strategy']['type']!='Recreate':raise ValueError('Single writer required')
    volume=next(v for v in pod['volumes']if v['name']=='harness-credentials')
    if volume.get('secret')!={'secretName':secret,'defaultMode':0o440}:
        raise ValueError('Unreviewed credential-mode repair baseline')
    consumers=[c for c in pod['containers']if any(m['name']=='harness-credentials'for m in c.get('volumeMounts',[]))]
    if len(consumers)!=1 or consumers[0]['name']!='dsh' or not all(m.get('readOnly')for m in consumers[0]['volumeMounts']if m['name']=='harness-credentials'):
        raise ValueError('Credential must stay read-only and owner-worker-only')
    volume['secret']['defaultMode']=0o444
    return spec


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--name',choices=['dsh-user2','dsh3'],required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--apply',action='store_true')
    ap.add_argument('--repair-key-mode',action='store_true',help='Repair only the reviewed0440 owner-only mount baseline');args=ap.parse_args()
    original=json.loads(kube('get','deploy',args.name,'-o','json'))
    main=json.loads(kube('get','deploy','dsh-secure','-o','json'))
    policy=next(v['configMap']['name']for v in main['spec']['template']['spec']['volumes']if v['name']=='managed-client-policy')
    data=json.loads(kube('get','cm',policy,'-o','json'))
    if not data.get('immutable'):raise ValueError('Qualified policy must be immutable')
    for key,path in [('claude-managed-settings.json','container/claude-managed-settings.json'),('trueforge-managed.sh','container/trueforge-managed.sh')]:
        if data['data'][key]!=(ROOT/path).read_text(encoding='utf-8'):
            raise ValueError('Qualified managed policy source differs')
    secret='dsh-harness-legacy-'+args.name.removeprefix('dsh-')
    spec=repair_key_mode(original,secret)if args.repair_key_mode else candidate(original,secret,policy)
    print(json.dumps({'name':args.name,'privateExistingHomeAlias':True,'modelScopedCredential':True,'gpuRestartRequired':False}),flush=True)
    if not args.apply:return
    snapshot=SNAPSHOT.replace('import http.client,json,uuid','import http.client,json,uuid,os').replace("h='dsh.aiportal.bot.or.th'","h=os.environ['DSH_TRUSTED_HOST']").replace("HTTPConnection('127.0.0.1',3080","HTTPConnection('127.0.0.1',3081")
    before=json.loads(kube('exec','-i','deploy/'+args.name,'-c','dsh','--','python3','-',data=snapshot))
    if before['running']:raise ValueError('Active owner agent; defer rollout')
    args.output.mkdir(parents=True,exist_ok=False);(args.output/'deployment-before.private.json').write_text(json.dumps(original),encoding='utf-8')
    issued=provision(secret)
    try:
        # Provisioning did not authorize changing a concurrently updated workload.
        current=json.loads(kube('get','deploy',args.name,'-o','json'))
        if current['spec']!=original['spec']:raise ValueError('Concurrent specification change')
        kube('patch','deploy',args.name,'--type=json','-p',json.dumps([
            {'op':'test','path':'/metadata/resourceVersion','value':current['metadata']['resourceVersion']},
            {'op':'replace','path':'/spec','value':spec}]))
        kube('rollout','status','deploy/'+args.name,'--timeout=180s')
        verify="""import json,os,errno
from pathlib import Path
v=json.load(open('/etc/claude-code/managed-settings.json'));assert v['model']=='deepseek-v4.1-flash[1m]';assert Path('/harness-credentials/api-key').stat().st_size>0
with open('/harness-credentials/api-key','rb')as f:assert len(f.read(1))==1
assert os.stat('/state').st_dev==os.stat('/root').st_dev and os.stat('/state').st_ino==os.stat('/root').st_ino
for p in ['/harness-credentials/api-key','/etc/claude-code/managed-settings.json','/opt/dsh/container/trueforge-managed.sh']:
 try:fd=os.open(p,os.O_WRONLY)
 except OSError as e:assert e.errno in [errno.EACCES,errno.EROFS]
 else:os.close(fd);raise RuntimeError('Managed file unexpectedly writable')
print(json.dumps({'managedModel':v['model'],'privateStateAliasVerified':True,'credentialMountedReadOnly':True,'credentialValuesExported':False}))
"""
        actual=json.loads(kube('exec','-i','deploy/'+args.name,'-c','dsh','--','python3','-',data=verify))
        after=json.loads(kube('exec','-i','deploy/'+args.name,'-c','dsh','--','python3','-',data=snapshot))
        if not set(before['ids']).issubset(after['ids']):raise RuntimeError('Original histories missing')
        (args.output/'result.json').write_text(json.dumps({'status':'passed','credential':issued,'installedPolicy':actual,
            'originalHistoryIDsPreserved':True,'ownerAcceptanceAndFileChecksRequired':True},indent=2),encoding='utf-8')
    except BaseException:
        kube('patch','deploy',args.name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':original['spec']}]))
        kube('rollout','status','deploy/'+args.name,'--timeout=180s');raise


if __name__=='__main__':main()
