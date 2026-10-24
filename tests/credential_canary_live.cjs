'use strict';
// Run inside the disposable gateway; stdin carries only disposable fixture passwords.
const assert=require('node:assert/strict'),http=require('node:http'),https=require('node:https'),fs=require('node:fs');
let input='';process.stdin.on('data',b=>input+=b);process.stdin.on('end',()=>main(JSON.parse(input)).catch(()=>{console.error('Credential gateway live acceptance failed');process.exitCode=1;}));
async function main(config){
 const request=(route,{method='GET',body,cookie,csrf,origin=config.host}={})=>new Promise((resolve,reject)=>{
  const data=body===undefined?null:Buffer.from(typeof body==='string'?body:JSON.stringify(body));
  const q=http.request({host:'127.0.0.1',port:3080,path:route,method,headers:{Host:config.host,...(cookie?{Cookie:cookie}:{}),...(data?{'Content-Type':typeof body==='string'?'application/x-www-form-urlencoded':'application/json','Content-Length':data.length,Origin:'https://'+origin}:{}),...(csrf?{'X-DSH-Credential-CSRF':csrf}:{})}},r=>{const chunks=[];r.on('data',b=>chunks.push(b));r.on('end',()=>{const text=Buffer.concat(chunks).toString();let value;try{value=JSON.parse(text);}catch{}resolve({status:r.statusCode,headers:r.headers,text,value});});});q.setTimeout(25000,()=>q.destroy(Error('Timeout')));q.on('error',reject);q.end(data);
 });
 const login=async(user,mode)=>{
  const r=await request('/login',{method:'POST',body:new URLSearchParams({username:user,password:config.passwords[user],internet:mode,auth_provider:'local'}).toString()});assert.equal(r.status,302);const cookie=r.headers['set-cookie'].find(x=>x.startsWith('dsh_credential_canary=')).split(';')[0];const p=await request('/credentials',{cookie});assert.equal(p.status,200);assert.match(p.text,/My credentials/);assert(!p.text.includes('localStorage'));return {cookie,csrf:p.text.match(/const csrf="([a-f0-9]+)"/)[1],user};
 };
 const a=await login('cred-qa-a','off'),b=await login('cred-qa-b','off'),online=await login('cred-qa-a','on');
 const action=(session,action,input)=>request('/api/user-credentials',{method:'POST',body:{action,input},cookie:session.cookie,csrf:session.csrf});
 const encrypt=(value,key)=>{const crypto=require('node:crypto');const aes=crypto.randomBytes(32),iv=crypto.randomBytes(12),c=crypto.createCipheriv('aes-256-gcm',aes,iv),input={...value};delete input.secret;const aad=Buffer.from(JSON.stringify([key.owner,key.environment,input.id,input.profile,input.workspace,input.expiresAt,[...input.operations].sort(),Object.keys(input.scopes||{}).sort().map(k=>[k,input.scopes[k]])]));c.setAAD(aad);input.secretEnvelope={key:crypto.publicEncrypt({key:key.publicKey,oaepHash:'sha256'},aes).toString('base64'),iv:iv.toString('base64'),body:Buffer.concat([c.update(value.secret),c.final(),c.getAuthTag()]).toString('base64')};return input;};
 const save={id:'canary-azure',profile:'azure-projects',workspace:'one',operations:['projects.read'],expiresAt:Date.now()+3600000,secret:'SYNTHETIC_CANARY_NOT_A_REAL_CREDENTIAL'};
 assert.equal((await action(a,'save',save)).status,428);
 assert.equal((await request('/api/user-credentials',{method:'POST',body:{action:'reauthenticate',password:config.passwords[a.user]},cookie:a.cookie,csrf:a.csrf})).status,200);
 assert.equal((await request('/api/user-credentials',{method:'POST',body:{action:'save',input:save},cookie:a.cookie,csrf:a.csrf,origin:'evil.example'})).status,403);
 assert.equal((await action(a,'save',save)).status,400);const encrypted=encrypt(save,(await request('/api/user-credentials',{cookie:a.cookie})).value.encryption);assert.equal((await action(a,'save',encrypted)).status,200);
 const listed=await request('/api/user-credentials',{cookie:a.cookie});assert(!listed.text.includes(save.secret));assert(listed.value.credentials.some(c=>c.id===save.id));
 assert(!(await request('/api/user-credentials',{cookie:b.cookie})).value.credentials.some(c=>c.id===save.id));
 assert(!(await request('/api/user-credentials',{cookie:online.cookie})).value.credentials.some(c=>c.id===save.id));
 assert.equal((await action(b,'execute',{id:save.id,workspace:'one',operation:'projects.read',parameters:{}})).status,403);
 assert.equal((await action(a,'execute',{id:save.id,workspace:'other',operation:'projects.read',parameters:{}})).status,403);
 assert.equal((await action(a,'disable',{id:save.id})).status,200);
 assert.equal((await action(a,'execute',{id:save.id,workspace:'one',operation:'projects.read',parameters:{}})).status,403);
 assert.equal((await action(a,'delete',{id:save.id})).status,200);
 assert(!(await request('/api/user-credentials',{cookie:a.cookie})).value.credentials.some(c=>c.id===save.id));
 const audit=fs.readFileSync('/audit/events.jsonl','utf8');assert(audit.includes('credential.save'));assert(!audit.includes(save.secret));assert(!audit.includes(config.passwords[a.user]));
 const tool=await new Promise((resolve,reject)=>{const data=Buffer.from(JSON.stringify({action:'list'}));const q=https.request('https://127.0.0.1:3443/v1/connections',{method:'POST',ca:fs.readFileSync('/tool-tls/ca.pem'),headers:{Authorization:'Bearer '+config.tokens['cred-qa-b-secure'],'Content-Type':'application/json','Content-Length':data.length}},r=>{let text='';r.on('data',b=>text+=b);r.on('end',()=>resolve({status:r.statusCode,data:JSON.parse(text)}));});q.on('error',reject);q.end(data);});
 assert.equal(tool.status,200);assert.equal(tool.data.data.credentials.length,0);
 const recovery={...save,id:'persistence-canary'};assert.equal((await action(a,'save',encrypt(recovery,(await request('/api/user-credentials',{cookie:a.cookie})).value.encryption))).status,200);
 console.log(JSON.stringify({browserEnvelopeRequired:true,gatewayLoginUsers:2,environmentsTested:2,recentAuthentication:true,crossOriginDenied:true,crossUserDenied:true,crossEnvironmentSeparated:true,workspaceMismatchDenied:true,metadataSecretExcluded:true,disableDeleteVerified:true,toolIdentityResolved:true,auditSecretExcluded:true,realProviderCredentialsUsed:false}));
}
