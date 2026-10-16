"""Bounded, staged shared-service inference stress test.

Synthetic content only. No settings, user histories or model deployment changes.
Stops escalation on errors, output mismatch, latency gates, busy admission or
pod replacement/restart. This is not a destructive capacity/OOM test.
"""
import argparse
import concurrent.futures
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

MODEL='vllm-deepseek-v4-1-flash'


def kube(*args,source=None,timeout=100):
    p=subprocess.run(['kubectl','--request-timeout=25s','-n','llm',*args],input=source,
        capture_output=True,text=True,encoding='utf8',timeout=timeout)
    if p.returncode:raise RuntimeError('Kubernetes test operation failed: '+p.stderr[:180])
    return p.stdout


SNAPSHOT=r'''
import json,subprocess,urllib.request
s=urllib.request.urlopen('http://127.0.0.1:8000/metrics',timeout=5).read().decode()
names=['sglang:num_running_reqs','sglang:num_queue_reqs','sglang:token_usage','sglang:full_token_usage']
m={}
for line in s.splitlines():
 for n in names:
  if line.startswith(n+'{'):m[n]=max(m.get(n,0),float(line.rsplit(' ',1)[1]))
p=subprocess.run(['nvidia-smi','--query-gpu=index,memory.used,memory.free,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=8)
g=[]
if p.returncode==0:
 for line in p.stdout.splitlines():
  a=[int(x.strip()) for x in line.split(',')];g.append(dict(zip(['index','usedMiB','freeMiB','utilizationPercent'],a)))
print(json.dumps({'metrics':m,'gpus':g}))
'''

REQUEST=r'''
import concurrent.futures,json,os,time,urllib.request,urllib.error,uuid,threading
plan=json.loads(PLAN)
def request(label,prompt,maximum,expected,barrier=None):
 if barrier:barrier.wait(timeout=8)
 start=time.monotonic();first=None;text='';usage={};finish=None;events=0
 try:
  payload={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':prompt}],
   'temperature':0,'max_tokens':maximum,'stream':True,'stream_options':{'include_usage':True},
   'chat_template_kwargs':{'enable_thinking':False}}
  req=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',
   data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
  with urllib.request.urlopen(req,timeout=45) as response:
   for line in response:
    if time.monotonic()-start>60:raise TimeoutError('Synthetic request deadline')
    if not line.startswith(b'data: '):continue
    body=line[6:].strip()
    if body==b'[DONE]':break
    item=json.loads(body)
    if 'error' in item:raise RuntimeError('Streaming error event')
    if item.get('usage'):usage=item['usage']
    for choice in item.get('choices',[]):
     delta=choice.get('delta',{});content=delta.get('content') or ''
     if (content or delta.get('reasoning_content')) and first is None:first=time.monotonic()
     text+=content
     if content:events+=1
     if choice.get('finish_reason'):finish=choice['finish_reason']
  elapsed=time.monotonic()-start
  return {'label':label,'startMonotonic':start,'endMonotonic':time.monotonic(),
   'firstTokenSeconds':round(first-start,4) if first else None,'elapsedSeconds':round(elapsed,4),
   'text':text,'expected':expected,'exact':''.join(text.split())==''.join(expected.split()),'usage':usage,
   'finishReason':finish,'contentEvents':events,'effectiveOutputTokensPerSecond':round(usage.get('completion_tokens',0)/elapsed,3)}
 except Exception as e:
  return {'label':label,'elapsedSeconds':round(time.monotonic()-start,4),'exact':False,'errorType':type(e).__name__,
   'httpStatus':getattr(e,'code',None)}
rows=[];begin=time.monotonic()
if plan['kind']=='burst':
 n=plan['concurrency'];barrier=threading.Barrier(n);expected=','.join(str(i) for i in range(1,41))
 with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
  futures=[pool.submit(request,'burst-'+str(i),'Synthetic nonce '+str(uuid.uuid4())+'\nOutput the integers from 1 through 40, separated by commas. No other text.',160,expected,barrier) for i in range(n)]
  rows=[f.result() for f in futures]
else:
 target=plan['inputTarget'];expected='MIXED_STRESS_OK'
 prompt='Synthetic nonce '+str(uuid.uuid4())+'\n'+(' red blue green yellow'*(target//4))+'\nIgnore the colors and reply exactly '+expected+'.'
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  long=pool.submit(request,'mixed-long',prompt,32,expected)
  time.sleep(.5)
  for i in range(3):
   short=request('mixed-short-'+str(i),'Synthetic nonce '+str(uuid.uuid4())+'\nReply with exactly SHORT_STRESS_OK.',32,'SHORT_STRESS_OK')
   short['longStillRunningAfterReply']=not long.done();rows.append(short)
  rows.insert(0,long.result())
elapsed=time.monotonic()-begin
print(json.dumps({'plan':plan,'wallSeconds':round(elapsed,4),'rows':rows,
 'allExact':all(r.get('exact') for r in rows),
 'aggregateOutputTokensPerSecond':round(sum(r.get('usage',{}).get('completion_tokens',0) for r in rows)/elapsed,3)}))
'''


def snapshot():
    s=json.loads(kube('exec','-i','deploy/'+MODEL,'--','python3','-',source=SNAPSHOT,timeout=30))
    pods=json.loads(kube('get','pods','-l','app='+MODEL,'-o','json'))['items']
    s['pods']=[{'uid':p['metadata']['uid'],'name':p['metadata']['name'],
       'containers':[{'restartCount':c['restartCount'],'imageID':c['imageID']} for c in p['status'].get('containerStatuses',[])]} for p in pods]
    s['timeUTC']=datetime.now(timezone.utc).isoformat()
    return s


def percentile(values,p):
    a=sorted(values);return a[max(0,__import__('math').ceil(len(a)*p)-1)]


def summarize(stage):
    rows=stage['rows'];times=[r['elapsedSeconds'] for r in rows]
    return {'requests':len(rows),'exactReplies':sum(bool(r.get('exact')) for r in rows),
        'p50Seconds':percentile(times,.5),'p95Seconds':percentile(times,.95),'maxSeconds':max(times),
        'perRequestEffectiveOutputTokensPerSecond':[r.get('effectiveOutputTokensPerSecond') for r in rows],
        'aggregateOutputTokensPerSecond':stage['aggregateOutputTokensPerSecond']}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('Refuse to overwrite an earlier stress-test record')
    record={'startedAtUTC':datetime.now(timezone.utc).isoformat(),'scope':'Synthetic streaming LiteLLM calls from Secure; not DSH browser/agent, near-1M, sustained saturation or SLA acceptance',
       'limits':{'burstConcurrency':[1,2,4,8,16],'roundsPerLevel':3,'mixedInputTargets':[24000,96000,120000],
                 'burstMaxSeconds':15,'mixedShortMaxSeconds':5,'mixedLongMaxSeconds':40},
       'configurationChanged':False,'stages':[],'samples':[],'status':'running'}
    def save():args.output.write_text(json.dumps(record,indent=2),encoding='utf8')
    def monitor(stop):
        while not stop.wait(2):
            try:record['samples'].append(snapshot())
            except Exception as e:record['samples'].append({'monitorErrorType':type(e).__name__})
    stop=threading.Event();thread=None
    try:
        before=snapshot();record['before']=before;save()
        plans=[{'kind':'burst','concurrency':n,'round':r} for n in [1,2,4,8,16] for r in range(1,4)]
        plans += [{'kind':'mixed','inputTarget':n} for n in [24000,96000,120000]]
        thread=threading.Thread(target=monitor,args=(stop,),daemon=True);thread.start()
        for plan in plans:
            state=snapshot()
            if state['pods']!=before['pods']:raise RuntimeError('Model pod/image/restart state changed; stop escalation')
            metrics=state['metrics']
            if not all(n in metrics for n in ['sglang:num_running_reqs','sglang:num_queue_reqs']):raise RuntimeError('Admission metrics unavailable')
            if metrics['sglang:num_running_reqs'] or metrics['sglang:num_queue_reqs']:
                raise RuntimeError('Model has active or queued work before next stage; defer further shared-service load')
            source='PLAN = '+repr(json.dumps(plan))+'\n'+REQUEST
            stage=json.loads(kube('exec','-i','deploy/dsh-secure','--','python3','-',source=source,timeout=100))
            stage['summary']=summarize(stage);record['stages'].append(stage);save()
            print(json.dumps({'completed':plan,'summary':stage['summary']}),flush=True)
            if not stage['allExact']:raise RuntimeError('Inference error or exact-output failure; stop escalation')
            if plan['kind']=='burst' and stage['summary']['maxSeconds']>15:raise RuntimeError('Burst latency gate exceeded')
            if plan['kind']=='mixed':
                if stage['rows'][0]['elapsedSeconds']>40:raise RuntimeError('Mixed long-request latency gate exceeded')
                if any(r['elapsedSeconds']>5 or not r['longStillRunningAfterReply'] for r in stage['rows'][1:]):
                    raise RuntimeError('Mixed responsiveness/overlap gate failed')
        record['status']='passed'
    except Exception as e:
        record['status']='stopped';record['stopReason']=str(e)
    finally:
        stop.set()
        if thread:thread.join(timeout=35)
        try:
            record['after']=snapshot()
            record['podIdentityAndRestartCountsUnchanged']=record.get('before',{}).get('pods')==record['after']['pods']
            if not record['podIdentityAndRestartCountsUnchanged']:record['status']='stopped'
            log=kube('logs','deploy/'+MODEL,'--since-time='+record['startedAtUTC'])
            record['newModelErrorSignatureCounts']={pattern:len(re.findall(pattern,log,re.I)) for pattern in
                ['CUDA out of memory','OutOfMemoryError','illegal memory access','Scheduler exception']}
        except Exception as e:record['finalCheckErrorType']=type(e).__name__;record['status']='stopped'
        record['finishedAtUTC']=datetime.now(timezone.utc).isoformat();save()
    print(json.dumps({'status':record['status'],'completedStages':len(record['stages']),'evidence':str(args.output)}))
    if record['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
