"""Replace the admin execution pools' model-master credential with inference-only.

Does not rotate the shared LiteLLM master or change other applications. Rollback
values stay in process memory; no credential backups are left inside workers.
"""
import argparse
import base64
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from run_isolation_canary import legacy_fingerprint


def kube(*args,data=None):
    p=subprocess.run(['kubectl','--request-timeout=30s','-n','llm',*args],input=data,text=True,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.strip())
    return p.stdout


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--secret',required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    new=json.loads(kube('get','secret',args.secret,'-o','json'))['data']['litellm-api-key']
    old=json.loads(kube('get','secret','dsh-runtime-secrets','-o','json'))['data']['litellm-api-key']
    current=base64.b64decode(old).decode();replacement=base64.b64decode(new).decode()
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'legacyBefore':legacy_fingerprint(),
            'credentialValuesExported':False,'sharedMasterRotated':False,'pools':[]}
    originals={};modified=[]
    replace=r'''
import sys,json,os,hashlib
from pathlib import Path
pair=json.load(sys.stdin);p=Path('/state/.credentials.yaml');count=0
if p.exists():
 before=p.read_text();count=before.count(pair['old'])
 if count:
  after=before.replace(pair['old'],pair['new']);temp=p.with_suffix('.yaml.client-key.tmp')
  temp.write_text(after);temp.chmod(0o600);os.replace(temp,p)
print(json.dumps({'literalCredentialOccurrencesReplaced':count}))
'''
    try:
        for name in ['dsh-secure','dsh-internet']:
            d=json.loads(kube('get','deploy',name,'-o','json'));originals[name]=d
            (args.output/(name+'-before.json')).write_text(json.dumps(d,indent=2),encoding='utf-8')
            change=json.loads(kube('exec','-i','deploy/'+name,'--','python3','-c',replace,data=json.dumps({'old':current,'new':replacement})))
            modified.append(name)
            template=json.loads(json.dumps(d['spec']['template']))
            for e in template['spec']['containers'][0]['env']:
                if e['name']=='DEEPSEEK_API_KEY':
                    e.pop('value',None);e['valueFrom']={'secretKeyRef':{'name':args.secret,'key':'litellm-api-key'}}
            kube('patch','deploy',name,'--type=merge','-p',json.dumps({'spec':{'template':template}}))
            kube('rollout','status','deploy/'+name,'--timeout=180s')
            verify=r'''
import os,json,urllib.request,urllib.error
from pathlib import Path
old=__import__('sys').stdin.read();key=os.environ['DEEPSEEK_API_KEY'];assert key!=old
assert all(old not in p.read_text(errors='ignore') for p in list(Path('/state').glob('*.yaml'))+list(Path('/state').glob('*.yml')))
base='http://litellm.llm.svc.cluster.local:4000'
req=urllib.request.Request(base+'/key/list',headers={'Authorization':'Bearer '+key})
try:urllib.request.urlopen(req,timeout=15);raise RuntimeError('Execution worker could administer LiteLLM')
except urllib.error.HTTPError as e:assert e.code in (401,403);denied=e.code
req=urllib.request.Request(base+'/v1/chat/completions',data=json.dumps({'model':'deepseek-v4.1-flash',
 'messages':[{'role':'user','content':'Reply exactly RESTRICTED_RUNTIME_OK'}],'max_tokens':32,'temperature':0,
 'chat_template_kwargs':{'enable_thinking':False}}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=30) as r:answer=json.load(r)
assert answer['choices'][0]['message']['content'].strip()=='RESTRICTED_RUNTIME_OK'
print(json.dumps({'runtimeKeyIsNotMaster':True,'noMasterInRootConfig':True,'administrationDenied':denied,'inferenceExact':True}))
'''
            checked=json.loads(kube('exec','-i','deploy/'+name,'--','python3','-c',verify,data=current))
            record['pools'].append({'name':name,**change,**checked})
        record['legacyAfter']=legacy_fingerprint();assert record['legacyBefore']==record['legacyAfter'];record['status']='passed'
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        for name in modified:
            kube('exec','-i','deploy/'+name,'--','python3','-c',replace,data=json.dumps({'old':replacement,'new':current}))
            kube('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':originals[name]['spec']}]))
            kube('rollout','status','deploy/'+name,'--timeout=180s')
        record['specificationsRestored']=True;raise
    finally:
        del current,replacement,old,new
        (args.output/'admin-inference-restriction-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record),flush=True)


if __name__=='__main__':main()
