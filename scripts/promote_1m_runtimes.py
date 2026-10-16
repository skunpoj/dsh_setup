"""Upgrade only existing private runtime pairs; preserve mounts and private rollback.

The previous profile is backed up inside its own PVC before startup changes it.
Rollback restores that exact profile before starting the old image. No histories
or workspace trees are copied, deleted or reassigned.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

IMAGE='dsoreg-sm1-p1.bot.or.th/da-gpu-server/dsh-runtime@sha256:87bc12dd5c2419e640c11358881f01709944a259498cf38a699fcc57d037e1a3'

def kube(*args, source=None):
    p=subprocess.run(['kubectl','-n','llm','--request-timeout=30s',*args],input=source,text=True,encoding='utf8',capture_output=True,timeout=90)
    if p.returncode: raise RuntimeError(p.stderr[-500:])
    return p.stdout

def selected(name):
    return name in ['dsh-secure','dsh-internet'] or bool(re.fullmatch(r'dsh-u-[0-9a-f]{16}-(secure|internet)',name))

def profile_init(container, tag, restore=False):
    script="""
from pathlib import Path
import hashlib,json,os
root=Path('/state/.context-upgrade-backup/TAG')
profile=Path('/state/profiles/web/cordis.patch.yml')
RESTORE
""".replace('TAG',tag)
    action="""root.mkdir(parents=True,exist_ok=False,mode=0o700)
original=profile.read_bytes()
(root/'profile.yml').write_bytes(original)
os.chmod(root/'profile.yml',0o600)
(root/'sha256').write_text(hashlib.sha256(original).hexdigest())
assert (root/'profile.yml').read_bytes()==original
"""
    if restore:
        action="""original=(root/'profile.yml').read_bytes()
assert hashlib.sha256(original).hexdigest()==(root/'sha256').read_text()
tmp=profile.with_suffix('.rollback.tmp')
tmp.write_bytes(original);os.chmod(tmp,0o600);os.replace(tmp,profile)
assert profile.read_bytes()==original
"""
    state=next(m for m in container['volumeMounts'] if m['mountPath']=='/state')
    return {'name':'context-profile-restore' if restore else 'context-profile-backup',
        'image':container['image'],'command':['python3','-c',script.replace('RESTORE',action)],
        'volumeMounts':[copy.deepcopy(state)],'securityContext':copy.deepcopy(container.get('securityContext',{}))}

def candidate(original, tag):
    spec=copy.deepcopy(original['spec'])
    if spec.get('replicas')!=1 or spec['strategy']['type']!='Recreate':raise ValueError('Single writer/Recreate required')
    pod=spec['template']['spec']
    if pod.get('initContainers'):raise ValueError('Unexpected existing init container')
    c=pod['containers'][0]
    pod['initContainers']=[profile_init(c,tag)]
    c['image']=IMAGE
    c['env']=[e for e in c.get('env',[]) if e['name']!='DSH_CONTEXT_TOKENS']+[{'name':'DSH_CONTEXT_TOKENS','value':'1048576'}]
    spec['template']['metadata'].setdefault('annotations',{})['dsh.bot.or.th/context-rollout']=tag
    assert pod['volumes']==original['spec']['template']['spec']['volumes']
    assert c['volumeMounts']==original['spec']['template']['spec']['containers'][0]['volumeMounts']
    return spec

def wait(name,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        d=json.loads(kube('get','deploy',name,'-o','json'));s=d.get('status',{})
        if s.get('observedGeneration',0)>=d['metadata']['generation'] and all(s.get(k)==1 for k in ['updatedReplicas','availableReplicas','readyReplicas','replicas']):return d
        time.sleep(3)
    raise RuntimeError('Runtime readiness deadline exceeded: '+name)

PROFILE=r"""
const fs=require('fs');const YAML=require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
const p=YAML.parse(fs.readFileSync('/state/profiles/web/cordis.patch.yml','utf8'));
const provider=p.find(x=>x.id==='llm-pi-ai').config.providers['litellm-cluster'];
const models=provider.models.filter(x=>['deepseek-v4.1-flash','deepseek-flash'].includes(x.id)).map(x=>({id:x.id,context:x.contextWindow,output:x.maxTokens}));
const comp=p.find(x=>x.id==='compaction-basic');
if(models.length!==2||models.some(x=>x.context!==1048576||x.output!==8192)||!comp.config.auto||comp.disabled)throw Error('Runtime policy mismatch');
console.log(JSON.stringify({models,compaction:comp.config.modelPolicies.filter(x=>x.provider==='litellm-cluster'),timeoutMs:provider.timeoutMs}));
"""

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply',action='store_true');ap.add_argument('--names',nargs='*')
    ap.add_argument('--rollback-dir',type=Path,required=True)
    args=ap.parse_args();tag='context1m-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    ds=json.loads(kube('get','deploy','-o','json'))['items']
    ds=[d for d in ds if selected(d['metadata']['name']) and (not args.names or d['metadata']['name'] in args.names)]
    if args.names and len(ds)!=len(set(args.names)):raise ValueError('Unknown or excluded runtime requested')
    if not ds:raise ValueError('No runtime selected')
    # Test a private account first, thanatcc legacy runtime last.
    ds.sort(key=lambda d:(d['metadata']['name'] in ['dsh-secure','dsh-internet'],d['metadata']['name']))
    print(json.dumps({'plan':[d['metadata']['name'] for d in ds],'image':IMAGE,'preserveAllMounts':True}),flush=True)
    if not args.apply:return
    gateway=json.loads(kube('get','deploy','litellm','-o','json'))
    if not any(c['name']=='context-forwarder' for c in gateway['spec']['template']['spec']['containers']):raise ValueError('Promote qualified proxy first')
    args.rollback_dir.mkdir(parents=True,exist_ok=False)
    results=[]
    for original in ds:
        name=original['metadata']['name'];new=candidate(original,tag)
        (args.rollback_dir/(name+'.json')).write_text(json.dumps(original,indent=2))
        current=json.loads(kube('get','deploy',name,'-o','json'))
        if current['spec']!=original['spec']:raise RuntimeError('Concurrent change; refuse '+name)
        try:
            kube('patch','deploy',name,'--type=merge','-p',json.dumps({'spec':new}))
            live=wait(name)
            actual=json.loads(kube('exec','deploy/'+name,'--','node','-e',PROFILE))
            pods=json.loads(kube('get','pods','-l','app='+name,'-o','json'))['items']
            image_ids=[s['imageID'] for p in pods for s in p.get('status',{}).get('containerStatuses',[]) if s['name']==live['spec']['template']['spec']['containers'][0]['name']]
            if len(image_ids)!=1 or IMAGE.split('@')[1] not in image_ids[0]:raise RuntimeError('Running image differs')
            result={'name':name,'imageID':image_ids[0],'policy':actual,'mountsUnchanged':True,'profileBackup':tag}
            results.append(result);print(json.dumps({'promoted':name,'context':1048576}),flush=True)
            (args.rollback_dir/'results.json').write_text(json.dumps(results,indent=2))
        except Exception:
            restore=copy.deepcopy(original['spec'])
            restore['template']['spec']['initContainers']=[profile_init(original['spec']['template']['spec']['containers'][0],tag,True)]
            kube('patch','deploy',name,'--type=merge','-p',json.dumps({'spec':restore}))
            wait(name)
            print(json.dumps({'rolledBack':name,'priorPromotionsPreserved':len(results)}),flush=True)
            raise

if __name__=='__main__':main()
