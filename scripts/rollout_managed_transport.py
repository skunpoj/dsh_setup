"""Apply the qualified internal-origin transport deadline without changing data.

Repairs the retained profile-backup init to be restart-idempotent. Rollback
removes this transport overlay while retaining that independent startup repair.
"""
import argparse
import copy
import hashlib
import json
import uuid
from pathlib import Path
from promote_1m_runtimes import kube, selected, profile_init, wait

def specification(original,name):
    spec=copy.deepcopy(original['spec']);p=spec['template']['spec'];c=p['containers'][0]
    if spec['replicas']!=1 or spec['strategy']['type']!='Recreate':raise ValueError('Single-writer runtime required')
    tag=spec['template']['metadata']['annotations']['dsh.bot.or.th/context-rollout']
    if [i['name'] for i in p.get('initContainers',[])]!=['context-profile-backup']:raise ValueError('Unexpected initializer')
    p['initContainers']=[profile_init({**c,'image':p['initContainers'][0]['image']},tag)]
    rollback=copy.deepcopy(spec)
    if any(v['name']=='context-transport' for v in p['volumes']):raise ValueError('Transport overlay already present')
    old=next((e for e in c.get('env',[]) if e['name']=='NODE_OPTIONS'),None)
    if old:raise ValueError('Existing NODE_OPTIONS requires explicit review')
    p['volumes'].append({'name':'context-transport','configMap':{'name':name}})
    c['volumeMounts'].append({'name':'context-transport','mountPath':'/context-runtime','readOnly':True})
    c['env'] += [{'name':'NODE_OPTIONS','value':'--require /context-runtime/managed_inference_transport.cjs'},
                  {'name':'DSH_MANAGED_TRANSPORT','value':'1'}]
    return spec,rollback

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--acceptance',type=Path,required=True);ap.add_argument('--rollback-dir',type=Path,required=True);ap.add_argument('--apply',action='store_true');args=ap.parse_args()
    a=json.loads(args.acceptance.read_text(encoding='utf8'))
    if not(a['managedNodeTransport'] and a['retryCount']==0 and a['result']['expectedTextPresent'] and a['result']['elapsedSeconds']>=315):raise ValueError('Actual delayed transport acceptance required')
    code=Path(__file__).with_name('managed_inference_transport.cjs').read_text(encoding='utf8');digest=hashlib.sha256(code.encode()).hexdigest();name='dsh-managed-transport-'+digest[:12]
    ds=[d for d in json.loads(kube('get','deploy','-o','json'))['items'] if selected(d['metadata']['name'])]
    ds.sort(key=lambda d:(d['metadata']['name'] in ['dsh-secure','dsh-internet'],d['metadata']['name']))
    changes=[(d,*specification(d,name)) for d in ds]
    print(json.dumps({'runtimeCount':len(changes),'configMap':name,'origin':'http://litellm.llm.svc.cluster.local:4000','dataMountsPreserved':True}),flush=True)
    if not args.apply:return
    args.rollback_dir.mkdir(parents=True,exist_ok=False)
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':name},'data':{'managed_inference_transport.cjs':code}}))
    results=[]
    marker='.context-transport-'+uuid.uuid4().hex
    def persistence(n,create):
        source="""from pathlib import Path
import json
paths=[Path('/workspace')/MARKER,Path('/state/attachments')/MARKER]
for p in paths:
 if CREATE:
  with p.open('xb') as f:f.write(IDENTITY.encode())
 else:
  assert p.read_text()==IDENTITY
  p.unlink()
print(json.dumps({'markers':len(paths),'survived':not CREATE}))
""".replace('MARKER',repr(marker)).replace('IDENTITY',repr(n)).replace('CREATE',repr(create))
        return json.loads(kube('exec','-i','deploy/'+n,'--','python3','-',source=source))
    for original,new,rollback in changes:
        n=original['metadata']['name'];(args.rollback_dir/(n+'.json')).write_text(json.dumps({'original':original,'workingRollbackSpec':rollback},indent=2))
        if json.loads(kube('get','deploy',n,'-o','json'))['spec']!=original['spec']:raise RuntimeError('Concurrent deployment change')
        persistence(n,True)
        try:
            kube('patch','deploy',n,'--type=merge','-p',json.dumps({'spec':new}));wait(n)
            result=json.loads(kube('exec','deploy/'+n,'--','node','-e',"const fs=require('fs'),crypto=require('crypto');console.log(JSON.stringify({enabled:process.env.DSH_MANAGED_TRANSPORT==='1',sha256:crypto.createHash('sha256').update(fs.readFileSync('/context-runtime/managed_inference_transport.cjs')).digest('hex')}));"))
            if not result['enabled'] or result['sha256']!=digest:raise RuntimeError('Running transport source mismatch')
            durable=persistence(n,False)
            results.append({'name':n,**result,'dataMountsPreserved':True,'restartSafeBackupInit':True,'persistence':durable});print(json.dumps({'transportAccepted':n}),flush=True)
            (args.rollback_dir/'results.json').write_text(json.dumps(results,indent=2))
        except Exception:
            kube('patch','deploy',n,'--type=merge','-p',json.dumps({'spec':rollback}));wait(n);raise

if __name__=='__main__':main()
