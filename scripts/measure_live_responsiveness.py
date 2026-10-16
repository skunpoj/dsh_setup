"""Bounded synthetic LiteLLM sample: three short and two concurrent requests.

Runs inside Secure with its existing credential; does not export credentials,
modify inference configuration or create DSH histories. Not a capacity benchmark.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROBE = r'''
import concurrent.futures,json,os,time,urllib.request,uuid
def request(label,prompt,maximum):
 start=time.monotonic();first=None;text='';usage={};finish=None
 payload={'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':prompt}],
 'temperature':0,'max_tokens':maximum,'stream':True,'stream_options':{'include_usage':True},
 'chat_template_kwargs':{'enable_thinking':False}}
 req=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',
 data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',
 'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
 with urllib.request.urlopen(req,timeout=60) as response:
  for line in response:
   if not line.startswith(b'data: '):continue
   body=line[6:].strip()
   if body==b'[DONE]':break
   item=json.loads(body)
   if item.get('usage'):usage=item['usage']
   for choice in item.get('choices',[]):
    delta=choice.get('delta',{});content=delta.get('content') or ''
    if (content or delta.get('reasoning_content')) and first is None:first=time.monotonic()
    text+=content
    if choice.get('finish_reason'):finish=choice['finish_reason']
 elapsed=time.monotonic()-start
 return {'label':label,'firstTokenSeconds':round(first-start,3) if first else None,
 'elapsedSeconds':round(elapsed,3),'text':text,'usage':usage,'finishReason':finish,
 'effectiveOutputTokensPerSecond':round(usage.get('completion_tokens',0)/elapsed,2)}
rows=[request('short-'+str(i),'Reply with exactly LIVE_STATUS_OK and nothing else.',32) for i in range(3)]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 parallel=list(pool.map(lambda i:request('parallel-'+str(i),'Output the integers from 1 through 40, separated by commas. No other text.',160),range(2)))
expected=','.join(str(i) for i in range(1,41))
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 long=pool.submit(request,'mixed-24k','Synthetic nonce '+str(uuid.uuid4())+'\n'+
  (' red blue green yellow'*6000)+'\nIgnore the colors and reply exactly MIXED_LONG_OK.',32)
 time.sleep(0.5)
 shortDuring=[]
 for i in range(3):
  row=request('mixed-short-'+str(i),'Reply with exactly LIVE_STATUS_OK and nothing else.',32)
  row['longStillRunningAfterReply']=not long.done();shortDuring.append(row)
 mixed={'long':long.result(),'shortDuring':shortDuring}
print(json.dumps({'short':rows,'parallel':parallel,'shortExact':all(x['text'].strip()=='LIVE_STATUS_OK' for x in rows),
 'parallelExact':all(''.join(x['text'].split())==expected for x in parallel),
 'mixed24k':mixed,'mixedExact':mixed['long']['text'].strip()=='MIXED_LONG_OK' and all(x['text'].strip()=='LIVE_STATUS_OK' for x in shortDuring),
 'definition':'Effective output tokens/sec includes queue, prefill and network time; not steady-state decode speed.'}))
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    result = subprocess.run(['kubectl', '--request-timeout=30s', '-n', 'llm', 'exec', '-i',
                             'deploy/dsh-secure', '--', 'python3', '-'], input=PROBE,
                            capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError(result.stderr)
    record = json.loads(result.stdout)
    record['timeUTC'] = datetime.now(timezone.utc).isoformat()
    record['scope'] = 'Synthetic short/two-concurrent and approximately 24K mixed-load LiteLLM calls from Secure; no near-1M or DSH agent benchmark'
    args.output.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record), flush=True)
    if not record['shortExact'] or not record['parallelExact'] or not record['mixedExact']:
        raise RuntimeError('Actual output did not match the synthetic acceptance content')


if __name__ == '__main__':
    main()
