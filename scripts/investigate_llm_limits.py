"""Read-only LLM configuration and isolated callback investigation.

Does not send oversized inference, change runtime settings, or read histories.
Only allowlisted configuration fields and synthetic callback results are saved.
"""
import argparse
import concurrent.futures
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import yaml


def kube(*args, source=None):
    p = subprocess.run(['kubectl', '--request-timeout=25s', '-n', 'llm', *args],
                       input=source, text=True, encoding='utf-8', capture_output=True, timeout=90)
    if p.returncode:
        raise RuntimeError('Kubernetes read/probe failed: ' + p.stderr[:300])
    return p.stdout


PROFILE = r'''
import json,re,hashlib,pathlib
p=pathlib.Path('/state/cordis.patch.yml')
t=p.read_text() if p.exists() else ''
fields=[]
for line in t.splitlines():
 if re.match(r'\s*(contextWindow|maxTokens|thresholdRatio|headroomTokens|retainRatio|auto):',line):
  fields.append(line.strip())
profileFiles=[]
for f in [pathlib.Path('/state/profiles/web/cordis.yml'),pathlib.Path('/state/profiles/web/cordis.patch.yml')]:
 if not f.exists():continue
 text=f.read_text();selected=[]
 for line in text.splitlines():
  if re.match(r'\s*(- )?(id|contextWindow|maxTokens|thresholdRatio|headroomTokens|retainRatio|auto|provider|model|disabled):',line):
   selected.append(line)
 profileFiles.append({'path':str(f),'sha256':hashlib.sha256(text.encode()).hexdigest(),'allowlistedLines':selected})
root=pathlib.Path('/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai')
code=(root/'dsh-compaction-basic/lib/index.js').read_text()
patterns=['const headroomTokens = config.headroomTokens ?? 65536;',
 'const thresholdTokens = Math.floor(Math.min(contextWindow * policy.thresholdRatio, pressureBudgetTokens));',
 'const messageBudgetTokens = contextWindow - reservedCompletionTokens;',
 'const pressureBudgetTokens = messageBudgetTokens - policy.headroomTokens;']
print(json.dumps({'profileExists':p.exists(),'profileSha256':hashlib.sha256(t.encode()).hexdigest(),
 'budgetFields':fields,'webProfileFiles':profileFiles,'compactionSourceSha256':hashlib.sha256(code.encode()).hexdigest(),
 'compactionFormulaVerified':all(x in code for x in patterns)}))
'''

CALLBACK = r'''
import asyncio,hashlib,importlib.util,json,pathlib
p=pathlib.Path('/etc/litellm/custom_callbacks.py')
s=importlib.util.spec_from_file_location('review_callback',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
async def probe():
 c=m.DynamicContextClamper();rows=[]
 original=m.litellm.token_counter
 try:
  for name,data in [
   ('ordinary',{'messages':[{'role':'user','content':'hello'}],'max_tokens':65536}),
   ('tool-schema',{'messages':[{'role':'user','content':'hello'}],'tools':[{'type':'function','function':{'name':'example','description':'synthetic '*1000,'parameters':{'type':'object','properties':{}}}}],'max_tokens':65536}),
   ('responses-shape',{'input':'hello','max_output_tokens':65536}),
   ('max-completion-alias',{'messages':[{'role':'user','content':'hello'}],'max_completion_tokens':65536})]:
   calls=[]
   def count(**kwargs):
    calls.append({'keys':sorted(kwargs),'model':kwargs.get('model')});return 1000
   m.litellm.token_counter=count
   result=await c.async_pre_call_hook(None,None,data,None)
   rows.append({'case':name,'counterCalls':calls,'maxTokens':result.get('max_tokens'),
    'maxCompletionTokens':result.get('max_completion_tokens'),'maxOutputTokens':result.get('max_output_tokens')})
  m.litellm.token_counter=original
  counts={}
  for name,content in [('latin','hello world '*100),('thai','ภาษาไทย '*100),('json','{"name":"sample","value":123},'*100)]:
   try:counts[name]={'tokens':original(model='deepseek-flash',messages=[{'role':'user','content':content}])}
   except Exception as e:counts[name]={'errorType':type(e).__name__}
  config=pathlib.Path('/etc/litellm/config.yaml').read_text()
  print(json.dumps({'callbackSha256':hashlib.sha256(p.read_bytes()).hexdigest(),
   'limits':{k:getattr(m,k,None) for k in ['MAX_CONTEXT_TOKENS','MAX_OUTPUT_TOKENS','SAFETY_BUFFER_TOKENS']},
   'callbackReferencedInConfig':'custom_callbacks.proxy_handler_instance' in config,
   'isolatedSyntheticCases':rows,'installedCounterSamples':counts,
   'scope':'Isolated callback object in installed gateway image; no inference and no production hook mutation'}))
 finally:m.litellm.token_counter=original
asyncio.run(probe())
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    deployments=json.loads(kube('get','deployments','-o','json'))['items']
    pods=json.loads(kube('get','pods','-o','json'))['items']
    names=sorted(d['metadata']['name'] for d in deployments if
                 d['metadata']['name'] in ['dsh-secure','dsh-internet'] or
                 d['metadata']['name'].startswith('dsh-u-'))
    def profile(name):
        return {'deployment':name,**json.loads(kube('exec','-i','deploy/'+name,'--','python3','-',source=PROFILE))}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        profiles=list(pool.map(profile,names))
    services=[]
    for name in ['litellm','vllm-deepseek-v4-1-flash']:
        d=next(d for d in deployments if d['metadata']['name']==name)
        containers=d['spec']['template']['spec']['containers']
        matching=[p for p in pods if all(p['metadata'].get('labels',{}).get(k)==v for k,v in d['spec']['selector']['matchLabels'].items())]
        services.append({'deployment':name,'images':[c['image'] for c in containers],
         'publicBudgetArgs':{a:c['args'][i+1] if i+1<len(c['args']) and not c['args'][i+1].startswith('--') else True
            for c in containers for i,a in enumerate(c.get('args',[])) if
            any(x in a for x in ['context-length','mem-fraction','max-running','prefill','decode','mixed-chunk'])},
         'pods':[{'name':p['metadata']['name'],'containers':[{'imageID':c.get('imageID'),'restarts':c.get('restartCount')} for c in p.get('status',{}).get('containerStatuses',[])]} for p in matching]})
    callback=json.loads(kube('exec','-i','deploy/litellm','--','python','-',source=CALLBACK))
    source=Path(__file__).resolve().parent/'litellm_custom_callbacks.py'
    callback['matchesRepositoryBytes']=hashlib.sha256(source.read_bytes()).hexdigest()==callback['callbackSha256']
    callback['matchesRepositoryNormalizedText']=hashlib.sha256(source.read_text().encode()).hexdigest()==callback['callbackSha256']
    callback['liveErrorMentions1M']='1M context budget' in kube('exec','deploy/litellm','--','cat','/etc/litellm/custom_callbacks.py')
    compositions=[]
    for name in ['dsh-secure','dsh-u-8c6976e5b5410415-secure']:
        raw=kube('exec','deploy/'+name,'--','dsh','--profile','web','--dump-config')
        # BaseLoader treats tagged expressions as text; none is evaluated.
        tree=yaml.load(raw,Loader=yaml.BaseLoader)
        selected=[]
        def walk(value,path=''):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k in ['contextWindow','maxTokens','thresholdRatio','headroomTokens','retainRatio','auto']:
                        selected.append({'path':path+'/'+k,'value':v})
                    walk(v,path+'/'+str(value.get('id',k)))
            elif isinstance(value,list):
                for i,v in enumerate(value):walk(v,path+'/'+str(i))
        walk(tree)
        compositions.append({'deployment':name,'selectedFields':selected,
            'note':'Boot-free config dump; launcher rewrites its existing empty root config, no server or history is started'})
    compact_js=r'''
const fs=require('fs');
const s=fs.readFileSync('/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-compaction-basic/lib/index.js','utf8');
const f=s.slice(s.indexOf('function resolveCompactSpec('),s.indexOf('/** Choose an explicit retention form'));
const resolve=new Function('deepFreeze','TargetPressureConfigError',f+';return resolveCompactSpec;')(x=>x,Error);
const policy={target:{provider:'litellm-cluster',model:'deepseek-v4.1-flash'},thresholdRatio:.75,headroomTokens:65536,retainRatio:.16,maxTokens:65536,compactionRetries:1,maxOverflowRetries:1};
console.log(JSON.stringify({scope:'Extracted installed pure budget function; no session compaction',defaultOutput:resolve(policy,131072,8192),smallerOutput:resolve(policy,131072,4096)}));
'''
    compaction=json.loads(kube('exec','-i','deploy/dsh-secure','--','node','-',source=compact_js))
    scheduler=kube('exec','deploy/vllm-deepseek-v4-1-flash','--','python3','-c',
        "from pathlib import Path;import hashlib,json;p=Path('/sgl-workspace/sglang/python/sglang/srt/managers/scheduler.py');s=p.read_bytes();print(json.dumps({'sha256':hashlib.sha256(s).hexdigest(),'v2Marker':b'BOT_INTERACTIVE_PREFILL_RESERVATION_V2' in s}))")
    record={'observedAtUTC':datetime.now(timezone.utc).isoformat(),'configurationChanged':False,
            'profiles':profiles,'services':services,'callback':callback,'composedWebProfiles':compositions,
            'compactionBudgetExecution':compaction,'liveScheduler':json.loads(scheduler)}
    args.output.write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
