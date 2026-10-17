"""Bounded managed-client policy rollout; no model, credential or data migration."""
import argparse,copy,hashlib,json,subprocess,time,uuid
from pathlib import Path
from promote_1m_runtimes import kube,selected,wait

def policy_spec(original,config_name):
    if not selected(original['metadata']['name']):raise ValueError('Not a main private runtime')
    s=copy.deepcopy(original['spec']);p=s['template']['spec'];c=p['containers'][0]
    if s['replicas']!=1 or s['strategy']['type']!='Recreate':raise ValueError('Single writer/Recreate required')
    if c.get('securityContext',{}).get('runAsUser')!=10001:raise ValueError('Non-root runtime required')
    if any(v['name']=='managed-client-policy' for v in p['volumes']):raise ValueError('Policy already mounted; inspect before replacement')
    paths=['/etc/claude-code/managed-settings.json','/opt/dsh/container/trueforge-managed.sh']
    if any(v['mountPath'] in paths for v in c['volumeMounts']):raise ValueError('Conflicting mount')
    p['volumes'].append({'name':'managed-client-policy','configMap':{'name':config_name,'defaultMode':0o444,'items':[{'key':'claude-managed-settings.json','path':'claude-managed-settings.json','mode':0o444},{'key':'trueforge-managed.sh','path':'trueforge-managed.sh','mode':0o555}]}})
    c['volumeMounts'] += [{'name':'managed-client-policy','mountPath':dst,'subPath':src,'readOnly':True} for src,dst in zip(['claude-managed-settings.json','trueforge-managed.sh'],paths)]
    return s

VERIFY=r'''
from pathlib import Path
import json,subprocess,os,hashlib,http.client,time,uuid
expected=json.loads(EXPECTED)
for p,d in expected.items():
 f=Path(p);assert hashlib.sha256(f.read_bytes()).hexdigest()==d
 try:
  fd=os.open(f,os.O_WRONLY);os.close(fd);raise RuntimeError('Policy writable')
 except OSError as e:assert e.errno in (1,13,30), e.errno
p=subprocess.run(['claude','-p','Reply exactly POLICY_1M_OK','--output-format','json','--max-turns','1','--no-session-persistence','--tools',''],capture_output=True,text=True,timeout=90,cwd='/tmp')
d=json.loads(p.stdout);assert p.returncode==0 and d['result'].strip()=='POLICY_1M_OK'
assert any(v['contextWindow']==1000000 for v in d['modelUsage'].values())
assert os.getuid()==10001
host=os.environ['DSH_TRUSTED_HOST'];mode=os.environ['DSH_ENVIRONMENT'];token=Path('/runtime-tokens/'+mode).read_text().strip();cookie=None
for _ in range(20):
 try:
  con=http.client.HTTPConnection('127.0.0.1',3080,timeout=10);con.request('GET','/?token='+token,headers={'Host':host});response=con.getresponse();cookie='; '.join(v.split(';')[0] for k,v in response.getheaders() if k.lower()=='set-cookie');response.read();con.close()
  if cookie:break
 except (ConnectionRefusedError,TimeoutError):pass
 time.sleep(1)
assert cookie,'Runtime login cookie not issued'
con=http.client.HTTPConnection('127.0.0.1',3080,timeout=15);body=json.dumps({'type':'client-request','rpcId':str(uuid.uuid4()),'method':'session/list','payload':{'args':{'_request':{}}}});con.request('POST','/api/session/list',body,headers={'Host':host,'Origin':'http://'+host,'Cookie':cookie,'Content-Type':'application/json'});response=con.getresponse();value=json.load(response);con.close();assert value['result']['ok'] and isinstance(value['result']['value']['items'],list)
print(json.dumps({'runtimeLoginAndSessionList':True,'claudeDefault1M':True,'exact':True,'policyWritesDenied':2,'uid':os.getuid(),'usage':d['usage']}))
'''

def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--names',nargs='+',required=True);a.add_argument('--rollback-dir',type=Path,required=True);a.add_argument('--apply',action='store_true');a=a.parse_args()
 root=Path(__file__).resolve().parents[1];data={p.name:p.read_text(encoding='utf-8') for p in [root/'container/claude-managed-settings.json',root/'container/trueforge-managed.sh']}
 cfg=json.loads(data['claude-managed-settings.json']);assert cfg['model']=='deepseek-v4.1-flash[1m]' and cfg['env']['API_TIMEOUT_MS']=='3600000'
 name='dsh-harness-policy-'+hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]
 cm={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':name,'namespace':'llm'},'immutable':True,'data':data}
 originals=[json.loads(kube('get','deploy',n,'-o','json')) for n in a.names];plans=[policy_spec(o,name) for o in originals]
 print(json.dumps({'plan':a.names,'configMap':name,'apply':a.apply}),flush=True)
 if not a.apply:return
 a.rollback_dir.mkdir(parents=True,exist_ok=False)
 present=json.loads(kube('get','configmap','-o','json'))['items'];match=[x for x in present if x['metadata']['name']==name]
 if match:assert match[0]['data']==data and match[0].get('immutable')
 else:kube('create','-f','-',source=json.dumps(cm))
 expected={dst:hashlib.sha256(data[src].encode()).hexdigest() for src,dst in [('claude-managed-settings.json','/etc/claude-code/managed-settings.json'),('trueforge-managed.sh','/opt/dsh/container/trueforge-managed.sh')]}
 results=[]
 for old,new in zip(originals,plans):
  n=old['metadata']['name'];(a.rollback_dir/(n+'.json')).write_text(json.dumps(old),encoding='utf-8')
  if json.loads(kube('get','deploy',n,'-o','json'))['spec']!=old['spec']:raise RuntimeError('Concurrent deployment change')
  marker='.harness-policy-'+uuid.uuid4().hex
  marker_code="from pathlib import Path;p=[Path('/workspace')/M,Path('/state/attachments')/M];".replace('M',repr(marker))
  kube('exec','-i','deploy/'+n,'--','python3','-',source=marker_code+"[x.write_text('durable') for x in p]")
  try:
   kube('patch','deploy',n,'--type=merge','-p',json.dumps({'spec':new}));wait(n,240)
   v=json.loads(kube('exec','-i','deploy/'+n,'--','python3','-',source=VERIFY.replace('EXPECTED',repr(json.dumps(expected)))))
   kube('exec','-i','deploy/'+n,'--','python3','-',source=marker_code+"assert all(x.read_text()=='durable' for x in p);[x.unlink() for x in p]")
   actual=json.loads(kube('get','deploy',n,'-o','json'))['spec'];assert actual==new
   results.append({'runtime':n,**v,'durableMarkers':2,'originalDataMountsPreserved':all(m in new['template']['spec']['containers'][0]['volumeMounts'] for m in old['spec']['template']['spec']['containers'][0]['volumeMounts'])})
   (a.rollback_dir/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps({'accepted':n}),flush=True)
  except Exception:
   kube('patch','deploy',n,'--type=merge','-p',json.dumps({'spec':old['spec']}));wait(n,240);raise
if __name__=='__main__':main()
