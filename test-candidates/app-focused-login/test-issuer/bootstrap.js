'use strict';
// Separate synthetic issuer and demo; no Main account/session database or API.
const fs=require('fs'),dns=require('dns').promises,http=require('http'),path=require('path');
const {isolate,privateState,migrateAliases}=require('./isolation_headers');
const root='/auth/state',own=process.env.DSH_COOKIE_NAME;
if(own!=='dsh-auth-app-signin-test')throw Error('Unexpected Test cookie');
privateState(root);
const exclusive=(name,value)=>{const file=path.join(root,name);if(!fs.existsSync(file))fs.writeFileSync(file,JSON.stringify(value),{flag:'wx',mode:0o600});else{const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.nlink!==1||s.uid!==process.getuid())throw Error('Unexpected Test file');fs.chmodSync(file,0o600);}};
(async()=>{
 const credentials=JSON.parse(fs.readFileSync('/test-credentials/issuer.json','utf8'));
 if(credentials.username!=='appreviewer')throw Error('Only synthetic Test identity allowed');
 const {hashPassword}=require('./password_store');
 exclusive('users.json',{appreviewer:{...hashPassword(credentials.password),internetAllowed:false}});
 const runtime={host:'unprovisioned-test-runtime.invalid',port:39999,tokenFile:'/runtime-tokens/not-a-real-token'};
 exclusive('routes.json',{appreviewer:{secure:runtime}});
 const target='https://'+process.env.TEST_UPSTREAM_HOST+':9443';
 const addresses=await dns.lookup(process.env.TEST_UPSTREAM_HOST,{all:true,family:4});
 if(addresses.length!==1)throw Error('Expected one owned Test Service address');
 const policies={[target]:{addresses:[addresses[0].address],ca:fs.readFileSync('/test-tls/tls.crt','utf8')}};
 fs.writeFileSync(root+'/external-policies.json',JSON.stringify(policies),{mode:0o600});
 const aliases=['app-signin-gated-test','app-signin-public-test'];
 const base={owner:'appreviewer',ports:{},targets:{off:{type:'external',url:target+'/base/'}},enabled:true};
 exclusive('app-links.json',{[aliases[0]]:{...base,accessMode:'authenticated',publicEnvironment:null},[aliases[1]]:{...base,accessMode:'public',publicEnvironment:'off'}});
 migrateAliases(root,process.env.TEST_ALIAS_MIGRATION_SHA256);
 const inventory=()=>{const file=root+'/inventory.json',tmp=file+'.tmp';fs.writeFileSync(tmp,JSON.stringify({domain:'aiportal.bot.or.th',observedAt:new Date().toISOString(),reservedNames:['dsh-app-signin-test'],allowedNames:aliases,wildcardReady:true,wildcardConflict:false}),{mode:0o600});fs.renameSync(tmp,file);};inventory();setInterval(inventory,30000).unref();
 // Drop Main cookies before the real issuer listener ever sees the request.
 const create=http.createServer;
 http.createServer=function(...args){const i=args.findIndex(a=>typeof a==='function');if(i<0)throw Error('Expected HTTP listener');const listener=args[i];args[i]=function(req,...rest){isolate(req,own);return listener.call(this,req,...rest);};const server=create.apply(this,args),on=server.on;server.on=function(event,listener){return on.call(this,event,event==='upgrade'?function(req,...rest){isolate(req,own);return listener.call(this,req,...rest);}:listener);};return server;};
 require('./auth_proxy');
})().catch(()=>{console.error('Synthetic Test issuer startup failed');process.exitCode=1;});
