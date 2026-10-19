// Operator-only acceptance in the gateway. Uses a loopback child and disposable
// account store. Never opens real user passwords or copies legacy histories.
'use strict';
const fs=require('fs'),http=require('http'),crypto=require('crypto'),assert=require('assert');
const {spawn}=require('child_process');
const {hashPassword}=require('/gateway-source/password_store.js');
const WebSocket=require(require.resolve('ws',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
const root='/auth/signup-acceptance-'+crypto.randomBytes(5).toString('hex'),port=3099;
fs.mkdirSync(root,{mode:0o700});
const host=process.env.DSH_TRUSTED_HOST,adminPassword=crypto.randomBytes(24).toString('hex');
const names=['signup_qa_'+crypto.randomBytes(4).toString('hex'),'signup_qa_'+crypto.randomBytes(4).toString('hex')];
const passwords=Object.fromEntries(names.map(u=>[u,crypto.randomBytes(24).toString('hex')]));
fs.writeFileSync(root+'/users.json',JSON.stringify({admin:hashPassword(adminPassword)}),{mode:0o600});
fs.writeFileSync(root+'/routes.json',JSON.stringify({admin:{secure:{host:'unprovisioned.invalid',port:3081,tokenFile:'/runtime-tokens/nonexistent/admin'}}}));
const env={...process.env,PORT:String(port),DSH_LISTEN_HOST:'127.0.0.1',WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:root+'/users.json',DSH_USER_SETTINGS_PATH:root+'/settings.json',DSH_USER_TARGETS_FILE:root+'/routes.json',DSH_SIGNUP_POOL_FILE:'/signup-pool/test.json',DSH_ALLOW_REGISTRATION:'true',DSH_COOKIE_NAME:'dsh_signup_acceptance',DSH_AUDIT_DIR:root+'/audit'};
delete env.DSH_AUTH_PASS;
let child;const state=[];const result={gatewaySourceSHA256:crypto.createHash('sha256').update(fs.readFileSync('/gateway-source/auth_proxy.js')).digest('hex'),scope:'Loopback candidate using deployed gateway code and four real empty private runtimes',accountsCreated:0,nativeSessions:0,crossUserHistoryDenials:0,crossEnvironmentHistoryDenials:0,defaultInternetDenials:0,ordinaryAdminDenials:0,terminalWrites:0,terminalReadbacks:0,actualDshReplies:0};
const request=(method,path,body='',cookie='',extra={})=>new Promise((resolve,reject)=>{const r=http.request({host:'127.0.0.1',port,method,path,headers:{host,cookie,'Content-Type':'application/x-www-form-urlencoded',...extra}},res=>{let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,cookie:(res.headers['set-cookie']||[]).map(c=>c.split(';')[0]).join('; ')}));});r.setTimeout(25000,()=>r.destroy(Error('candidate request timeout: '+method+' '+path)));r.on('error',reject);r.end(body);});
const login=(user,mode='off')=>request('POST','/login',new URLSearchParams({username:user,password:user==='admin'?adminPassword:passwords[user],internet:mode}).toString());
const rpc=async(cookie,method,args,extra={})=>{const r=await request('POST','/api/'+method,JSON.stringify({type:'client-request',rpcId:crypto.randomUUID(),method,payload:{args}}),cookie,{'Content-Type':'application/json',Origin:'http://'+host,...extra});assert.equal(r.status,200,method+" HTTP "+r.status);return JSON.parse(r.text);};
const value=r=>{assert.equal(r.result?.ok,true,JSON.stringify(r.result?.error||{}));return r.result.value;};
async function start(){child=spawn(process.execPath,['/gateway-source/auth_proxy.js'],{env,stdio:'ignore'});for(let i=0;i<80;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,100));}}throw Error('candidate did not start');}
async function stop(){if(child&&child.exitCode===null){child.kill('SIGTERM');await new Promise(r=>child.once('exit',r));}}
async function terminal(cookie,marker,phase){return new Promise((resolve,reject)=>{
 const ws=new WebSocket('ws://127.0.0.1:'+port+'/proxy/7681/ws','tty',{headers:{Host:host,Cookie:cookie,Origin:'https://'+host,'X-DSH-User':'forged_other_user'}});
 let output='';const timer=setTimeout(()=>{ws.terminate();reject(Error('terminal marker check timed out'));},25000);
 const code=`from pathlib import Path; import os; paths=[Path('/workspace/.signup-acceptance-marker'),Path('/state/attachments/.signup-acceptance-marker')]; `+(phase==='create'?`[(p.open('xb').write(bytes.fromhex('${Buffer.from(marker).toString('hex')}'))) for p in paths]; `:'')+`assert all(p.read_text()==paths[0].read_text() for p in paths); print(paths[0].read_text()); print('UID='+str(os.getuid())); assert not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()`;
 const command="python3 -c '"+code.replaceAll("'","'\\''")+"'";
 ws.on('open',()=>{ws.send(JSON.stringify({AuthToken:'',columns:120,rows:30}));setTimeout(()=>ws.send('0'+command+'\r'),500);});
 ws.on('message',data=>{if(data[0]!==48)return;output+=data.subarray(1).toString();if(output.includes(marker)&&output.includes('UID=10001')){clearTimeout(timer);ws.send('0exit\r');ws.close();resolve();}});
 ws.on('error',e=>{clearTimeout(timer);reject(e);});
});}
async function exactReply(cookie,sid){const expected='SIGNUP_PRIVATE_OK',started=Date.now();const baseline=value(await rpc(cookie,'session/projections',{request:{sessionId:sid}})).asOfSeq;
 value(await rpc(cookie,'session/prompt',{request:{sessionId:sid,requestId:crypto.randomUUID(),content:[{type:'text',text:'Reply exactly '+expected+'. Do not use tools.'}],mode:'queue'}}));
 while(Date.now()-started<120000){const p=value(await rpc(cookie,'session/projections',{request:{sessionId:sid}}));const page=value(await rpc(cookie,'session/page',{request:{address:{kind:'session',sessionId:sid},throughSeq:p.asOfSeq,maxMessages:30}}));const events=page.records.map(x=>x.event).filter(e=>e.seq>baseline);assert(!events.some(e=>e.type==='llm/retry'));
 if(events.some(e=>e.type==='turn/end')){const text=events.filter(e=>e.type==='assistant/message').flatMap(e=>e.data.message.content).filter(x=>x.type==='text').map(x=>x.text||'').join('');assert.equal(text.trim(),expected);result.actualDshReplies++;return;}await new Promise(r=>setTimeout(r,300));}
 throw Error('native DSH response exceeded deadline');}
(async()=>{try{await start();assert((await request('GET','/login')).text.includes('id="tab-register"'));result.signupCapacitySamples=[JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots];assert.equal(result.signupCapacitySamples[0],2);
 for(const user of names){const r=await request('POST','/register',new URLSearchParams({username:user,password:passwords[user],confirm_password:passwords[user],role:'admin',internet:'on'}).toString());assert.equal(r.status,200);result.accountsCreated++;result.signupCapacitySamples.push(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots);assert.equal(result.signupCapacitySamples.at(-1),2-result.accountsCreated);assert.equal((await login(user,'on')).status,403);result.defaultInternetDenials++;}
 const stored=JSON.parse(fs.readFileSync(root+'/users.json'));assert.notEqual(stored[names[0]].runtimeSlot,stored[names[1]].runtimeSlot);for(const user of names){assert.equal(stored[user].internetAllowed,false);assert.equal(stored[user].scheme,'scrypt-v1');}
 let admin=(await login('admin')).cookie;const info=JSON.parse((await request('GET','/api/admin/users','',admin)).text);
 for(const user of names){let offline=await login(user);assert.equal(offline.status,302);assert.equal((await request('GET','/api/admin/users','',offline.cookie,{'X-DSH-Role':'admin'})).status,403);result.ordinaryAdminDenials++;
  const grant=await request('POST','/api/admin/users',new URLSearchParams({action:'allow-internet',user}).toString(),admin,{'X-DSH-Admin-CSRF':info.csrfToken});assert.equal(grant.status,200);
  for(const mode of ['off','on']){const auth=await login(user,mode);assert.equal(auth.status,302);const list=value(await rpc(auth.cookie,'session/list',{_request:{}}));assert.equal(list.items.length,0,'New workspace inherited a history');const sid=value(await rpc(auth.cookie,'session/create',{request:{cwd:'/workspace'}})).sessionId;value(await rpc(auth.cookie,'session/rename',{request:{sessionId:sid,title:'SYNTHETIC SIGNUP '+user+' '+mode}}));const marker='PRIVATE_'+crypto.randomBytes(12).toString('hex');await terminal(auth.cookie,marker,'create');result.terminalWrites++;state.push({user,mode,cookie:auth.cookie,sid,marker});result.nativeSessions++;if(mode==='off')await exactReply(auth.cookie,sid);}
 }
 for(const own of state){for(const other of state.filter(x=>x!==own&&(x.user===own.user||x.mode===own.mode))){const denied=await rpc(own.cookie,'session/page',{request:{address:{kind:'session',sessionId:other.sid},throughSeq:100000,maxMessages:10}},{'X-DSH-User':other.user,'X-DSH-Internet-Access':other.mode});assert.equal(denied.result?.ok,false);if(own.user!==other.user)result.crossUserHistoryDenials++;else result.crossEnvironmentHistoryDenials++;}}
 assert.equal((await request('POST','/register',new URLSearchParams({username:'signup_overflow',password:'long-synthetic-password',confirm_password:'long-synthetic-password'}).toString())).status,503);result.fullPoolRefused=true;
 result.checkpoint=root+'/continue';console.log(JSON.stringify({phase:'awaiting-runtime-replacement',...result}));
 const startWait=Date.now();while(!fs.existsSync(root+'/continue')){if(Date.now()-startWait>600000)throw Error('Operator runtime-replacement deadline');await new Promise(r=>setTimeout(r,500));}
 await stop();await start();
 for(const own of state){const auth=await login(own.user,own.mode);assert.equal(auth.status,302);const list=value(await rpc(auth.cookie,'session/list',{_request:{}}));assert(list.items.some(x=>x.sessionId===own.sid));await terminal(auth.cookie,own.marker,'verify');result.terminalReadbacks++;}
 admin=(await login('admin')).cookie;const fresh=JSON.parse((await request('GET','/api/admin/users','',admin)).text);assert.equal((await request('POST','/api/admin/users',new URLSearchParams({action:'deny-internet',user:names[0]}).toString(),admin,{'X-DSH-Admin-CSRF':fresh.csrfToken})).status,200);assert.equal((await login(names[0],'on')).status,403);assert.equal((await login(names[0],'off')).status,302);result.adminInternetRevocation=true;result.accountAssignmentSurvivedGatewayRestart=true;assert.equal(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots,0);result.signupCapacitySurvivedRestart=true;result.status='passed';delete result.checkpoint;console.log(JSON.stringify(result));
}finally{await stop();fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(JSON.stringify({status:'failed',error:e.message}));process.exitCode=1;});
