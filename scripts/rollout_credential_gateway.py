"""Guarded source-overlay rollout: preserve the actual live image, routing and storage."""
import argparse,hashlib,json,subprocess,tempfile,os,urllib.request,urllib.error
from pathlib import Path
from integrate_credential_gateway import integrate

def main():
 p=argparse.ArgumentParser();p.add_argument('--expected-source',required=True);p.add_argument('--private-output',required=True);a=p.parse_args();out=Path(a.private_output)
 def k(*args,obj=None):
  args=list(args);temporary=None
  if '--patch-file=-' in args:
   fd,temporary=tempfile.mkstemp(prefix='dsh-credential-patch-',suffix='.json')
   with os.fdopen(fd,'w',encoding='utf-8')as f:json.dump(obj,f)
   args[args.index('--patch-file=-')]='--patch-file='+temporary;obj=None
  try:r=subprocess.run(['kubectl','-n','llm',*args],input=json.dumps(obj).encode() if obj is not None else None,capture_output=True,timeout=480 if args[:2]==['rollout','status'] else 180)
  finally:
   if temporary:Path(temporary).unlink(missing_ok=True)
  if r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace')[:300])
  return r.stdout.decode('utf-8')
 def apply(obj):k('apply','--server-side','--field-manager=dsh-credential-rollout','-f','-',obj=obj)
 def external_login(host):
  with urllib.request.urlopen('https://'+host+'/login',timeout=25)as r:
   if r.status!=200 or b'name="password"' not in r.read():raise RuntimeError('External login form failed')
  try:urllib.request.urlopen('https://'+host+'/api/auth/session',timeout=25)
  except urllib.error.HTTPError as e:
   if e.code==401:return
   raise
  raise RuntimeError('External unauthenticated session was not denied')
 name='dsh-environment-gateway';live=json.loads(k('get','deployment',name,'-o','json'));template=live['spec']['template'];spec=template['spec'];index=next(i for i,c in enumerate(spec['containers'])if c['name']=='gateway');container=spec['containers'][index]
 source_index=next(i for i,v in enumerate(spec['volumes'])if v['name']=='gateway-source');old_source=spec['volumes'][source_index]['configMap']['name'];data=json.loads(k('get','configmap',old_source,'-o','json'))['data']
 if data!=json.loads(Path(a.expected_source).read_text(encoding='utf-8')):raise RuntimeError('Live source changed after qualification; requalify that source before rollout')
 if any(e['name']=='DSH_USER_CREDENTIAL_GATEWAY_CONFIG' for e in container.get('env',[])):raise RuntimeError('Credential integration already configured; inspect rather than overwrite')
 data['auth_proxy.js']=integrate(data['auth_proxy.js'])
 for n in ['credential_broker.js','credential_gateway.js','credential_identity.js','platform_ui.js','bot_platform.css']:data[n]=(Path(__file__).parent/n).read_text(encoding='utf-8')
 data['dsh-connection.cjs']=(Path(__file__).resolve().parents[1]/'container/dsh-connection.cjs').read_text(encoding='utf-8')
 digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest();source='dsh-credential-gateway-'+digest[:12]
 apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':source},'immutable':True,'data':data})
 ips={n:json.loads(k('get','service',n,'-o','json'))['spec']['clusterIP']for n in ['dsh-credential-off','dsh-credential-on','dsh-credential-tools']}
 trusted=next(e['value']for e in container['env']if e['name']=='DSH_TRUSTED_HOST')
 config={'trustedHost':trusted,'caFile':'/credential-tls/ca.pem','gatewayKeyFiles':{'off':'/credential-gateway-keys/off','on':'/credential-gateway-keys/on'},'brokers':{m:'https://'+ips['dsh-credential-'+m]+':8443'for m in ['off','on']},'adapterFile':'/gateway-source/dsh-connection.cjs','tools':{'url':'https://'+ips['dsh-credential-tools']+':3443','port':3443,'keyFile':'/credential-tls/tls.key','certFile':'/credential-tls/tls.crt'}}
 text=json.dumps(config);configname='dsh-credential-gateway-config-'+hashlib.sha256(text.encode()).hexdigest()[:12]
 apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':configname},'immutable':True,'data':{'gateway.json':text}})
 apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-credential-gateway-brokers'},'spec':{'podSelector':{'matchLabels':{'app':name}},'policyTypes':['Egress'],'egress':[{'to':[{'podSelector':{'matchLabels':{'dsh-credential-broker':'true'}}}],'ports':[{'port':8443,'protocol':'TCP'}]}]}})
 workers={'matchExpressions':[{'key':'dsh.bot.or.th/egress-mode','operator':'In','values':['offline','online']}]}
 apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-credential-tools-ingress'},'spec':{'podSelector':{'matchLabels':{'app':name}},'policyTypes':['Ingress'],'ingress':[{'from':[{'podSelector':workers}],'ports':[{'port':3443,'protocol':'TCP'}]},{'from':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'app.kubernetes.io/name':'rke2-ingress-nginx','app.kubernetes.io/component':'controller'}}}],'ports':[{'port':3080,'protocol':'TCP'}]}]}})
 apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-credential-worker-tools'},'spec':{'podSelector':workers,'policyTypes':['Egress'],'egress':[{'to':[{'podSelector':{'matchLabels':{'app':name}}}],'ports':[{'port':3443,'protocol':'TCP'}]}]}})
 external_login(trusted)
 # These volumes are mounted only in the trusted gateway container. Do not add a
 # pod fsGroup: it would alter permission bits on existing protected session files.
 volumes=[{'name':'credential-config','configMap':{'name':configname}},{'name':'credential-tls','secret':{'secretName':'dsh-credential-tools-tls','defaultMode':292}},{'name':'credential-gateway-keys','secret':{'secretName':'dsh-credential-gateway-key','defaultMode':292}}]
 if any(v['name']in{n['name']for n in volumes}for v in spec['volumes']):raise RuntimeError('Credential volume name already reserved')
 mounts=[{'name':n,'mountPath':dest,'readOnly':True}for n,dest in [('credential-config','/credential-config'),('credential-tls','/credential-tls'),('credential-gateway-keys','/credential-gateway-keys')]]
 patch=[{'op':'test','path':'/spec/template','value':template},{'op':'replace','path':f'/spec/template/spec/volumes/{source_index}/configMap/name','value':source}]
 patch += [{'op':'add','path':'/spec/template/spec/volumes/-','value':v}for v in volumes]
 patch += [{'op':'add','path':f'/spec/template/spec/containers/{index}/volumeMounts/-','value':v}for v in mounts]
 patch += [{'op':'add','path':f'/spec/template/spec/containers/{index}/env/-','value':{'name':'DSH_USER_CREDENTIAL_GATEWAY_CONFIG','value':'/credential-config/gateway.json'}}]
 out.mkdir(exist_ok=True,parents=True);(out/'production-gateway-before.json').write_text(json.dumps(live),encoding='utf-8')
 k('patch','deployment',name,'--type=json','--patch-file=-',obj=patch)
 try:
  k('rollout','status','deployment/'+name,'--timeout=420s')
  probe=r'''const fs=require('fs'),http=require('http'),https=require('https'),crypto=require('crypto');
const {httpJson}=require('/gateway-source/credential_broker');const config=JSON.parse(fs.readFileSync(process.env.DSH_USER_CREDENTIAL_GATEWAY_CONFIG));
async function read(path){return new Promise((resolve,reject)=>{http.get({host:'127.0.0.1',port:Number(process.env.PORT||3080),path,headers:{Host:config.trustedHost}},s=>{let body='';s.on('data',b=>body+=b);s.on('end',()=>resolve({status:s.statusCode,body}));}).on('error',reject);});}
async function main(){const auth=await read('/api/auth/session'),login=await read('/login');if(auth.status!==401||login.status!==200||!login.body.includes('name="password"'))throw Error('Login behavior changed');
const ca=fs.readFileSync(config.caFile);for(const mode of ['off','on']){const result=await httpJson(new URL('/v1/rpc',config.brokers[mode]),{method:'POST',ca,headers:{Authorization:'Bearer '+fs.readFileSync(config.gatewayKeyFiles[mode],'utf8').trim()},body:{owner:'u-preflight',action:'profiles',input:{}}});if(result.status!==200||!Array.isArray(result.data.data)||!result.data.data.length)throw Error('Broker unavailable');}
const denied=await httpJson(new URL('/v1/connections','https://127.0.0.1:3443'),{method:'POST',ca,headers:{Authorization:'Bearer invalid-fixture-token'},body:{action:'list'}});if(denied.status!==403)throw Error('Unauthenticated tool access');
console.log(JSON.stringify({loginRoutePreserved:true,unauthenticatedSessionDenied:true,bothBrokersReachable:true,toolAuthenticationEnforced:true,authSourceSHA256:crypto.createHash('sha256').update(fs.readFileSync('/gateway-source/auth_proxy.js')).digest('hex')}));}main().catch(e=>{console.error(e.message);process.exit(1);});'''
  tested=subprocess.run(['kubectl','-n','llm','exec','-i','deployment/'+name,'--','node','-'],input=probe.encode(),capture_output=True,timeout=75)
  if tested.returncode:raise RuntimeError('Live credential gateway behavior failed acceptance: '+tested.stderr.decode('utf-8',errors='replace')[:240])
  external_login(trusted)
  result=json.loads(tested.stdout);result['externalHTTPSLoginVerified']=True;assert result['authSourceSHA256']==hashlib.sha256(data['auth_proxy.js'].encode()).hexdigest()
  (out/'production-gateway-acceptance.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 except Exception:
  # Roll back only our exact source and additions, preserving unrelated fields.
  current=json.loads(k('get','deployment',name,'-o','json'));t=current['spec']['template'];s=t['spec'];c=s['containers'][index]
  vi=next(i for i,v in enumerate(s['volumes'])if v['name']=='gateway-source')
  if s['volumes'][vi]['configMap']['name']!=source:raise RuntimeError('Concurrent source change: automatic rollback withheld')
  names={v['name']for v in volumes};restored=[v for v in s['volumes']if v['name']not in names]
  next(v for v in restored if v['name']=='gateway-source')['configMap']['name']=old_source
  undo=[{'op':'test','path':'/spec/template','value':t},{'op':'replace','path':'/spec/template/spec/volumes','value':restored},{'op':'replace','path':f'/spec/template/spec/containers/{index}/volumeMounts','value':[v for v in c['volumeMounts']if v['name']not in names]},{'op':'replace','path':f'/spec/template/spec/containers/{index}/env','value':[e for e in c['env']if e['name']!='DSH_USER_CREDENTIAL_GATEWAY_CONFIG']}]
  k('patch','deployment',name,'--type=json','--patch-file=-',obj=undo);k('rollout','status','deployment/'+name,'--timeout=420s');external_login(trusted);raise RuntimeError('Credential rollout failed and was rolled back; external login verified')
 result={'sourceConfigMap':source,'sourceSHA256':digest,'runtimeImagePreserved':container['image'],'routingAndStoragePreserved':True,'workerRestarts':0}
 (out/'production-gateway-rollout.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
