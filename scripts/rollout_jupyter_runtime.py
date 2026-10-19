"""Replace idle DSH workers with a qualified notebook image; preserve mounts/state.

Run notebook browser acceptance first. Rollback restores configuration only,
never older history bytes. Does not replace gateway or inference workloads.
"""
import argparse,copy,hashlib,json,re,subprocess,uuid
from pathlib import Path

SNAPSHOT=r'''
import os,json,http.client,uuid,hashlib
from pathlib import Path
host=os.environ['DSH_TRUSTED_HOST'];port=int(os.environ.get('DSH_VERIFICATION_PORT','3080'));token=next(p for p in Path('/runtime-tokens').iterdir()if p.is_file()).read_text().strip()
c=http.client.HTTPConnection('127.0.0.1',port,timeout=20);c.request('GET','/?token='+token,headers={'Host':host});r=c.getresponse();cookie='; '.join(v.split(';')[0]for key,v in r.getheaders()if key.lower()=='set-cookie');r.read();c.close()
c=http.client.HTTPConnection('127.0.0.1',port,timeout=30);c.request('POST','/api/session/list',json.dumps({'type':'client-request','rpcId':str(uuid.uuid4()),'method':'session/list','payload':{'args':{'_request':{}}}}),headers={'Host':host,'Origin':'http://'+host,'Cookie':cookie,'Content-Type':'application/json'});r=c.getresponse();v=json.loads(r.read());assert v['result']['ok'];items=v['result']['value']['items']
session_root=Path(os.environ.get('DSH_HOME','/state'))/'sessions'
files={str(p.relative_to(session_root)):hashlib.sha256(p.read_bytes()).hexdigest()for p in session_root.rglob('*')if p.is_file()}
print(json.dumps({'ids':sorted(i['sessionId']for i in items),'running':sum(bool(i.get('running'))for i in items),'sessionFiles':files,'uid':os.getuid()}))
'''

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--image',required=True);ap.add_argument('--acceptance',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--kubectl',default='kubectl');ap.add_argument('--only',help='Comma-separated names within the selected active worker set');ap.add_argument('--apply',action='store_true');a=ap.parse_args()
 if not re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}',a.image):raise ValueError('Immutable image required')
 accepted=json.loads(a.acceptance.read_text(encoding='utf-8'))
 if accepted.get('status')!='passed' or accepted.get('qualifiedImage')!=a.image or len(accepted.get('cases',[]))!=4 or not accepted.get('notebooksSurvivedFourRuntimeReplacements'):raise ValueError('Matching image and real notebook routing/kernel/persistence acceptance required')
 def k(*args,code=None):
  p=subprocess.run([a.kubectl,'-n','llm','--request-timeout=30s',*args],input=code,capture_output=True,text=True,encoding='utf-8',timeout=210)
  if p.returncode:raise RuntimeError(p.stderr[-500:])
  return p.stdout
 ds=json.loads(k('get','deploy','-o','json'))['items'];ds=[d for d in ds if d['spec'].get('replicas')==1 and (d['metadata']['name']in ['dsh-secure','dsh-internet','dsh-user2','dsh3']or re.fullmatch(r'dsh-u-[a-f0-9]{16}-(secure|internet)',d['metadata']['name'])) and d['metadata'].get('labels',{}).get('dsh.bot.or.th/signup-pool')!='jupyter-20261019']
 ds.sort(key=lambda d:(d['metadata']['name']in ['dsh-secure','dsh-internet','dsh-user2','dsh3'],d['metadata']['name']))
 if a.only:
  selected=set(a.only.split(','));assert selected.issubset({d['metadata']['name']for d in ds});ds=[d for d in ds if d['metadata']['name']in selected]
 if not ds:raise RuntimeError('No active private workers')
 print(json.dumps({'workerCount':len(ds),'image':a.image,'modelRestart':False}),flush=True)
 if not a.apply:return
 a.output.mkdir(parents=True,exist_ok=False);results=[]
 for d in ds:
  name=d['metadata']['name'];idx=next(i for i,c in enumerate(d['spec']['template']['spec']['containers'])if c['name']=='dsh');old=d['spec']['template']['spec']['containers'][idx]
  def snapshot():return json.loads(k('exec','-i','deploy/'+name,'-c','dsh','--','env','DSH_VERIFICATION_PORT='+('3081'if name in ['dsh-user2','dsh3']else'3080'),'python3','-',code=SNAPSHOT))
  before=snapshot()
  if before['running']:
   results.append({'name':name,'status':'deferred-active-agent'});print(json.dumps(results[-1]),flush=True);continue
  assert before['uid']!=0
  (a.output/(name+'-before.private.json')).write_text(json.dumps(d,indent=2),encoding='utf-8')
  marker='.jupyter-rollout-'+uuid.uuid4().hex
  def markers(create):
   code="from pathlib import Path\npaths=[Path('/workspace')/"+repr(marker)+",Path('/state/attachments')/"+repr(marker)+"]\nfor p in paths:\n if "+repr(create)+":\n  p.parent.mkdir(parents=True,exist_ok=True)\n  with p.open('xb')as f:f.write(b'jupyter-persistence')\n else:\n  assert p.read_bytes()==b'jupyter-persistence'\n  p.unlink()\n"
   k('exec','-i','deploy/'+name,'-c','dsh','--','python3','-',code=code)
  markers(True);current=json.loads(k('get','deploy',name,'-o','json'));assert current['spec']==d['spec'],'Concurrent workload change'
  spec=copy.deepcopy(d['spec']);c=spec['template']['spec']['containers'][idx];c['image']=a.image
  if name in ['dsh-user2','dsh3']:c['env']=[e for e in c.get('env',[])if e['name']!='DSH_ENVIRONMENT']+[{'name':'DSH_ENVIRONMENT','value':'internet'}]
  try:
   k('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':spec}]))
   k('rollout','status','deploy/'+name,'--timeout=180s');after=snapshot()
   assert set(before['ids']).issubset(after['ids']),'Missing history IDs'
   assert all(after['sessionFiles'].get(p)==h for p,h in before['sessionFiles'].items()),'History bytes changed'
   version=k('exec','deploy/'+name,'-c','dsh','--','jupyter','--version').strip();assert version=='JupyterLab 4.6.4'
   pod=json.loads(k('get','pods','-l','app='+name,'-o','json'))['items'];pod=next(p for p in pod if not p['metadata'].get('deletionTimestamp'));status=next(c for c in pod['status']['containerStatuses']if c['name']=='dsh');assert a.image.split('@')[1] in status['imageID']
   observed=json.loads(k('get','deploy',name,'-o','json'));assert observed['spec']==spec,'Workload changed during verification'
   markers(False);results.append({'name':name,'status':'passed','jupyter':version,'historyIDs':len(before['ids']),'unchangedSessionFiles':len(before['sessionFiles']),'durableMarkers':2,'runningImageID':status['imageID'],'mountsPreserved':True})
  except BaseException:
   current=json.loads(k('get','deploy',name,'-o','json'))
   if current['spec']!=spec:raise RuntimeError('Concurrent workload change: preserve state and review before rollback')
   k('patch','deploy',name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':d['spec']}]))
   k('rollout','status','deploy/'+name,'--timeout=180s');results.append({'name':name,'status':'rolled-back-configuration'});(a.output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8');raise
  (a.output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results[-1]),flush=True)
if __name__=='__main__':main()
