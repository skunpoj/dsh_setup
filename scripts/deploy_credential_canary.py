"""Create disposable gateway validation, without mounting production accounts or files."""
import argparse,hashlib,json,secrets,subprocess
from pathlib import Path
from integrate_credential_gateway import integrate

def main():
 p=argparse.ArgumentParser();p.add_argument('--snapshot',required=True);p.add_argument('--private-output',required=True);p.add_argument('--host',required=True);a=p.parse_args();out=Path(a.private_output)
 def k(*args,obj=None):
  r=subprocess.run(['kubectl','-n','llm',*args],input=json.dumps(obj).encode() if obj else None,capture_output=True,timeout=120)
  if r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace')[:300])
  return r.stdout.decode('utf-8')
 def apply(obj):k('apply','--server-side','--field-manager=dsh-credential-rollout','-f','-',obj=obj)
 data=json.loads(Path(a.snapshot).read_text(encoding='utf-8'));data['auth_proxy.js']=integrate(data['auth_proxy.js'])
 for name in ['credential_gateway.js','credential_broker.js','credential_identity.js','platform_ui.js','bot_platform.css']:data[name]=(Path(__file__).parent/name).read_text(encoding='utf-8')
 data['dsh-connection.cjs']=(Path(__file__).resolve().parents[1]/'container/dsh-connection.cjs').read_text(encoding='utf-8')
 digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest();source='dsh-credential-canary-source-'+digest[:12]
 apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':source},'immutable':True,'data':data})
 prior=out/'canary-private.json'
 if prior.exists():
  saved=json.loads(prior.read_text(encoding='utf-8'));secret=saved['passwords'];tokens=saved['tokens']
 else:secret={u:secrets.token_urlsafe(24) for u in ['cred-qa-a','cred-qa-b']};tokens={u+'-'+m:secrets.token_hex(24) for u in secret for m in ['secure','internet']}
 node="let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',()=>{const {hashPassword}=require('./scripts/password_store');console.log(JSON.stringify(Object.fromEntries(Object.entries(JSON.parse(s)).map(([u,p])=>[u,{...hashPassword(p),internetAllowed:true}]))));});"
 hashes=json.loads(subprocess.run(['node','-e',node],input=json.dumps(secret).encode(),capture_output=True,check=True).stdout)
 routes={u:{m:{'host':'127.0.0.1','port':3081,'tokenFile':'/runtime-tokens/'+u+'-'+m} for m in ['secure','internet']}for u in secret}
 ips={n:json.loads(k('get','service',n,'-o','json'))['spec']['clusterIP']for n in ['dsh-credential-off','dsh-credential-on']}
 config={'trustedHost':a.host,'caFile':'/tool-tls/ca.pem','gatewayKeyFiles':{'off':'/gateway-keys/off','on':'/gateway-keys/on'},'brokers':{m:'https://'+ips['dsh-credential-'+m]+':8443'for m in ['off','on']},'adapterFile':'/gateway-source/dsh-connection.cjs','tools':{'url':'https://127.0.0.1:3443','port':3443,'keyFile':'/tool-tls/tls.key','certFile':'/tool-tls/tls.crt'}}
 backend="require('http').createServer((q,s)=>{s.setHeader('Content-Type','text/html');s.end('<html><body>Disposable runtime fixture</body></html>')}).listen(3081,'127.0.0.1')"
 fixture={'users.json':json.dumps(hashes),'routes.json':json.dumps(routes),'gateway.json':json.dumps(config),'backend.js':backend}
 apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'dsh-credential-canary-fixture'},'data':fixture})
 apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'dsh-credential-canary-tokens'},'stringData':tokens})
 live=json.loads(k('get','deployment','dsh-environment-gateway','-o','json'));image=live['spec']['template']['spec']['containers'][0]['image']
 env={'PORT':'3080','DSH_TRUSTED_HOST':a.host,'DSH_COOKIE_NAME':'dsh_credential_canary','DSH_COOKIE_DOMAIN':a.host,'DSH_COOKIE_SECURE':'true','WORKSPACE_ROOT':'/workspace','DSH_USER_STORE_PATH':'/auth/users.json','DSH_USER_SETTINGS_PATH':'/auth/settings.json','DSH_USER_TARGETS_FILE':'/fixture/routes.json','DSH_AUDIT_DIR':'/audit','DSH_USER_CREDENTIAL_GATEWAY_CONFIG':'/fixture/gateway.json','DSH_JUPYTER_ON_DEMAND':'false','DSH_ALLOW_REGISTRATION':'false'}
 apply({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'dsh-credential-canary-auth'},'spec':{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'100Mi'}}}})
 volumes=[{'name':'source','configMap':{'name':source}},{'name':'fixture','configMap':{'name':'dsh-credential-canary-fixture'}},{'name':'tokens','secret':{'secretName':'dsh-credential-canary-tokens'}},{'name':'tool-tls','secret':{'secretName':'dsh-credential-tools-tls','defaultMode':288}},{'name':'gateway-keys','secret':{'secretName':'dsh-credential-gateway-key','defaultMode':288}},{'name':'auth','persistentVolumeClaim':{'claimName':'dsh-credential-canary-auth'}}]+[{'name':n,'emptyDir':{}}for n in ['workspace','audit']]
 mounts=[{'name':n,'mountPath':path,'readOnly':True}for n,path in [('source','/gateway-source'),('fixture','/fixture'),('tokens','/runtime-tokens'),('tool-tls','/tool-tls'),('gateway-keys','/gateway-keys')]]+[{'name':n,'mountPath':'/'+n}for n in ['auth','workspace','audit']]
 apply({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'dsh-credential-canary'},'spec':{'replicas':1,'strategy':{'type':'Recreate','rollingUpdate':None},'selector':{'matchLabels':{'app':'dsh-credential-canary'}},'template':{'metadata':{'labels':{'app':'dsh-credential-canary'}},'spec':{'automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001},'containers':[{'name':'gateway','image':image,'command':['sh','-c','test -f /auth/users.json || cp /fixture/users.json /auth/users.json; if [ -d /auth/.browser-sessions ]; then chmod 700 /auth/.browser-sessions; if [ -f /auth/.browser-sessions/sessions.json ]; then chmod 600 /auth/.browser-sessions/sessions.json; fi; fi; node /fixture/backend.js & exec node /gateway-source/auth_proxy.js'],'env':[{'name':n,'value':v}for n,v in env.items()],'resources':{'requests':{'cpu':'50m','memory':'128Mi'},'limits':{'cpu':'1','memory':'512Mi'}},'volumeMounts':mounts,'readinessProbe':{'tcpSocket':{'port':3080},'initialDelaySeconds':2}}],'volumes':volumes}}}})
 apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-credential-canary'},'spec':{'podSelector':{'matchLabels':{'app':'dsh-credential-canary'}},'policyTypes':['Ingress','Egress'],'ingress':[{'from':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}}}],'ports':[{'port':3080,'protocol':'TCP'}]}],'egress':[{'to':[{'podSelector':{'matchLabels':{'dsh-credential-broker':'true'}}}],'ports':[{'port':8443,'protocol':'TCP'}]}]}})
 k('rollout','status','deployment/dsh-credential-canary','--timeout=90s')
 out.mkdir(exist_ok=True,parents=True);(out/'canary-private.json').write_text(json.dumps({'passwords':secret,'tokens':tokens,'host':a.host}),encoding='utf-8')
 print(json.dumps({'canaryReady':True,'gatewaySourceSHA256':digest,'productionAccountsMounted':False,'productionWorkspacesMounted':False}))

if __name__=='__main__':main()
