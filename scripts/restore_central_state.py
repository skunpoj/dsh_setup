"""Stop Secure, preserve central originals, mount durable state directly on CIFS.

Credentials/config remain on local state. Never deletes historical central copies.
Rollback restores previous mounts and leaves both copies available for review.
"""
import argparse,json,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

def k(*args,data=None):
 r=subprocess.run(['kubectl','-n','llm','--request-timeout=30s',*args],input=data,text=True,capture_output=True)
 if r.returncode:raise RuntimeError(r.stderr.strip())
 return r.stdout

def ready():
 for _ in range(90):
  d=json.loads(k('get','deploy','dsh-secure','-o','json'))
  if d.get('status',{}).get('observedGeneration',0)>=d['metadata']['generation'] and d.get('status',{}).get('availableReplicas')==1:return
  time.sleep(3)
 raise RuntimeError('Secure did not become ready')

def main():
 p=argparse.ArgumentParser();p.add_argument('--rollback-dir',type=Path,required=True);p.add_argument('--probe',required=True);a=p.parse_args()
 a.rollback_dir.mkdir(parents=True,exist_ok=False)
 original=json.loads(k('get','deploy','dsh-secure','-o','json'));(a.rollback_dir/'before.json').write_text(json.dumps(original,indent=2))
 if original['spec']['replicas']!=1:raise ValueError('Expected single Secure writer')
 pod=original['spec']['template']['spec'];container=pod['containers'][0];image=container['image'];claims={v['name']:v['persistentVolumeClaim']['claimName'] for v in pod['volumes']}
 suffix=datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S');name='dsh-central-state-'+suffix
 script=Path(__file__).with_name('session_cwd_migration.py').read_text()
 k('apply','-f','-',data=json.dumps({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':name},'data':{'session_cwd_migration.py':script,'reconcile_workspace.py':Path(__file__).with_name('reconcile_workspace.py').read_text()}}))
 code=r"""from pathlib import Path
import json,shutil,hashlib,os,sys
sys.path.insert(0,'/maintenance');from session_cwd_migration import migrate,event_digest
from reconcile_workspace import reconcile
central=Path('/workspace/dsh_storage');recovery=Path('/workspace/.state-recovery-RECOVERY_ID');recovery.mkdir(mode=0o700)
names=['sessions','attachments','storages','workspaces','logs'];records=[]
for name in names:
 source=Path('/source-state')/name;target=recovery/'candidate'/name
 if not source.exists():source.mkdir()
 shutil.copytree(source,target,symlinks=True)
 count=0
 for f in source.rglob('*'):
  if f.is_symlink():raise ValueError('State symlink requires review')
  if f.is_file():
   if event_digest(f,0)!=event_digest(target/f.relative_to(source),0):raise RuntimeError('Central state readback mismatch')
   count+=1
 records.append({'directory':name,'filesVerified':count})
print(json.dumps({'phase':'stopped state copied and read back','directories':records}),flush=True)
mapping={'/root':'/workspace'}
for folder in ['1213','Dashboard','PDF','Spark','green-test','kim954','nb corp structure']:
 mapping['/root/'+folder]='/workspace/dsh_storage/workspaces/'+folder
# The live CIFS project directory is authoritative over stale copies in local state.
# Preserve both conflict versions and destination-only state files.
workspace_result=reconcile(central/'workspaces',recovery/'candidate/workspaces',recovery/'workspace-conflicts') if (central/'workspaces').exists() else None
result=migrate(recovery/'candidate/sessions',mapping,recovery/'cwd-originals')
result['canonicalWorkspaceReconciliation']=workspace_result
central.mkdir(exist_ok=True);(recovery/'previous-central').mkdir()
for name in names:
 old=central/name
 if old.exists():os.rename(old,recovery/'previous-central'/name)
 os.rename(recovery/'candidate'/name,old)
result.update({'directories':records,'activeDurableSubdirectories':names,'credentialsCopied':False,'centralRecovery':str(recovery),'stoppedWriter':True})
(recovery/'result.json').write_text(json.dumps(result));print(json.dumps({'phase':'CENTRAL_STATE_READY',**result}),flush=True)
""".replace('RECOVERY_ID',suffix)
 job={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':name},'spec':{'backoffLimit':0,'activeDeadlineSeconds':1800,'template':{'metadata':{'labels':{'app':'dsh-maintenance','dsh.bot.or.th/egress-mode':'offline'}},'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'securityContext':{'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'migration','image':image,'command':['python3','-c',code],'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},'resources':{'requests':{'cpu':'500m','memory':'256Mi'},'limits':{'cpu':'4','memory':'2Gi'}},'volumeMounts':[{'name':'state','mountPath':'/source-state'},{'name':'central','mountPath':'/workspace','subPath':'dsh'},{'name':'script','mountPath':'/maintenance','readOnly':True}]}],'volumes':[{'name':'state','persistentVolumeClaim':{'claimName':claims['state']}},{'name':'central','persistentVolumeClaim':{'claimName':claims['protected-workspace']}},{'name':'script','configMap':{'name':name}}]}}}}
 print(json.dumps({'phase':'stop Secure single writer','rollback':str(a.rollback_dir)}),flush=True)
 k('scale','deploy','dsh-secure','--replicas=0')
 try:
  for _ in range(90):
   if not json.loads(k('get','pods','-l','app=dsh-secure','-o','json'))['items']:break
   time.sleep(2)
  else:raise RuntimeError('Secure writer did not stop')
  k('apply','-f','-',data=json.dumps(job));last=''
  for _ in range(360):
   status=json.loads(k('get','job',name,'-o','json')).get('status',{})
   try:
    log=k('logs','job/'+name)
    if log!=last:print(log[len(last):],flush=True);last=log
   except RuntimeError:pass
   if status.get('failed'):raise RuntimeError('Central state preparation failed')
   if status.get('succeeded'):break
   time.sleep(5)
  else:raise RuntimeError('Central state preparation timed out')
  (a.rollback_dir/'migration.log').write_text(last)
  result=json.loads(last.strip().splitlines()[-1]);assert result['phase']=='CENTRAL_STATE_READY'
  k('delete','job',name,'--wait=true','--timeout=60s')
  template=json.loads(json.dumps(original['spec']['template']))
  for directory in result['activeDurableSubdirectories']:
   template['spec']['containers'][0]['volumeMounts'].append({'name':'protected-workspace','mountPath':'/state/'+directory,'subPath':'dsh/dsh_storage/'+directory})
  template['metadata'].setdefault('annotations',{})['dsh.bot.or.th/durable-state-backend']='DA_WORKSPACE-CIFS'
  k('patch','deploy','dsh-secure','--type=merge','-p',json.dumps({'spec':{'replicas':1,'template':template}}));ready()
  for action in ['resume','verify']:
   v=json.loads(k('exec','deploy/dsh-environment-gateway','--','node',a.probe,action));result['login_'+action]=v
  # Force another process replacement to test real direct-state persistence.
  before_pods=json.loads(k('get','pods','-l','app=dsh-secure','-o','json'))['items']
  old_uids={p['metadata']['uid'] for p in before_pods}
  k('rollout','restart','deploy/dsh-secure');ready()
  after_pods=json.loads(k('get','pods','-l','app=dsh-secure','-o','json'))['items']
  if not after_pods or any(p['metadata']['uid'] in old_uids for p in after_pods):raise RuntimeError('Restart did not replace the old process')
  result['login_afterSecondRestart']=json.loads(k('exec','deploy/dsh-environment-gateway','--','node',a.probe,'verify'))
  (a.rollback_dir/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps({'phase':'CENTRAL_STATE_DEPLOYED','resultFile':str(a.rollback_dir/'result.json')}),flush=True)
 except BaseException:
  k('patch','deploy','dsh-secure','--type=merge','-p',json.dumps({'spec':original['spec']}));ready()
  print(json.dumps({'phase':'ROLLED_BACK','localOriginalStateRetained':True,'centralCopiesRetained':True}),flush=True);raise

if __name__=='__main__':main()
