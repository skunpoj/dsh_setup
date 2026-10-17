"""Synthetic DSH stream timing probe. Run only in reviewed disposable storage.

Creates test histories; never run this against a real user runtime. Use the
operator-created ephemeral canary and archive its sessions before cleanup.
"""

import json,http.client,time,uuid,argparse
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--target',type=int,default=0);ap.add_argument('--label',default='short');ap.add_argument('--count',type=int,default=40);a=ap.parse_args()
h='dsh.aiportal.bot.or.th';t=next(x for x in Path('/runtime-tokens').iterdir()if x.is_file()).read_text().strip()
c=http.client.HTTPConnection('127.0.0.1',3080,timeout=30);c.request('GET','/?token='+t,headers={'Host':h});r=c.getresponse();cookie='; '.join(v.split(';')[0]for k,v in r.getheaders()if k.lower()=='set-cookie');r.read();c.close()
def rpc(m,args):
 c=http.client.HTTPConnection('127.0.0.1',3080,timeout=60);c.request('POST','/api/'+m,json.dumps({'type':'client-request','rpcId':str(uuid.uuid4()),'method':m,'payload':{'args':args}}),headers={'Host':h,'Origin':'http://'+h,'Content-Type':'application/json','Cookie':cookie});r=c.getresponse();v=json.loads(r.read());c.close()
 if not v.get('result',{}).get('ok'):raise RuntimeError(str(v.get('result',{}).get('error'))[:200])
 return v['result']['value']
sid=rpc('session/create',{'request':{'cwd':'/workspace'}})['sessionId'];rpc('session/rename',{'request':{'sessionId':sid,'title':'Synthetic latency '+a.label}})
expected=','.join(map(str,range(1,a.count+1)))if not a.target else 'LONG_LATENCY_OK'
prompt=('Synthetic nonce '+uuid.uuid4().hex+'\n'+(' red blue green yellow'*(a.target//4))+'\nReply exactly LONG_LATENCY_OK. Do not use tools.')if a.target else ('Output the integers from 1 through '+str(a.count)+', separated by commas. No other text. Do not use tools.')
start=time.time();baseline=rpc('session/projections',{'request':{'sessionId':sid}})['asOfSeq'];rpc('session/prompt',{'request':{'sessionId':sid,'requestId':str(uuid.uuid4()),'content':[{'type':'text','text':prompt}],'mode':'queue'}})
record={'label':a.label,'sessionId':sid,'target':a.target,'startUTC':start,'status':'running'};dest=Path('/tmp/'+a.label+'.json');dest.write_text(json.dumps(record))
while time.time()-start<2400:
 proj=rpc('session/projections',{'request':{'sessionId':sid}});page=rpc('session/page',{'request':{'address':{'kind':'session','sessionId':sid},'throughSeq':proj['asOfSeq'],'maxMessages':20}});events=[x['event']for x in page.get('records',[])if x['event']['seq']>baseline]
 if any(e['type']=='turn/end'for e in events):
  messages=[e for e in events if e['type']=='assistant/message'];texts=[];first=None;last=None;usage={};gaps=[]
  for e in messages:
   d=e['data'];texts.append(''.join(b.get('text','')for b in d.get('message',{}).get('content',[])if b.get('type')=='text'));usage=d.get('usage',{})
   for s in d.get('stream',[]):
    if s.get('type')=='text-chunks':
     t0=s['time0']/1000;first=t0 if first is None else min(first,t0);last=t0+sum(s.get('dt',[]))/1000;gaps+=s.get('dt',[])
  text=''.join(texts);record.update(status='completed',endUTC=time.time(),elapsedSeconds=time.time()-start,firstTextSeconds=first-start if first else None,streamSeconds=last-first if first and last else None,usage=usage,exact=''.join(text.split())==expected,output=text,retries=sum(e['type']=='llm/retry'for e in events),tools=sum(e['type']=='tool/call'for e in events),maxGapMs=max(gaps or [0]),largeGapsMs=[n for n in gaps if n>500],persistedPromptVerified=any(e['type']=='user/message'and e['data'].get('content')==[{'type':'text','text':prompt}]for e in events));dest.write_text(json.dumps(record));print(json.dumps(record));break
 time.sleep(.5)
else:raise RuntimeError('Deadline')
