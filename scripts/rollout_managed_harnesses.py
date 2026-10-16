"""Roll out only qualified main DSH runtimes; preserve all existing data mounts."""
import argparse,copy,json,uuid
from pathlib import Path
from promote_1m_runtimes import kube,selected,wait,PROFILE
from provision_harness_credentials import provision

def specification(original,image,secret):
    spec=copy.deepcopy(original['spec']);p=spec['template']['spec'];c=p['containers'][0]
    if spec['replicas']!=1 or spec['strategy']['type']!='Recreate':raise ValueError('Single writer required')
    if any(v['name']=='harness-credentials' for v in p['volumes']):raise ValueError('Already provisioned')
    c['image']=image
    p['volumes'].append({'name':'harness-credentials','secret':{'secretName':secret,'defaultMode':0o440}})
    c['volumeMounts'].append({'name':'harness-credentials','mountPath':'/harness-credentials','readOnly':True})
    return spec

VERIFY=r'''
import json,subprocess,os,urllib.request
from pathlib import Path
v=subprocess.check_output(['claude','--version'],text=True).strip();assert v.startswith('2.1.301 ')
t=subprocess.check_output(['trueforge','--help'],text=True);assert '0.179.2' in t
p=Path('/etc/claude-code/managed-settings.json');cfg=json.loads(p.read_text())
assert cfg['allowedProviders']==['customEndpoint'] and cfg['availableModels']==['deepseek-v4.1-flash']
blocked=[]
for f in [p,Path('/opt/dsh/container/managed_trueforge_store.mjs')]:
 try:
  fd=os.open(f,os.O_WRONLY);os.close(fd)
 except PermissionError:blocked.append(str(f))
assert len(blocked)==2
key=Path('/harness-credentials/api-key').read_text().strip()
body={'model':'deepseek-v4.1-flash','max_tokens':128,'thinking':{'type':'disabled'},'messages':[{'role':'user','content':'Reply exactly HARNESS_RUNTIME_OK'}]}
req=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/messages',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=40) as r:
 d=json.load(r);assert ''.join(x.get('text','') for x in d['content']).strip()=='HARNESS_RUNTIME_OK'
assert Path('/home/dsh/.claude').resolve()==Path('/state/claude')
print(json.dumps({'claude':v,'trueforge':'0.179.2','operatorPolicyWritesDenied':len(blocked),'inferenceExact':True,'privateClaudeState':True}))
'''

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--image',required=True);ap.add_argument('--rollback-dir',type=Path,required=True);ap.add_argument('--names',nargs='*');ap.add_argument('--apply',action='store_true');a=ap.parse_args()
    if '@sha256:' not in a.image:raise ValueError('Immutable candidate digest required')
    ds=[d for d in json.loads(kube('get','deploy','-o','json'))['items'] if selected(d['metadata']['name']) and (not a.names or d['metadata']['name'] in a.names)]
    if a.names and len(ds)!=len(set(a.names)):raise ValueError('Unknown or excluded runtime')
    ds.sort(key=lambda d:(d['metadata']['name'] in ['dsh-secure','dsh-internet'],d['metadata']['name']))
    print(json.dumps({'plan':[d['metadata']['name'] for d in ds],'image':a.image}),flush=True)
    if not a.apply:return
    a.rollback_dir.mkdir(parents=True,exist_ok=False);results=[];marker='.harness-rollout-'+uuid.uuid4().hex
    for old in ds:
        name=old['metadata']['name'];secret='dsh-harness-'+name.removeprefix('dsh-')
        credential=provision(secret)
        new=specification(old,a.image,secret)
        (a.rollback_dir/(name+'.json')).write_text(json.dumps(old))
        if json.loads(kube('get','deploy',name,'-o','json'))['spec']!=old['spec']:raise RuntimeError('Concurrent deployment change')
        def markers(create):
            code="from pathlib import Path;import json;paths=[Path('/workspace')/MARKER,Path('/state/attachments')/MARKER];".replace('MARKER',repr(marker))
            code+= "[p.write_text('durable') for p in paths];print(2)" if create else "assert all(p.read_text()=='durable' for p in paths);[p.unlink() for p in paths];print(2)"
            return int(kube('exec','-i','deploy/'+name,'--','python3','-',source=code))
        markers(True)
        try:
            kube('patch','deploy',name,'--type=merge','-p',json.dumps({'spec':new}));wait(name,240)
            test=json.loads(kube('exec','-i','deploy/'+name,'--','python3','-',source=VERIFY))
            profile=json.loads(kube('exec','-i','deploy/'+name,'--','node','-',source=PROFILE))
            assert markers(False)==2
            actual=json.loads(kube('get','pods','-l','app='+name,'-o','json'))['items']
            running=[p for p in actual if not p['metadata'].get('deletionTimestamp')]
            result={'runtime':name,**test,'credential':credential,'context':profile,'durableMarkers':2,
                    'imageIDs':[s['imageID'] for p in running for s in p['status']['containerStatuses']]}
            results.append(result);(a.rollback_dir/'results.json').write_text(json.dumps(results,indent=2));print(json.dumps({'accepted':name}),flush=True)
        except Exception:
            kube('patch','deploy',name,'--type=merge','-p',json.dumps({'spec':old['spec']}));wait(name,240);raise

if __name__=='__main__':main()
