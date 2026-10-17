"""Checkpoint a legacy home, then move execution to a pinned non-root image.

Only dsh-user2/dsh3 are accepted. Existing private PVCs stay in place. Root
checkpoint bytes are compared before/after copying while application writers
are frozen. No credential values are printed or written to evidence.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from datetime import datetime, timezone

from provision_inference_client import provision

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'dsoreg-sm1-p1.bot.or.th/da-gpu-server/dsh-runtime@sha256:595452b9d14f79bc5415795145967df713288f49db5f4699db570bcda4c3c5a6'


def kube(*args, source=None):
    p = subprocess.run(['kubectl','-n','llm','--request-timeout=30s',*args],
                       input=source,text=True,encoding='utf-8',capture_output=True,timeout=360)
    if p.returncode: raise RuntimeError(p.stderr[-500:])
    return p.stdout


CHECKPOINT = r'''
import pathlib,os,signal,shutil,hashlib,json,time
root=pathlib.Path('/root');dest=pathlib.Path('/workspace/.legacy-cutover-checkpoint/root')
if dest.parent.exists():raise RuntimeError('Checkpoint collision')
processes={}
for p in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
 try:
  a=p.read_bytes().split(b'\0');stat=(p.parent/'stat').read_text(encoding='utf-8').rsplit(')',1)[1].split();processes[int(p.parent.name)]=(int(stat[1]),a)
 except (OSError,ValueError):pass
selected={pid for pid,(_,a) in processes.items() if a and ((a[0].endswith(b'node') and b'web' in a) or a[0].endswith(b'ttyd'))}
if len(selected)<2:raise RuntimeError('Expected DSH and terminal processes')
while True:
 more={pid for pid,(parent,_) in processes.items() if parent in selected}-selected
 if not more:break
 selected|=more
def fingerprint(path):
 h=hashlib.sha256();count=0;total=0
 for p in sorted(path.rglob('*')):
  if p.name.endswith('.lock'):continue
  rel=str(p.relative_to(path))
  if p.is_symlink():v=('link:'+os.readlink(p)).encode()
  elif p.is_file():v=hashlib.sha256(p.read_bytes()).digest();count+=1;total+=p.stat().st_size
  else:continue
  h.update(rel.encode()+b'\0'+v)
 return {'files':count,'bytes':total,'sha256':h.hexdigest()}
frozen=[]
try:
 for pid in selected:os.kill(pid,signal.SIGSTOP);frozen.append(pid)
 before=fingerprint(root);sessions=fingerprint(root/'.dsh/sessions')
 if shutil.disk_usage('/workspace').free<before['bytes']*2+134217728:raise RuntimeError('Insufficient checkpoint/home capacity')
 dest.parent.mkdir(mode=0o700);shutil.copytree(root,dest,symlinks=True)
 copied=fingerprint(dest);after=fingerprint(root)
 if before!=copied or before!=after:raise RuntimeError('Checkpoint content mismatch')
 print(json.dumps({'home':before,'sessions':sessions,'frozenPids':frozen,'checkpointVerified':True}))
except BaseException:
 for pid in frozen:
  try:os.kill(pid,signal.SIGCONT)
  except OSError:pass
 raise
'''

INIT = r'''
import pathlib,shutil,os,hashlib,json
source=pathlib.Path('/workspace/.legacy-cutover-checkpoint/root');home=pathlib.Path('/workspace/.legacy-home-v2')
marker=home/'.legacy-migration-complete'
if not marker.exists():
 if home.exists():raise RuntimeError('Partial home exists; operator reconciliation required')
 shutil.copytree(source,home,symlinks=True)
 for p in source.rglob('*'):
  q=home/p.relative_to(source)
  if p.is_symlink():
   if not q.is_symlink() or os.readlink(p)!=os.readlink(q):raise RuntimeError('Home link mismatch')
  elif p.is_file() and hashlib.sha256(p.read_bytes()).digest()!=hashlib.sha256(q.read_bytes()).digest():raise RuntimeError('Home bytes mismatch')
 marker.write_text('verified private home migration\n')
for base,dirs,files in os.walk('/workspace',followlinks=False):
 for p in [pathlib.Path(base),*[pathlib.Path(base)/n for n in dirs+files]]:os.chown(p,10001,10001,follow_symlinks=False)
print(json.dumps({'homeCopyVerified':True,'privateWorkspaceOwner':10001}))
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name',required=True,choices=['dsh-user2','dsh3'])
    ap.add_argument('--apply',action='store_true')
    ap.add_argument('--reuse-checkpoint-from-pod',help='Private diagnostic pod; only for recovery of a saved checkpoint after a verification harness failure')
    ap.add_argument('--rollback-dir',type=Path,required=True)
    a=ap.parse_args();before=json.loads(kube('get','deploy',a.name,'-o','json'))
    owner=next(e['value'] for e in before['spec']['template']['spec']['containers'][0]['env'] if e['name']=='AUTH_USER')
    if not a.apply:print(json.dumps({'name':a.name,'owner':owner,'image':IMAGE,'apply':False}));return
    a.rollback_dir.mkdir(parents=True,exist_ok=False)
    # Rollback bytes may contain historic bootstrap material: keep them in memory.
    password=kube('exec','deploy/'+a.name,'--','node','-e',"process.stdout.write(process.env.AUTH_PASS||'')")
    if not password:raise RuntimeError('No private owner verification credential available')
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'name':a.name,'owner':owner,'image':IMAGE}
    frozen=False;changed=False
    try:
        if a.reuse_checkpoint_from_pod:
            if not a.reuse_checkpoint_from_pod.startswith('dsh2-nonroot-diagnostic-'):
                raise RuntimeError('Unexpected checkpoint verifier')
            kube('get','secret','dsh-inference-legacy-'+owner,'-o','name')
            record['clientKey']={'secret':'dsh-inference-legacy-'+owner,'reused':True}
            fingerprint=CHECKPOINT[CHECKPOINT.index('def fingerprint(path):'):CHECKPOINT.index('frozen=[]')]
            check="import pathlib,hashlib,os,json\n"+fingerprint+"\nroot=pathlib.Path('/workspace/.legacy-cutover-checkpoint/root');a=fingerprint(root/'.dsh/sessions');b=fingerprint(pathlib.Path('/root/.dsh/sessions'));assert a==b;print(json.dumps({'home':fingerprint(root),'sessions':a,'savedCheckpointSessionsMatch':True,'frozenPids':[]}))"
            record['checkpoint']=json.loads(kube('exec','-i',a.reuse_checkpoint_from_pod,'--','python3','-',source=check))
            kube('delete','pod',a.reuse_checkpoint_from_pod,'--wait=true','--timeout=30s')
            record['recoveryNote']='Original candidate rolled back after Windows text-decoding verification failure; saved checkpoint session bytes rechecked before retry.'
        else:
            record['clientKey']=provision('dsh-inference-legacy-'+owner,['deepseek-v4.1-flash','deepseek-flash'])
            record['checkpoint']=json.loads(kube('exec','-i','deploy/'+a.name,'--','python3','-',source=CHECKPOINT));frozen=True
        (a.rollback_dir/'progress.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        new=copy.deepcopy(before['spec']);pod=new['template']['spec'];c=pod['containers'][0]
        old_command='\n'.join(c.get('command',[]));hosts=re.findall(r'--trusted-host ([a-zA-Z0-9.-]+)',old_command)
        c['image']=IMAGE;c['command']=['bash','/legacy-start/start.sh'];c.pop('args',None)
        env={e['name']:e for e in c.get('env',[]) if e['name']!='AUTH_PASS'}
        for key,value in {'HOME':'/root','DSH_HOME':'/root/.dsh','DSH_TRUSTED_HOST_ALIASES':','.join(hosts),'KRB5CCNAME':'FILE:/root/.kerberos/ccache'}.items():env[key]={'name':key,'value':value}
        for key in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','LITELLM_API_KEY']:
            env[key]={'name':key,'valueFrom':{'secretKeyRef':{'name':'dsh-inference-legacy-'+owner,'key':'litellm-api-key'}}}
        c['env']=list(env.values());pod['automountServiceAccountToken']=False
        pod['securityContext']={'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}}
        c['securityContext']={'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True,'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}
        c['resources']={'requests':{'cpu':'250m','memory':'256Mi'},'limits':{'cpu':'2','memory':'4Gi'}}
        script=(ROOT/'container/start-legacy-private.sh').read_text(encoding='utf-8');digest=hashlib.sha256(script.encode()).hexdigest();cm='dsh-legacy-start-'+digest[:12]
        kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':cm,'namespace':'llm'},'data':{'start.sh':script}}))
        pod['volumes']=[v for v in pod['volumes'] if v['name']!='legacy-start']+[{'name':'legacy-start','configMap':{'name':cm}}]
        c['volumeMounts']=[v for v in c['volumeMounts'] if v['mountPath']!='/root']+[{'name':'isolated-local-storage','mountPath':'/root','subPath':'.legacy-home-v2'},{'name':'legacy-start','mountPath':'/legacy-start','readOnly':True}]
        pod['initContainers']=[{'name':'private-home-migration','image':IMAGE,'command':['python3','-c',INIT],
            'securityContext':{'runAsUser':0,'runAsGroup':0,'runAsNonRoot':False,'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL'],'add':['CHOWN','FOWNER','DAC_OVERRIDE']}},
            'resources':{'requests':{'cpu':'100m','memory':'128Mi'},'limits':{'cpu':'1','memory':'1Gi'}},
            'volumeMounts':[{'name':'isolated-local-storage','mountPath':'/workspace'}]}]
        ready="import socket,pathlib;[(socket.create_connection(('127.0.0.1',p),timeout=1).close()) for p in [3080,3081,7681]];assert pathlib.Path('/tmp/dsh_token.txt').stat().st_size>10"
        c['readinessProbe']={'exec':{'command':['python3','-c',ready]},'periodSeconds':5,'timeoutSeconds':5,'failureThreshold':6}
        c['startupProbe']={'exec':{'command':['python3','-c',ready]},'periodSeconds':5,'timeoutSeconds':5,'failureThreshold':60}
        new['strategy']={'type':'Recreate'}
        if password in json.dumps(new):raise RuntimeError('Bootstrap password still present in candidate spec')
        changed=True;kube('patch','deploy',a.name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':new}]))
        kube('rollout','status','deploy/'+a.name,'--timeout=300s')
        probe=(ROOT/'scripts/review_legacy_auth.js').read_text(encoding='utf-8').replace("const users=JSON.parse(fs.readFileSync('/workspace/users/.user_auth.json'));","const users=JSON.parse(fs.readFileSync(0,'utf8'));")
        record['behavior']=json.loads(kube('exec','-i','deploy/'+a.name,'--','node','-e',probe,source=json.dumps({owner:password,'guest':'denied-placeholder','thanatcc':'denied-placeholder'})))
        if not record['behavior']['authenticatedHistoryRpcSucceeded']:raise RuntimeError('History RPC failed')
        terminal=(ROOT/'scripts/verify_terminal_websocket.js').read_text(encoding='utf-8');start=terminal.index('const selectedUser=');end=terminal.index('function request(')
        terminal=terminal[:start]+"const identity=JSON.parse(fs.readFileSync(0,'utf8'));\n"+terminal[end:]
        host=next(e['value'] for e in c['env'] if e['name']=='DSH_TRUSTED_HOST');terminal=terminal.replace('dsh.aiportal.bot.or.th',host).replace("[['off','secure'],['on','internet']]","[['on','internet']]")
        record['terminal']=json.loads(kube('exec','-i','deploy/'+a.name,'--','node','-e',terminal,source=json.dumps({'user':owner,'password':password})))
        state=CHECKPOINT[CHECKPOINT.index('def fingerprint(path):'):CHECKPOINT.index('frozen=[]')]
        state="import pathlib,hashlib,os,json\n"+state+"\nprint(json.dumps(fingerprint(pathlib.Path('/root/.dsh/sessions'))))"
        record['sessionsAfter']=json.loads(kube('exec','-i','deploy/'+a.name,'--','python3','-',source=state))
        if record['sessionsAfter']!=record['checkpoint']['sessions']:raise RuntimeError('Session content changed across cutover')
        code="import os,json,pathlib;print(json.dumps({'uid':os.getuid(),'homeWritable':os.access('/root',os.W_OK),'stateOnWorkspace':os.stat('/root/.dsh').st_dev==os.stat('/workspace').st_dev,'serviceAccountTokenMounted':pathlib.Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists(),'bootstrapPasswordInEnvironment':'AUTH_PASS' in os.environ}))"
        record['execution']=json.loads(kube('exec','-i','deploy/'+a.name,'--','python3','-',source=code));assert record['execution']['uid']==10001 and not record['execution']['serviceAccountTokenMounted'] and not record['execution']['bootstrapPasswordInEnvironment']
        current=json.loads(kube('get','deploy',a.name,'-o','json'))
        annotation=current['metadata'].get('annotations',{}).get('kubectl.kubernetes.io/last-applied-configuration','')
        if password in annotation:
            kube('annotate','deploy',a.name,'kubectl.kubernetes.io/last-applied-configuration-')
        current=json.loads(kube('get','deploy',a.name,'-o','json'))
        if password in json.dumps(current.get('metadata',{})) or password in json.dumps(current['spec']):
            raise RuntimeError('Current deployment still contains the bootstrap password')
        record['currentDeploymentBootstrapCopyRemoved']=True
        record['status']='passed';record['startupConfigMap']=cm
        actual=json.loads(kube('get','deploy',a.name,'-o','json'));record['runningImage']=actual['spec']['template']['spec']['containers'][0]['image']
        # Publish only the credential-free candidate manifest.
        manifest={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':a.name,'namespace':'llm'},'spec':new}
        (a.rollback_dir/'candidate-public.json').write_text(json.dumps(manifest,indent=2)+'\n')
    except Exception as error:
        record['status']='failed';record['error']=str(error)
        (a.rollback_dir/'failure-before-rollback.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        if changed:
            kube('patch','deploy',a.name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':before['spec']}]))
            kube('rollout','status','deploy/'+a.name,'--timeout=300s');record['deploymentRestored']=True
        elif frozen:
            pids=record['checkpoint']['frozenPids'];kube('exec','deploy/'+a.name,'--','python3','-c',"import os,signal;[os.kill(p,signal.SIGCONT) for p in "+repr(pids)+"]")
        raise
    finally:
        password=None
        (a.rollback_dir/'result.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)


if __name__=='__main__':main()
