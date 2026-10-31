'use strict';
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http'),net=require('net');
const {spawn}=require('child_process'),{hashPassword}=require('../scripts/password_store'),{TTL_MS}=require('../scripts/session_store');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-session-restart-')),held=new Set();let gateway,port,backendPort,diagnostic='';
const backend=http.createServer((q,r)=>{r.setHeader('Content-Type','application/json');r.end(JSON.stringify({user:q.headers['x-dsh-user']}));});
backend.on('upgrade',(q,s)=>{held.add(s);s.on('error',()=>s.destroy());s.on('close',()=>held.delete(s));s.write('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');});
const pause=ms=>new Promise(r=>setTimeout(r,ms));
function request(method,route,body='',cookie='',headers={}){return new Promise((resolve,reject)=>{const q=http.request({host:'127.0.0.1',port,method,path:route,headers:{Host:'dsh.test.local',Cookie:cookie,'Content-Type':'application/x-www-form-urlencoded',...headers}},r=>{let text='';r.on('data',b=>text+=b);r.on('end',()=>resolve({status:r.statusCode,text,headers:r.headers,cookie:r.headers['set-cookie']?.[0]?.split(';')[0]}));});q.on('error',reject);q.setTimeout(3000,()=>q.destroy(Error('Fixture deadline')));q.end(body);});}
async function start(){gateway=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...Object.fromEntries(Object.entries(process.env).filter(([k])=>!/^(DSH_|AUTH_|WORKSPACE_ROOT$)/.test(k))),PORT:String(port),WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_OFFLINE_HOST:'127.0.0.1',DSH_OFFLINE_PORT:String(backendPort),DSH_TRUSTED_HOST:'dsh.test.local',DSH_COOKIE_SECURE:'false'},stdio:['ignore','ignore','pipe']});gateway.stderr.on('data',b=>diagnostic+=b);for(let i=0;i<80;i++){if(gateway.exitCode!==null)throw Error('Gateway refused startup');try{await request('GET','/login');return;}catch{await pause(40);}}throw Error('Gateway startup deadline');}
async function stop(){if(gateway?.exitCode===null){gateway.kill();await new Promise(r=>gateway.once('exit',r));}}
async function login(user,password='synthetic-'+user){const r=await request('POST','/login',new URLSearchParams({username:user,password,internet:'off'}).toString());assert.equal(r.status,302);assert(r.cookie);return r.cookie;}
const authenticated=async cookie=>(await request('GET','/api/auth/session','',cookie)).status;
function upgrade(cookie,origin='http://dsh.test.local',onOpen){
 return new Promise((resolve,reject)=>{let text='',opened=false;const s=net.connect(port,'127.0.0.1',()=>s.write(`GET /socket HTTP/1.1\r\nHost: dsh.test.local\r\nCookie: ${cookie}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nOrigin: ${origin}\r\n\r\n`));const timer=setTimeout(()=>s.destroy(Error('Upgrade deadline')),6000);s.on('error',reject);s.on('data',b=>{text+=b;if(text.includes('\r\n\r\n')){const status=Number(text.split(' ')[1]);if(status!==101)s.end();else if(!opened){opened=true;if(onOpen)Promise.resolve(onOpen()).catch(reject);}}});s.on('close',()=>{clearTimeout(timer);resolve({status:Number(text.split(' ')[1]),text});});});
}
(async()=>{try{
 fs.writeFileSync(path.join(root,'users.json'),JSON.stringify(Object.fromEntries(['admin','alice','bobby'].map(u=>[u,hashPassword('synthetic-'+u)]))));
 await new Promise(r=>backend.listen(0,'127.0.0.1',r));backendPort=backend.address().port;const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));port=probe.address().port;await new Promise(r=>probe.close(r));
 await start();let admin=await login('admin'),alice=await login('alice'),bob=await login('bobby');
 const originalUsers=fs.readFileSync(path.join(root,'users.json'));
 await stop();await start();for(const c of [admin,alice,bob])assert.equal(await authenticated(c),200);
 assert.equal((await request('GET','/api/admin/users','',alice)).status,403);
 const anon=await upgrade('');assert.equal(anon.status,401);assert(anon.text.includes('AUTHENTICATION_REQUIRED'));
 const foreign=await upgrade(alice,'https://hostile.example.invalid');assert.equal(foreign.status,403);
 let info=JSON.parse((await request('GET','/api/admin/users','',admin)).text);
 const revoke=await request('POST','/api/admin/users',new URLSearchParams({action:'revoke',user:'alice'}).toString(),admin,{Origin:'http://dsh.test.local','X-DSH-Admin-CSRF':info.csrfToken});assert.equal(revoke.status,200);
 await stop();await start();assert.equal(await authenticated(alice),401);assert.equal(await authenticated(bob),200);assert.equal(await authenticated(admin),200);assert.equal(fs.readFileSync(path.join(root,'users.json')).toString(),originalUsers.toString());
 alice=await login('alice');const change=await request('POST','/change-password',new URLSearchParams({username:'alice',old_password:'synthetic-alice',new_password:'synthetic-replacement-password'}).toString());assert.equal(change.status,200,'Password change failure: '+change.text+' '+diagnostic.slice(-500));assert.equal(await authenticated(alice),401);
 await stop();await start();assert.equal(await authenticated(alice),401);assert.equal(await authenticated(bob),200);
 alice=await login('alice','synthetic-replacement-password');assert.equal((await upgrade(alice,'http://dsh.test.local',async()=>assert.equal((await request('GET','/logout','',alice)).status,302))).status,101);await stop();await start();assert.equal(await authenticated(alice),401);
 alice=await login('alice','synthetic-replacement-password');await stop();const file=path.join(root,'.browser-sessions','sessions.json'),store=JSON.parse(fs.readFileSync(file));for(const r of store.sessions)if(r.user==='alice')r.created=Date.now()-TTL_MS+2500;fs.writeFileSync(file,JSON.stringify(store),{mode:0o600});await start();assert.equal(await authenticated(alice),200);
 const expiry=await upgrade(alice);assert.equal(expiry.status,101);assert.equal(await authenticated(alice),401);assert.equal(await authenticated(bob),200);assert.equal(gateway.exitCode,null);
 console.log(JSON.stringify({passed:true,actualGatewayProcessReplacement:true,sameCookiesSurviveRestart:3,durableLogout:true,heldWebSocketClosedOnLogout:true,durableUserRevocation:true,passwordChangeInvalidatesOldSessions:true,unrelatedUserRetained:true,anonymousUpgrade401:true,foreignOriginUpgrade403:true,heldWebSocketClosedAtServerExpiry:true,modelCalls:0,productionRequests:0}));
}finally{await stop();for(const s of held)s.destroy();await new Promise(r=>backend.close(r));assert(root.startsWith(path.join(os.tmpdir(),'dsh-session-restart-')));fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
