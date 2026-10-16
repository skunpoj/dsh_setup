"""Actual DSH/LiteLLM five-minute boundary test with a delayed synthetic server.

No inference or real user data. This tests transport timeouts, not model quality.
"""
import copy
import json
from pathlib import Path
import subprocess
import time
import yaml

def kube(*args,source=None):
    p=subprocess.run(['kubectl','-n','llm',*args],input=source,text=True,capture_output=True,timeout=450)
    if p.returncode:raise RuntimeError(p.stderr[-800:])
    return p.stdout

STUB='''import asyncio,json
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse
app=FastAPI()
@app.post('/v1/chat/completions')
async def complete(request:Request):
 body=await request.json()
 await asyncio.sleep(315)
 async def stream():
  for choice in [{'delta':{'role':'assistant','content':'DSH_LONG_CONTEXT_OK'},'index':0,'finish_reason':None},{'delta':{},'index':0,'finish_reason':'stop'}]:
   yield 'data: '+json.dumps({'id':'delayed-transport-fixture','object':'chat.completion.chunk','created':1,'model':'deepseek-v4.1-flash','choices':[choice]})+'\\n\\n'
  yield 'data: '+json.dumps({'id':'delayed-transport-fixture','object':'chat.completion.chunk','created':1,'model':'deepseek-v4.1-flash','choices':[],'usage':{'prompt_tokens':1,'completion_tokens':8,'total_tokens':9}})+'\\n\\n'
  yield 'data: [DONE]\\n\\n'
 return StreamingResponse(stream(),media_type='text/event-stream')
'''

def main():
    name='litellm-timeout-fixture'
    if kube('get','pod',name,'--ignore-not-found','-o','name').strip():raise ValueError('Existing fixture; inspect first')
    p=json.loads(kube('get','pod','litellm-1m-canary','-o','json'))
    cm=json.loads(kube('get','cm','litellm-1m-canary','-o','json'))['data']
    config=yaml.safe_load(cm['config.yaml'])
    config['litellm_settings'].pop('callbacks',None)
    for r in config['model_list']:
        r['litellm_params'].update(api_base='http://127.0.0.1:4002/v1',timeout=3600,stream_timeout=3600)
    data={'config.yaml':yaml.safe_dump(config),'delayed_backend.py':STUB}
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':name},'data':data}))
    spec=copy.deepcopy(p['spec']);spec['volumes'][0]['configMap']['name']=name
    side=spec['containers'][1];side['command']=['python','-m','uvicorn','delayed_backend:app','--app-dir','/etc/litellm','--host','127.0.0.1','--port','4002']
    side['env']=[e for e in side['env'] if e['name']!='DSH_CAPTURE_SYNTHETIC_ENVELOPE']
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'labels':p['metadata']['labels']},'spec':spec}))
    kube('wait','--for=condition=Ready','pod/'+name,'--timeout=120s')
    ip=json.loads(kube('get','pod',name,'-o','json'))['status']['podIP']
    dp=json.loads(kube('get','pod','dsh-1m-image-canary','-o','json'));d=copy.deepcopy(dp['spec'])
    # Replace only the numeric endpoint in the canary's seed script.
    import re
    d['initContainers'][0]['command'][2]=re.sub(r'http://[0-9.]+:4000',f'http://{ip}:4000',d['initContainers'][0]['command'][2])
    dn='dsh-timeout-fixture'
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'Pod','metadata':{'name':dn,'labels':dp['metadata']['labels']},'spec':d}))
    kube('wait','--for=condition=Ready','pod/'+dn,'--timeout=120s')
    time.sleep(5)
    source="import sys;sys.argv=['probe','--deadline','420']\n"+Path(__file__).with_name('probe_dsh_1m_agent.py').read_text()
    result=json.loads(kube('exec','-i',dn,'--','python3','-',source=source))
    retries=[e for e in result.get('events',[]) if e['type']=='llm/retry']
    record={'scope':'Delayed synthetic HTTP/SSE transport; no GPU/model inference','upstreamDelaySeconds':315,
        'litellmTimeoutSeconds':3600,'litellmStreamTimeoutSeconds':3600,'dshTimeoutMs':3600000,
        'retryCount':len(retries),'result':result}
    Path('docs/context-evidence/dsh-five-minute-transport-fixture-20261016.json').write_text(json.dumps(record,indent=2))
    assert result['expectedTextPresent'] and result['persistedPromptMatches'] and result['elapsedSeconds']>=315 and not retries
    print(json.dumps({k:v for k,v in record.items() if k!='result'}))

if __name__=='__main__':main()
