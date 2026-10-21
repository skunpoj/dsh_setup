from pathlib import Path
import os,json,hashlib,time,sys,uuid
ROOT=Path(__file__).parent;NAME='dsh-app-signin-test';NS='llm'
if not __debug__:raise RuntimeError('Safety checks require non-optimized Python')
sha=lambda b:hashlib.sha256(b).hexdigest()
PREFIX={'PersistentVolumeClaim':('/api/v1','persistentvolumeclaims'),'Secret':('/api/v1','secrets'),'ConfigMap':('/api/v1','configmaps'),'Service':('/api/v1','services'),'Deployment':('/apis/apps/v1','deployments'),'Ingress':('/apis/networking.k8s.io/v1','ingresses'),'NetworkPolicy':('/apis/networking.k8s.io/v1','networkpolicies')}
def api(kind,name):
 prefix,plural=PREFIX[kind];return prefix+'/namespaces/'+NS+'/'+plural+'/'+name
def durable(path,value,exclusive=False):
 target=path if exclusive else path.with_name(path.name+'.tmp-'+uuid.uuid4().hex)
 fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w',encoding='utf8')as f:json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
 if not exclusive:os.replace(target,path)
def validate(plan,review):
 assert plan['namespace']==NS and plan['name']==NAME
 assert str(uuid.UUID(plan['operation_id']))==plan['operation_id']
 labels={'app':NAME,'codex-task':NAME,'codex-op':plan['operation_id']};assert plan['labels']==labels
 resources=plan['resources'];assert [r['kind']for r in resources]==['PersistentVolumeClaim','Secret','Secret','ConfigMap','NetworkPolicy','Service','Deployment','Ingress']
 cm=resources[3];identity=sha(json.dumps(cm['data'],sort_keys=True).encode());assert identity==plan['source_identity']
 assert cm['metadata']['name']==NAME+'-source-'+identity[:12] and cm['immutable']is True
 expected=[NAME,NAME+'-credentials',NAME+'-target-tls',cm['metadata']['name'],NAME,NAME,NAME,NAME]
 for resource,name in zip(resources,expected):
  assert resource['metadata']=={'name':name,'namespace':NS,'labels':labels}or(resource['kind']=='Ingress'and resource['metadata']=={'name':name,'namespace':NS,'labels':labels,'annotations':{'nginx.ingress.kubernetes.io/ssl-redirect':'true','nginx.ingress.kubernetes.io/proxy-read-timeout':'120'}})
 assert plan['source_hashes']=={n:sha(v.encode())for n,v in cm['data'].items()}
 assert plan['source_hashes']['auth_proxy.js']=='59bce63126a62a134c55ae42345b4eadc8275af5f48a78b12d9c8e9f1a76f5d0'
 hosts=[NAME+'.aiportal.bot.or.th','dsh-app-signin-gated-test.aiportal.bot.or.th','dsh-app-signin-public-test.aiportal.bot.or.th'];assert plan['hosts']==hosts
 ingress=resources[-1]['spec'];assert [r['host']for r in ingress['rules']]==hosts and ingress['tls']==[{'hosts':hosts,'secretName':'aiportal-wildcard-tls'}] and ingress['ingressClassName']=='nginx'
 assert resources[0]['spec']['resources']=={'requests':{'storage':'1Gi'}}
 for r in resources[1:3]:assert r['immutable']is True
 deployment=resources[-2];pod=deployment['spec']['template']['spec'];assert deployment['spec']['selector']['matchLabels']==labels and deployment['spec']['template']['metadata']['labels']==labels
 assert pod['automountServiceAccountToken']is False and len(pod['containers'])==2
 for ct in pod['containers']:
  assert ct['image']==plan['image']=='dsoreg-sm1-p1.bot.or.th/da-gpu-server/dsh-runtime@sha256:1397e17507bba66f33d1901518db9a97b80bd1b9fee2e2268656731f8a840016'
  assert ct['securityContext']=={'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}}
 env={e['name']:e.get('value')for e in pod['containers'][0]['env']};assert env['DSH_COOKIE_NAME']=='dsh-auth-app-signin-test' and env['DSH_ALLOW_REGISTRATION']=='false' and env['DSH_APP_LOGIN_ENABLED']=='true'
 assert not any('TOKEN'in k or k.startswith('GOOGLE')or k.startswith('DSH_NORMAL')for k in env)
 assert review['result']=='PASS' and review['source_identity']==identity
 for name in ['PLAN_PRIVATE.json','apply_isolated_test.py','recovery_isolated_test.py','FINAL_QUALIFICATION.log','FINAL_SOURCE_PINS.json']:
  assert review['files'][name]==sha((ROOT/name).read_bytes()),'Reviewed file drift: '+name
 return resources
def verify_subset(desired,actual):
 if isinstance(desired,dict):return isinstance(actual,dict)and all(k in actual and verify_subset(v,actual[k])for k,v in desired.items())
 if isinstance(desired,list):return isinstance(actual,list)and len(actual)==len(desired)and all(verify_subset(x,y)for x,y in zip(desired,actual))
 return desired==actual
def snapshot(c):
 out={}
 for name in ['dsh-environment-gateway','dsh-proxy-test-gateway','dsh-domain-docs-test']:
  d=c.cluster('/apis/apps/v1/namespaces/llm/deployments/'+name);out[name]={'uid':d['metadata']['uid'],'generation':d['metadata']['generation'],'spec_sha256':sha(json.dumps(d['spec'],sort_keys=True).encode())}
 out['existing_ingresses']={d['metadata']['namespace']+'/'+d['metadata']['name']:sha(json.dumps(d['spec'],sort_keys=True).encode())for d in c.cluster('/apis/networking.k8s.io/v1/ingresses')['items']if not(d['metadata']['namespace']==NS and d['metadata']['name']==NAME)}
 return out
def create_one(resource,c,plan):
 path=api(resource['kind'],resource['metadata']['name']);reconciled=False
 try:actual=json.loads(c.run(['-n',NS,'create','-f','-','-o','json'],input=json.dumps(resource).encode(),timeout=45).stdout)
 except Exception:
  actual=c.cluster(path);reconciled=True
 assert actual['metadata']['labels']==plan['labels'] and verify_subset(resource,actual),'Created resource drift/foreign ownership'
 entry={'kind':resource['kind'],'name':resource['metadata']['name'],'namespace':NS,'uid':actual['metadata']['uid'],'operation_id':plan['operation_id'],'create_response_reconciled':reconciled}
 durable(ROOT/('CREATED_'+resource['kind']+'_'+resource['metadata']['name']+'.json'),entry,exclusive=True)
 return entry
def main():
 plan=json.loads((ROOT/'PLAN_PRIVATE.json').read_bytes());review=json.loads((ROOT/'INDEPENDENT_REVIEW.json').read_bytes());resources=validate(plan,review)
 sys.path.insert(0,'C:/Users/skunpojt/outputs/product-label-join-followup-20261015');import control as c
 # Existing names and exact hosts must be unused before the exclusive start.
 for resource in resources:
  try:c.cluster(api(resource['kind'],resource['metadata']['name']))
  except Exception as e:
   if getattr(e,'code',None)!=404:raise
  else:raise RuntimeError('Resource exists; reconcile ownership, never overwrite')
 ingresses=c.cluster('/apis/networking.k8s.io/v1/ingresses')['items']
 assert not any(rule.get('host')in plan['hosts']for item in ingresses for rule in item['spec'].get('rules',[]))
 aliases={h.split('.')[0]for h in plan['hosts']}
 registry="const fs=require('fs'),path=require('path'),p=process.env.DSH_APP_LINKS_PATH||path.join(path.dirname(process.env.DSH_USER_STORE_PATH||'/workspace/users/.user_auth.json'),'app-links.json');console.log(JSON.stringify(fs.existsSync(p)?Object.keys(JSON.parse(fs.readFileSync(p,'utf8'))):[]));"
 for deployment in ['dsh-environment-gateway','dsh-proxy-test-gateway']:
  d=c.cluster('/apis/apps/v1/namespaces/llm/deployments/'+deployment);ct=d['spec']['template']['spec']['containers'][0]['name'];names=json.loads(c.run(['-n',NS,'exec','deployment/'+deployment,'-c',ct,'--','node','-e',registry],timeout=25).stdout);assert not aliases.intersection(names),'Existing registry alias conflict'
 before=snapshot(c);durable(ROOT/'PROTECTED_BEFORE.json',before,exclusive=True)
 durable(ROOT/'STARTED.json',{'plan_sha256':sha((ROOT/'PLAN_PRIVATE.json').read_bytes()),'operation_id':plan['operation_id'],'started_epoch':time.time()},exclusive=True)
 owned=[]
 for resource in resources:
  owned.append(create_one(resource,c,plan))
  durable(ROOT/'OWNERSHIP.json',owned)
 deployment=next(x for x in owned if x['kind']=='Deployment')
 for _ in range(100):
  d=c.cluster(api('Deployment',NAME));assert d['metadata']['uid']==deployment['uid'] and d['metadata']['labels']==plan['labels']
  pods=[p for p in c.cluster('/api/v1/namespaces/llm/pods')['items']if not p['metadata'].get('deletionTimestamp')and all(p['metadata'].get('labels',{}).get(k)==v for k,v in plan['labels'].items())]
  if len(pods)==1 and len(pods[0]['status'].get('containerStatuses',[]))==2 and all(s['ready']for s in pods[0]['status']['containerStatuses']):break
  time.sleep(2)
 else:raise RuntimeError('New Test not ready; preserve owned resources for diagnosis')
 pod=pods[0];owner=next(x for x in pod['metadata']['ownerReferences']if x['controller']);assert owner['kind']=='ReplicaSet'
 rs=c.cluster('/apis/apps/v1/namespaces/llm/replicasets/'+owner['name']);assert rs['metadata']['uid']==owner['uid'] and any(x['uid']==deployment['uid']and x.get('controller')for x in rs['metadata']['ownerReferences'])
 assert all(s['imageID'].endswith(plan['image'].split('@')[1])for s in pod['status']['containerStatuses'])
 code="const fs=require('fs'),c=require('crypto'),names="+json.dumps(list(plan['source_hashes']))+";console.log(JSON.stringify(Object.fromEntries(names.map(n=>[n,c.createHash('sha256').update(fs.readFileSync('/source/'+n)).digest('hex')]))));"
 hashes=json.loads(c.run(['-n',NS,'exec',pod['metadata']['name'],'-c','gateway','--','node','-e',code],timeout=25).stdout);assert hashes==plan['source_hashes']
 for kind in ['Deployment','NetworkPolicy','Ingress','Service']:
  desired=next(r for r in resources if r['kind']==kind);live=c.cluster(api(kind,desired['metadata']['name']));identity=next(x for x in owned if x['kind']==kind)
  assert live['metadata']['uid']==identity['uid']and live['metadata']['labels']==plan['labels']and verify_subset(desired,live),'Final '+kind+' drift'
 latestPod=c.cluster('/api/v1/namespaces/llm/pods/'+pod['metadata']['name']);assert latestPod['metadata']['uid']==pod['metadata']['uid']and all(s['ready']and s['restartCount']==0 for s in latestPod['status']['containerStatuses'])
 after=snapshot(c);durable(ROOT/'PROTECTED_AFTER.json',after)
 durable(ROOT/'DEPLOYMENT_READBACK_PRIVATE.json',d)
 result={'new_Test_ready':True,'source_hashes_match_exact_CM':True,'pod_uid':pod['metadata']['uid'],'containers':[{'name':s['name'],'imageID':s['imageID'],'ready':s['ready'],'restarts':s['restartCount']}for s in pod['status']['containerStatuses']],'existing_protected_specs_unchanged':before==after,'application_acceptance_pending':True,'Production_changes_by_operator':0,'historical_resend':0}
 durable(ROOT/'ROLLOUT_READBACK.json',result);print(json.dumps(result))
 assert before==after,'Existing protected DSH/normal-bridge/docs drift; retain receipts/resources for coordinated review'
if __name__=='__main__':main()
