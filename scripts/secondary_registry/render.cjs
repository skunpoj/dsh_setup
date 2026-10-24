'use strict';
// Pure renderer: no cluster calls, Secret reads, keys, apply or replacement.
const crypto=require('node:crypto'), net=require('node:net');
const FILES=['registry_runtime.js','registry_native_bridge.js','registry_token_https.js','registry_token_service.js','registry_scope_policy.js','registry_jwt_signer.js','registry_machine_service.js'];
const dns=v=>typeof v==='string'&&v.length<=63&&/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(v);
function render(c,source){
 const keys=['namespace','prefix','host','node','storageClass','storageGi','registryImage','tokenImage','edgeTlsSecret','backendTlsSecret','backendTrustSecret','signingSecret','publicSigningSecret','machineSecret','issuer','allowedPeers','sourceCidrs','ingressNamespace','ingressLabels','ingressClass'];
 if(!c||Object.keys(c).sort().join()!=keys.sort().join())throw Error('Exact non-secret configuration required');
 for(const k of ['namespace','prefix','node','storageClass','edgeTlsSecret','backendTlsSecret','backendTrustSecret','signingSecret','publicSigningSecret','machineSecret','ingressNamespace','ingressClass'])if(!dns(c[k]))throw Error('Invalid DNS label: '+k);
 if(!c.namespace.endsWith('-test')||!c.prefix.endsWith('-test')||c.prefix.length>35)throw Error('Only a dedicated Test namespace/prefix is supported');
 if(typeof c.host!=='string'||c.host.length>253||!c.host.includes('.')||!c.host.split('.').every(dns))throw Error('Explicit registry FQDN required');
 for(const k of ['registryImage','tokenImage'])if(!/^[a-z0-9./:_-]+@sha256:[a-f0-9]{64}$/.test(c[k]))throw Error('Digest-pinned image required');
 if(!Number.isInteger(c.storageGi)||c.storageGi<10||c.storageGi>100)throw Error('Capacity-qualified storage 10..100 Gi required');
 if(!Array.isArray(c.allowedPeers)||!c.allowedPeers.length||c.allowedPeers.some(x=>!net.isIP(x)))throw Error('Exact ingress peer IPs required');
 // Exact source addresses only; do not infer client identity from shared ingress/proxy IPs.
 if(!Array.isArray(c.sourceCidrs)||!c.sourceCidrs.length||c.sourceCidrs.some(x=>{const a=x.split('/');return a.length!==2||!(net.isIP(a[0])===4&&a[1]==='32'||net.isIP(a[0])===6&&a[1]==='128');}))throw Error('Observed exact /32 or /128 source addresses required');
 if(!c.ingressLabels||typeof c.ingressLabels!=='object'||Array.isArray(c.ingressLabels)||!Object.keys(c.ingressLabels).length||Object.entries(c.ingressLabels).some(([k,v])=>!/^[a-zA-Z0-9./_-]+$/.test(k)||typeof v!=='string'||!v))throw Error('Explicit ingress selectors required');
 if(typeof c.issuer!=='string'||!/^[a-zA-Z0-9._:-]{1,128}$/.test(c.issuer))throw Error('Explicit token issuer required');
 const owned=['backendTlsSecret','backendTrustSecret','signingSecret','publicSigningSecret','machineSecret'];
 if(owned.some(k=>!c[k].startsWith(c.prefix+'-'))||new Set(owned.map(k=>c[k])).size!==owned.length||owned.some(k=>c[k]===c.edgeTlsSecret))throw Error('Separate dedicated protected references required');
 if(!source||Object.keys(source).sort().join()!=FILES.slice().sort().join()||Object.values(source).some(v=>typeof v!=='string'||!v))throw Error('Complete runtime source required');
 const data=Object.fromEntries(FILES.slice().sort().map(k=>[k,source[k].replace(/\r\n?/g,'\n')]));
 const hash=crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex'), p=c.prefix,ns=c.namespace;
 const meta=name=>({name,namespace:ns,labels:{'app.kubernetes.io/part-of':p}});
 const mount=(name,mountPath,subPath)=>({name,mountPath,readOnly:true,...(subPath?{subPath}:{})});
 const secret=(name,secretName)=>({name,secret:{secretName,defaultMode:292}});
 const config={version:1,mode:'machine-only',bindHost:'0.0.0.0',port:5443,issuer:c.issuer,service:c.host,allowedPeers:c.allowedPeers,perMinute:30,machinePrincipalsPath:'/machine-principals/machine-principals.json',signingKeyPath:'/signing/key.pem',tlsKeyPath:'/tls/tls.key',tlsCertPath:'/tls/tls.crt'};
 const registry={version:0.1,log:{level:'info',formatter:'json'},storage:{filesystem:{rootdirectory:'/var/lib/registry'},delete:{enabled:false}},http:{addr:':5000',host:'https://'+c.host,tls:{certificate:'/tls/tls.crt',key:'/tls/tls.key'}},auth:{token:{realm:'https://'+c.host+'/api/registry/token',service:c.host,issuer:c.issuer,rootcertbundle:'/token-public/rootcertbundle.pem',signingalgorithms:['RS256']}}};
 const configData={'config.json':JSON.stringify(registry),'runtime.json':JSON.stringify(config)};
 const configName=p+'-config-'+crypto.createHash('sha256').update(JSON.stringify(configData)).digest('hex').slice(0,12), runtimeName=p+'-runtime-'+hash.slice(0,12);
 const items=[{apiVersion:'v1',kind:'ConfigMap',metadata:meta(runtimeName),immutable:true,data},{apiVersion:'v1',kind:'ConfigMap',metadata:meta(configName),immutable:true,data:configData},{apiVersion:'v1',kind:'PersistentVolumeClaim',metadata:meta(p+'-data'),spec:{accessModes:['ReadWriteOnce'],storageClassName:c.storageClass,resources:{requests:{storage:c.storageGi+'Gi'}}}}];
 for(const role of ['registry','token']){
  const labels={app:p+'-'+role}, port=role==='registry'?5000:5443;
  const volumes=[secret('tls',c.backendTlsSecret),{name:'config',configMap:{name:configName}}];
  const mounts=[mount('tls','/tls/tls.crt','tls.crt'),mount('tls','/tls/tls.key','tls.key')];
  if(role==='registry'){volumes.push({name:'storage',persistentVolumeClaim:{claimName:p+'-data'}},secret('token-public',c.publicSigningSecret));mounts.push(mount('config','/config'),{name:'storage',mountPath:'/var/lib/registry'},mount('token-public','/token-public'));}
  else{volumes.push({name:'runtime',configMap:{name:runtimeName}},secret('signing',c.signingSecret),secret('machine',c.machineSecret));mounts.push(mount('config','/config/runtime.json','runtime.json'),mount('runtime','/runtime'),mount('signing','/signing/key.pem','key.pem'),mount('machine','/machine-principals/machine-principals.json','machine-principals.json'));}
  const container={name:role,image:role==='registry'?c.registryImage:c.tokenImage,imagePullPolicy:'IfNotPresent',command:[role==='registry'?'registry':'node'],args:role==='registry'?['serve','/config/config.json']:['/runtime/registry_runtime.js','/config/runtime.json'],ports:[{name:'https',containerPort:port}],securityContext:{runAsNonRoot:true,runAsUser:10001,runAsGroup:10001,allowPrivilegeEscalation:false,readOnlyRootFilesystem:true,capabilities:{drop:['ALL']}},resources:{requests:{cpu:'100m',memory:'128Mi'},limits:{cpu:'500m',memory:'512Mi'}},volumeMounts:mounts,readinessProbe:{tcpSocket:{port:'https'},periodSeconds:10}};
  if(role==='registry')container.env=[{name:'OTEL_TRACES_EXPORTER',value:'none'},{name:'REGISTRY_HTTP_SECRET',valueFrom:{secretKeyRef:{name:c.machineSecret,key:'registry-http-secret'}}}];
  items.push({apiVersion:'apps/v1',kind:'Deployment',metadata:meta(p+'-'+role),spec:{replicas:1,strategy:{type:'Recreate'},selector:{matchLabels:labels},template:{metadata:{labels},spec:{nodeSelector:{'kubernetes.io/hostname':c.node},automountServiceAccountToken:false,securityContext:{seccompProfile:{type:'RuntimeDefault'},...(role==='registry'?{fsGroup:10001,fsGroupChangePolicy:'OnRootMismatch'}:{})},containers:[container],volumes}}}},{apiVersion:'v1',kind:'Service',metadata:meta(p+'-'+role),spec:{type:'ClusterIP',selector:labels,ports:[{name:'https',port,targetPort:'https'}]}},{apiVersion:'networking.k8s.io/v1',kind:'NetworkPolicy',metadata:meta(p+'-'+role+'-network'),spec:{podSelector:{matchLabels:labels},policyTypes:['Ingress','Egress'],ingress:[{from:[{namespaceSelector:{matchLabels:{'kubernetes.io/metadata.name':c.ingressNamespace}},podSelector:{matchLabels:c.ingressLabels}}],ports:[{protocol:'TCP',port}]}],egress:[]}});
 }
 const im=meta(p+'-ingress'); im.annotations={'nginx.ingress.kubernetes.io/backend-protocol':'HTTPS','nginx.ingress.kubernetes.io/ssl-redirect':'true','nginx.ingress.kubernetes.io/proxy-ssl-verify':'on','nginx.ingress.kubernetes.io/proxy-ssl-server-name':'on','nginx.ingress.kubernetes.io/proxy-ssl-name':c.host,'nginx.ingress.kubernetes.io/proxy-ssl-secret':ns+'/'+c.backendTrustSecret,'nginx.ingress.kubernetes.io/whitelist-source-range':c.sourceCidrs.join(','),'nginx.ingress.kubernetes.io/proxy-body-size':'8g','nginx.ingress.kubernetes.io/proxy-request-buffering':'off','nginx.ingress.kubernetes.io/proxy-buffering':'off','nginx.ingress.kubernetes.io/proxy-http-version':'1.1','nginx.ingress.kubernetes.io/proxy-read-timeout':'300','nginx.ingress.kubernetes.io/proxy-send-timeout':'300'};
 items.push({apiVersion:'networking.k8s.io/v1',kind:'Ingress',metadata:im,spec:{ingressClassName:c.ingressClass,tls:[{hosts:[c.host],secretName:c.edgeTlsSecret}],rules:[{host:c.host,http:{paths:[{path:'/api/registry/token',pathType:'Exact',backend:{service:{name:p+'-token',port:{number:5443}}}},{path:'/v2',pathType:'Prefix',backend:{service:{name:p+'-registry',port:{number:5000}}}}]}}]}});
 const priority={NetworkPolicy:0,ConfigMap:1,PersistentVolumeClaim:2,Service:3,Deployment:4,Ingress:5};items.sort((a,b)=>priority[a.kind]-priority[b.kind]);
 return {apiVersion:'v1',kind:'List',items};
}
if(require.main===module){const fs=require('node:fs'),path=require('node:path');if(process.argv.length!==4)throw Error('Supply config JSON and NEW review output path');const source=Object.fromEntries(FILES.map(n=>[n,fs.readFileSync(path.join(__dirname,n),'utf8')]));fs.writeFileSync(process.argv[3],JSON.stringify(render(JSON.parse(fs.readFileSync(process.argv[2],'utf8')),source),null,2),{flag:'wx',mode:384});console.log('Review manifest created; no cluster calls or Secret material.');}
module.exports={render,FILES};
