from pathlib import Path
import json,hashlib,copy,sys,time,urllib.request,urllib.error,ssl
from guard_helpers import durable,api,snapshot,verify_subset,create_one
ROOT=Path(__file__).parent;NAME='dsh-app-signin-test';NS='llm'
if not __debug__:raise RuntimeError('Non-optimized Python required')
sha=lambda b:hashlib.sha256(b).hexdigest()
def validate(plan,review):
 assert plan['namespace']==NS and plan['name']==NAME and set(plan['targets'])=={'Deployment','Ingress'}
 assert plan['targets']['Deployment']['uid']=='f1fbf9b2-1fa6-42b6-8d0f-dbb236077c58'and plan['targets']['Ingress']['uid']=='df9a1b63-a2be-4b2d-ab6b-924c870e97f4'
 assert plan['labels']=={'app':NAME,'codex-task':NAME,'codex-op':plan['parent_operation_id']}
 cm=plan['new_ConfigMap'];identity=sha(json.dumps(cm['data'],sort_keys=True).encode());assert identity==plan['source_identity']
 assert cm['metadata']=={'name':NAME+'-source-'+identity[:12],'namespace':NS,'labels':plan['labels']}and cm['immutable']is True
 assert plan['source_hashes']=={n:sha(v.encode())for n,v in cm['data'].items()}
 assert plan['source_hashes']['auth_proxy.js']=='8ba09e26058f8ae610ef89b35ef9810ce7fce914337d78e22d19f83c31601059'
 assert 'password hashes are mirrored'not in cm['data']['auth_proxy.js']
 expected=copy.deepcopy(plan['targets']['Deployment']['old_spec']);pod=expected['template']['spec'];next(v for v in pod['volumes']if v['name']=='source')['configMap']['name']=cm['metadata']['name']
 gateway=next(c for c in pod['containers']if c['name']=='gateway');gateway['env'] += [{'name':'TEST_ALIAS_MIGRATION_SHA256','value':plan['store_before']['app-links.json']},{'name':'DSH_TEST_ISSUER','value':'true'}]
 target=next(c for c in pod['containers']if c['name']=='test-target');next(e for e in target['env']if e['name']=='TEST_SOURCE_REVISION')['value']='app-focused-login-8ba09e26'
 assert expected==plan['targets']['Deployment']['new_spec'],'Deployment footprint widened'
 hosts=[NAME+'.aiportal.bot.or.th','app-signin-gated-test.aiportal.bot.or.th','app-signin-public-test.aiportal.bot.or.th'];assert plan['hosts']==hosts
 expected=copy.deepcopy(plan['targets']['Ingress']['old_spec']);expected['tls'][0]['hosts']=hosts
 for rule,host in zip(expected['rules'],hosts):rule['host']=host
 assert expected==plan['targets']['Ingress']['new_spec'],'Ingress footprint widened'
 assert review['result']=='PASS'and review['source_identity']==identity
 for n in ['PLAN_PRIVATE.json','apply_successor.py','guard_helpers.py','recovery_successor.py','FINAL_QUALIFICATION.log','FINAL_SOURCE_PINS.json']:assert review['files'][n]==sha((ROOT/n).read_bytes()),'Reviewed file drift: '+n
def state(c):
 code="const fs=require('fs'),c=require('crypto'),names=['users.json','routes.json','app-links.json','browser/sessions.json','app-links.before-alias-fix-v3.json'],hash=b=>c.createHash('sha256').update(b).digest('hex'),out=Object.fromEntries(names.map(n=>[n,fs.existsSync('/auth/state/'+n)?hash(fs.readFileSync('/auth/state/'+n)):null]));const map=JSON.parse(fs.readFileSync('/auth/state/app-links.json'));out.names=Object.keys(map);if(map['app-signin-gated-test']&&map['app-signin-public-test'])out.reconstructed_old_sha256=hash(JSON.stringify({'dsh-app-signin-gated-test':map['app-signin-gated-test'],'dsh-app-signin-public-test':map['app-signin-public-test']}));console.log(JSON.stringify(out));"
 return json.loads(c.run(['-n',NS,'exec','deployment/'+NAME,'-c','gateway','--','node','-e',code],timeout=25).stdout)
def patch_target(c,kind,entry,labels):
 path=api(kind,NAME);live=c.cluster(path);assert live['metadata']['uid']==entry['uid']and live['metadata']['labels']==labels and live['spec']==entry['old_spec']
 patch=[{'op':'test','path':'/metadata/uid','value':entry['uid']},{'op':'test','path':'/metadata/resourceVersion','value':live['metadata']['resourceVersion']},{'op':'test','path':'/spec','value':entry['old_spec']},{'op':'replace','path':'/spec','value':entry['new_spec']}]
 reconciled=False
 try:c.run(['-n',NS,'patch',kind.lower(),NAME,'--type=json','-p',json.dumps(patch)],timeout=45)
 except Exception:
  live=c.cluster(path);assert live['metadata']['uid']==entry['uid']and live['spec']==entry['new_spec'],'Unknown patch outcome; do not retry';reconciled=True
 live=c.cluster(path);assert live['metadata']['uid']==entry['uid']and live['metadata']['labels']==labels and live['spec']==entry['new_spec']
 durable(ROOT/('PATCH_'+kind+'_ACK.json'),{'uid':entry['uid'],'spec_sha256':sha(json.dumps(live['spec'],sort_keys=True).encode()),'response_reconciled':reconciled},exclusive=True)
 return live
def matches_phase(pod,plan,flag):
 source=next((v.get('configMap',{}).get('name')for v in pod['spec']['volumes']if v['name']=='source'),None)
 gateway=next((ct for ct in pod['spec']['containers']if ct['name']=='gateway'),{})
 actual=next((e.get('value')for e in gateway.get('env',[])if e['name']=='DSH_APP_LOGIN_ENABLED'),None)
 return source==plan['new_ConfigMap']['metadata']['name']and actual==flag
def ready(c,plan,flag='true'):
 for _ in range(100):
  pods=[p for p in c.cluster('/api/v1/namespaces/llm/pods')['items']if not p['metadata'].get('deletionTimestamp')and all(p['metadata'].get('labels',{}).get(k)==v for k,v in plan['labels'].items())and matches_phase(p,plan,flag)]
  if len(pods)==1 and len(pods[0]['status'].get('containerStatuses',[]))==2 and all(s['ready']and s['restartCount']==0 for s in pods[0]['status']['containerStatuses']):
   pod=pods[0];break
  time.sleep(2)
 else:raise RuntimeError('Own Test not ready; preserve state for diagnosis')
 owner=next(o for o in pod['metadata']['ownerReferences']if o.get('controller'));assert owner['kind']=='ReplicaSet'
 rs=c.cluster('/apis/apps/v1/namespaces/llm/replicasets/'+owner['name']);assert rs['metadata']['uid']==owner['uid']and any(o.get('controller')and o['uid']==plan['targets']['Deployment']['uid']for o in rs['metadata']['ownerReferences'])
 expected='sha256:1397e17507bba66f33d1901518db9a97b80bd1b9fee2e2268656731f8a840016';assert all(s['imageID'].endswith(expected)for s in pod['status']['containerStatuses'])
 code="const fs=require('fs'),c=require('crypto'),names="+json.dumps(list(plan['source_hashes']))+";console.log(JSON.stringify(Object.fromEntries(names.map(n=>[n,c.createHash('sha256').update(fs.readFileSync('/source/'+n)).digest('hex')]))));"
 hashes=json.loads(c.run(['-n',NS,'exec',pod['metadata']['name'],'-c','gateway','--','node','-e',code],timeout=25).stdout);assert hashes==plan['source_hashes']
 return pod
def verify_http():
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*a,**kw):return None
 opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()),NoRedirect());checks=[]
 for route in ['https://app-signin-gated-test.aiportal.bot.or.th/private','https://app-signin-public-test.aiportal.bot.or.th/login','https://dsh-app-signin-test.aiportal.bot.or.th/login?app=app-signin-gated-test']:
  try:r=opener.open(route,timeout=15)
  except urllib.error.HTTPError as e:r=e
  body=r.read(1024*1024);entry={'url':route,'status':r.code,'location':r.headers.get('Location'),'sha256':sha(body)}
  assert b'password hashes are mirrored'not in body
  if 'gated-test.aiportal' in route:assert r.code==303 and r.headers['Location']=='https://dsh-app-signin-test.aiportal.bot.or.th/login?app=app-signin-gated-test'
  elif 'public-test' in route:assert r.code==200 and b'Demonstration application sign-in'in body and b'Jupyter'not in body
  else:assert r.code==200 and b'Sign in to app-signin-gated-test'in body and b'Isolated Test issuer'in body and b'Jupyter'not in body
  checks.append(entry)
 return checks
def main():
 plan=json.loads((ROOT/'PLAN_PRIVATE.json').read_bytes());review=json.loads((ROOT/'INDEPENDENT_REVIEW.json').read_bytes());validate(plan,review)
 sys.path.insert(0,'C:/Users/skunpojt/outputs/product-label-join-followup-20261015');import control as c
 for kind,entry in plan['targets'].items():
  live=c.cluster(api(kind,NAME));assert live['metadata']['uid']==entry['uid']and live['metadata']['labels']==plan['labels']and live['spec']==entry['old_spec']
 for kind,entry in plan['unchanged_own_resources'].items():
  live=c.cluster(api(kind,NAME));assert live['metadata']['uid']==entry['uid']and live['spec']==entry['spec']
 try:c.cluster(api('ConfigMap',plan['new_ConfigMap']['metadata']['name']))
 except Exception as e:
  if getattr(e,'code',None)!=404:raise
 else:raise RuntimeError('New source exists; reconcile prior intent')
 allIngress=c.cluster('/apis/networking.k8s.io/v1/ingresses')['items'];assert not any(r.get('host')in plan['hosts'][1:]for i in allIngress for r in i['spec'].get('rules',[]))
 beforeStore=state(c);assert all(beforeStore[k]==v for k,v in plan['store_before'].items())
 before=snapshot(c);durable(ROOT/'PROTECTED_BEFORE.json',before,exclusive=True);durable(ROOT/'STARTED.json',{'plan_sha256':sha((ROOT/'PLAN_PRIVATE.json').read_bytes()),'phase_id':plan['phase_id'],'epoch':time.time()},exclusive=True)
 newSource=create_one(plan['new_ConfigMap'],c,{'labels':plan['labels'],'operation_id':plan['parent_operation_id']});durable(ROOT/'NEW_SOURCE_OWNERSHIP.json',newSource,exclusive=True)
 patch_target(c,'Deployment',plan['targets']['Deployment'],plan['labels']);pod=ready(c,plan)
 migrated=state(c);assert migrated['names']==['app-signin-gated-test','app-signin-public-test']and migrated['reconstructed_old_sha256']==plan['store_before']['app-links.json']and migrated['app-links.before-alias-fix-v3.json']==plan['store_before']['app-links.json']
 assert all(migrated[n]==plan['store_before'][n]for n in ['users.json','routes.json','browser/sessions.json'])
 patch_target(c,'Ingress',plan['targets']['Ingress'],plan['labels'])
 for kind,entry in plan['targets'].items():
  live=c.cluster(api(kind,NAME));assert live['metadata']['uid']==entry['uid']and live['metadata']['labels']==plan['labels']and live['spec']==entry['new_spec']
 for kind,entry in plan['unchanged_own_resources'].items():
  live=c.cluster(api(kind,NAME));assert live['metadata']['uid']==entry['uid']and live['spec']==entry['spec']
 checks=None
 for attempt in range(15):
  try:checks=verify_http();break
  except(AssertionError,urllib.error.URLError,TimeoutError):
   if attempt==14:raise
   time.sleep(1)
 after=snapshot(c);durable(ROOT/'PROTECTED_AFTER.json',after)
 durable(ROOT/'DEPLOYMENT_READBACK_PRIVATE.json',c.cluster(api('Deployment',NAME)))
 result={'source_identity':plan['source_identity'],'pod_uid':pod['metadata']['uid'],'actual_source_hashes_match':True,'migrated_registry_readback':migrated,'anonymous_actual_HTTP':checks,'existing_protected_unchanged':before==after,'no_Main_or_existing_bridge_changes_by_operator':True,'historical_resend':0,'authenticated_and_recovery_acceptance_pending':True}
 durable(ROOT/'ROLLOUT_READBACK.json',result);assert before==after,'Protected drift; retain receipts and coordinate';print(json.dumps(result))
if __name__=='__main__':main()
