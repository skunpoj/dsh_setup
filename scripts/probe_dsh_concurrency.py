"""Native DSH concurrency through one Kubernetes control channel.

Creates synthetic histories only in an explicitly selected disposable pod.
Never deploys, restarts workloads, or cancels another session's work.
"""
import argparse,json,subprocess,sys
from pathlib import Path

REMOTE=r'''
import concurrent.futures,http.client,json,time,uuid
from pathlib import Path
host=CONFIG['host'];token=next(p for p in Path('/runtime-tokens').iterdir()if p.is_file()).read_text().strip()
c=http.client.HTTPConnection('127.0.0.1',3080,timeout=30)
c.request('GET','/?token='+token,headers={'Host':host});r=c.getresponse()
cookie='; '.join(v.split(';')[0]for k,v in r.getheaders()if k.lower()=='set-cookie');r.read();c.close()
if not cookie:raise RuntimeError('Disposable DSH launch authentication failed')
def rpc(method,args):
 c=http.client.HTTPConnection('127.0.0.1',3080,timeout=60)
 c.request('POST','/api/'+method,json.dumps({'type':'client-request','rpcId':str(uuid.uuid4()),'method':method,'payload':{'args':args}}),headers={'Host':host,'Origin':'http://'+host,'Content-Type':'application/json','Cookie':cookie})
 r=c.getresponse();v=json.loads(r.read());c.close()
 if not v.get('result',{}).get('ok'):raise RuntimeError('Native DSH rejected the synthetic request')
 return v['result']['value']
def one(label):
 sid=rpc('session/create',{'request':{'cwd':'/workspace'}})['sessionId']
 rpc('session/rename',{'request':{'sessionId':sid,'title':'Synthetic concurrency '+label}})
 prompt='Synthetic nonce '+uuid.uuid4().hex+'\nOutput integers from 1 through 40, separated by commas and spaces. No other text. Do not use tools.'
 expected=''.join(', '.join(map(str,range(1,41))).split());baseline=rpc('session/projections',{'request':{'sessionId':sid}})['asOfSeq'];start=time.time()
 record={'label':label,'sessionId':sid,'startUTC':start,'status':'running'}
 rpc('session/prompt',{'request':{'sessionId':sid,'requestId':str(uuid.uuid4()),'content':[{'type':'text','text':prompt}],'mode':'queue'}})
 try:
  while time.time()-start<240:
   projection=rpc('session/projections',{'request':{'sessionId':sid}})
   page=rpc('session/page',{'request':{'address':{'kind':'session','sessionId':sid},'throughSeq':projection['asOfSeq'],'maxMessages':20}})
   events=[x['event']for x in page['records']if x['event']['seq']>baseline]
   if any(e['type']=='llm/retry'for e in events):raise RuntimeError('Synthetic turn retried')
   if any(e['type']=='turn/end'for e in events):
    messages=[e for e in events if e['type']=='assistant/message']
    text=''.join(b.get('text','')for e in messages for b in e['data'].get('message',{}).get('content',[])if b.get('type')=='text')
    streams=[s for e in messages for s in e['data'].get('stream',[])if s.get('type')=='text-chunks']
    first=min((s['time0']/1000 for s in streams),default=None)
    last=max(((s['time0']+sum(s.get('dt',[])))/1000 for s in streams),default=None)
    usage=messages[-1]['data'].get('usage',{})if messages else{}
    record.update(status='completed',endUTC=time.time(),elapsedSeconds=time.time()-start,firstTextSeconds=first-start if first is not None else None,streamSeconds=last-first if first is not None and last is not None else None,usage=usage,output=text,exact=''.join(text.split())==expected,retries=0,tools=sum(e['type']=='tool/call'for e in events),persistedPromptVerified=any(e['type']=='user/message'and e['data'].get('content')==[{'type':'text','text':prompt}]for e in events))
    if record['streamSeconds']and usage.get('outputTokens'):record['streamTokensPerSecond']=(usage['outputTokens']-1)/record['streamSeconds']
    return record
   time.sleep(.25)
  raise TimeoutError('Synthetic DSH turn exceeded its deadline')
 except Exception as exc:
  try:rpc('session/cancel',{'request':{'sessionId':sid}})
  except Exception:pass
  record.update(status='failed',failureType=type(exc).__name__,endUTC=time.time())
  return record
out={'scope':'Actual native DSH clients, one operator Kubernetes channel','groups':[],'status':'running'}
dest=Path('/tmp/dsh-concurrency-'+CONFIG['nonce']+'.json')
for count in CONFIG['groups']:
 with concurrent.futures.ThreadPoolExecutor(count)as pool:rows=list(pool.map(one,[CONFIG['nonce']+'-'+str(count)+'-'+str(i)for i in range(count)]))
 passed=all(r.get('status')=='completed'and r.get('exact')and r.get('persistedPromptVerified')and r.get('tools')==0 and r.get('retries')==0 for r in rows)
 out['groups'].append({'clients':count,'rows':rows,'passed':passed});dest.write_text(json.dumps(out))
 if not passed:break
out['status']='passed'if len(out['groups'])==len(CONFIG['groups'])and all(g['passed']for g in out['groups'])else'failed'
out['remoteResultPath']=str(dest);dest.write_text(json.dumps(out));print(json.dumps(out))
'''

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--kubectl',default='kubectl');ap.add_argument('--namespace',required=True)
 ap.add_argument('--pod',required=True);ap.add_argument('--expected-app',required=True)
 ap.add_argument('--host',required=True,help='Operator-supplied approved DSH Host value')
 ap.add_argument('--output',type=Path,required=True)
 args=ap.parse_args()
 if args.output.exists():raise SystemExit('Preserve existing result; choose a new output path')
 command=[args.kubectl,'-n',args.namespace]
 pod=json.loads(subprocess.check_output(command+['get','pod',args.pod,'-o','json']))
 if pod['metadata'].get('labels',{}).get('app')!=args.expected_app:raise SystemExit('Unexpected pod identity')
 allowed={'emptyDir','configMap','secret','projected','downwardAPI'}
 if any(len(set(v)-{'name'})!=1 or not(set(v)-{'name'})<=allowed for v in pod['spec'].get('volumes',[])):
  raise SystemExit('Refuse persistent or host-mounted user storage; use a disposable canary')
 import uuid
 config={'host':args.host,'groups':[1,2,4,8,16],'nonce':uuid.uuid4().hex}
 code='CONFIG='+repr(config)+'\n'+REMOTE
 p=subprocess.run(command+['exec','-i',args.pod,'--','python3','-'],input=code,text=True,encoding='utf-8',capture_output=True,timeout=1200)
 args.output.parent.mkdir(parents=True,exist_ok=True)
 if p.returncode:
  args.output.with_suffix('.transport.private.txt').write_text(p.stderr,encoding='utf-8')
  raise SystemExit('Operator channel failed; inspect saved native sessions before attributing a model failure')
 result=json.loads(p.stdout);args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps({'status':result['status'],'groups':[{'clients':g['clients'],'correctReplies':sum(bool(r.get('exact'))for r in g['rows'])}for g in result['groups']]}))
 if result['status']!='passed':raise SystemExit(1)

if __name__=='__main__':main()
