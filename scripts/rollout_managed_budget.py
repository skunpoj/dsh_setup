"""Refresh only managed Node transport/budget overlays on idle main runtimes.

Preserve mounts/profiles; save prior references; verify actual history IDs and
workspace/state markers. Refuse active agents or unexpected source revisions.
"""
import argparse,json,hashlib,subprocess,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def k(*args,code=None):
 p=subprocess.run(['kubectl','--request-timeout=30s','-n','llm',*args],input=code,text=True,encoding='utf-8',capture_output=True,timeout=170)
 if p.returncode:raise RuntimeError(p.stderr[-300:])
 return p.stdout
SNAPSHOT=r'''
import http.client,json,uuid
from pathlib import Path
h='dsh.aiportal.bot.or.th';token=next(p for p in Path('/runtime-tokens').iterdir()if p.is_file()).read_text().strip();c=http.client.HTTPConnection('127.0.0.1',3080,timeout=20);c.request('GET','/?token='+token,headers={'Host':h});r=c.getresponse();cookie='; '.join(v.split(';')[0]for key,v in r.getheaders()if key.lower()=='set-cookie');r.read();c.close();c=http.client.HTTPConnection('127.0.0.1',3080,timeout=30);c.request('POST','/api/session/list',json.dumps({'type':'client-request','rpcId':str(uuid.uuid4()),'method':'session/list','payload':{'args':{'_request':{}}}}),headers={'Host':h,'Origin':'http://'+h,'Cookie':cookie,'Content-Type':'application/json'});r=c.getresponse();v=json.loads(r.read());assert v['result']['ok'];items=v['result']['value']['items'];print(json.dumps({'ids':[i['sessionId']for i in items],'running':sum(bool(i.get('running'))for i in items)}))
'''
BUDGET=r'''import {clampMaxTokensToContext} from '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js';const m={provider:'litellm-cluster',api:'openai-completions',id:'deepseek-v4.1-flash',baseUrl:'http://litellm.llm.svc.cluster.local:4000/v1',contextWindow:1048576,maxTokens:8192};const c={messages:[{role:'user',content:'x'.repeat(5600000)}]};const full=clampMaxTokensToContext(m,c,8192),one=clampMaxTokensToContext(m,c,1);if(full!==8192||one!==1)throw Error('Managed budget mismatch');console.log(JSON.stringify({fullBudget:full,explicitOne:one}));'''
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--expected-transport-sha',required=True);ap.add_argument('--apply',action='store_true');a=ap.parse_args()
 source=(ROOT/'scripts/managed_inference_transport.cjs').read_text(encoding='utf-8');sha=hashlib.sha256(source.encode()).hexdigest();cmname='dsh-managed-transport-'+sha[:12]
 import re
 deployments=[d for d in json.loads(k('get','deploy','-o','json'))['items']if d['metadata']['name']in ['dsh-secure','dsh-internet']or re.fullmatch(r'dsh-u-[0-9a-f]{16}-(secure|internet)',d['metadata']['name'])];assert len(deployments)==20
 deployments.sort(key=lambda d:(d['metadata']['name']in ['dsh-secure','dsh-internet'],d['metadata']['name']))
 for d in deployments:
  assert d['spec']['replicas']==1 and d['spec']['strategy']['type']=='Recreate'
  old=next(v['configMap']['name']for v in d['spec']['template']['spec']['volumes']if v['name']=='context-transport');v=json.loads(k('get','cm',old,'-o','json'));assert hashlib.sha256(v['data']['managed_inference_transport.cjs'].encode()).hexdigest()==a.expected_transport_sha
 print(json.dumps({'runtimeCount':len(deployments),'configMap':cmname,'modelRestartRequired':False}),flush=True)
 if not a.apply:return
 a.output.mkdir(parents=True,exist_ok=False);k('apply','-f','-',code=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':cmname,'namespace':'llm'},'data':{'managed_inference_transport.cjs':source}}));results=[]
 for d in deployments:
  name=d['metadata']['name'];current=json.loads(k('get','deploy',name,'-o','json'));assert current['spec']==d['spec'],'Concurrent runtime change'
  before=json.loads(k('exec','-i','deploy/'+name,'--','python3','-',code=SNAPSHOT));assert not before['running'],'Active user agent: defer rollout'
  (a.output/(name+'-before.json')).write_text(json.dumps(d,indent=2),encoding='utf-8')
  marker='.managed-budget-'+uuid.uuid4().hex
  def durable(create):
   code="from pathlib import Path\nimport json\npaths=[Path('/workspace')/"+repr(marker)+",Path('/state/attachments')/"+repr(marker)+"]\nfor p in paths:\n if "+repr(create)+":\n  with p.open('xb')as f:f.write(b'managed-budget-persistence')\n else:\n  assert p.read_bytes()==b'managed-budget-persistence'\n  p.unlink()\nprint(json.dumps({'markers':2,'survived':"+repr(not create)+"}))"
   return json.loads(k('exec','-i','deploy/'+name,'--','python3','-',code=code))
  durable(True);volumes=d['spec']['template']['spec']['volumes'];idx=next(i for i,v in enumerate(volumes)if v['name']=='context-transport');old=volumes[idx]['configMap']['name'];path=f'/spec/template/spec/volumes/{idx}/configMap/name'
  k('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'test','path':path,'value':old},{'op':'replace','path':path,'value':cmname}]))
  try:
   k('rollout','status','deploy/'+name,'--timeout=120s');result=json.loads(k('exec','deploy/'+name,'--','node','--input-type=module','-e',BUDGET));after=json.loads(k('exec','-i','deploy/'+name,'--','python3','-',code=SNAPSHOT));assert set(before['ids']).issubset(after['ids']),'History IDs missing';persist=durable(False)
  except BaseException:
   k('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'test','path':path,'value':cmname},{'op':'replace','path':path,'value':old}]));k('rollout','status','deploy/'+name,'--timeout=120s');durable(False);raise
  results.append({'name':name,'historyCountBefore':len(before['ids']),'historyCountAfter':len(after['ids']),'allHistoryIDsPreserved':True,'budget':result,'persistence':persist});(a.output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps({'accepted':name}),flush=True)
if __name__=='__main__':main()
