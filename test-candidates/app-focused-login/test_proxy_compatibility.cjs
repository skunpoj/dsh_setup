'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const http=require('node:http');
const https=require('node:https');
const cp=require('node:child_process');
const crypto=require('node:crypto');
const SOURCE=path.join(__dirname,'dsh-test-candidate');
const ROOT=path.join(__dirname,'gateway-fixture');
const upstreamHost=process.env.EXTERNAL_FIXTURE_HOST;
const upstreamIP=process.env.EXTERNAL_FIXTURE_IP;
assert(upstreamHost&&upstreamIP);
const upstreamOrigin='https://'+upstreamHost+':9443';
const domain='proxy-canary.invalid';
const canonical='gateway.'+domain;
const alias='external.'+domain;
const fixturePassword='fixture-only-not-a-real-account';
const cert=fs.readFileSync(__dirname+'/private-fixture/fixture-ca.pem');
const key=fs.readFileSync(__dirname+'/private-fixture/fixture-key.pem');
let child,log='',upstreamHeaders,upstreamBody;
function req(host,url,{method='GET',cookie='',headers={},body=''}={}){
 return new Promise((resolve,reject)=>{
  const r=http.request({host:'127.0.0.1',port:9150,path:url,method,headers:{Host:host,...(cookie?{Cookie:cookie}:{}),...headers}},res=>{
   let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,text}));
  });r.on('error',reject);r.setTimeout(6000,()=>r.destroy(new Error('Fixture request timeout')));r.end(body);
 });
}
async function start(baseline=false,appLogin=true){
 const env={PATH:process.env.PATH,HOME:ROOT,PORT:'9150',DSH_LISTEN_HOST:'127.0.0.1',WORKSPACE_ROOT:ROOT,
  DSH_USER_STORE_PATH:ROOT+'/users.json',DSH_USER_SETTINGS_PATH:ROOT+'/settings.json',DSH_USER_TARGETS_FILE:ROOT+'/routes.json',
  DSH_SESSION_STORE_PATH:ROOT+'/sessions.json',DSH_AUDIT_DIR:ROOT+'/audit',DSH_APP_LINKS_PATH:ROOT+'/app-links.json',
  DSH_APP_POLICY_PATH:ROOT+'/app-policy.json',DSH_APP_INVENTORY_FILE:ROOT+'/inventory.json',DSH_APP_DOMAIN:domain,
  DSH_EXTERNAL_TARGETS_FILE:ROOT+'/external-policies.json',DSH_COOKIE_NAME:'fixture_dsh',DSH_COOKIE_SECURE:'true',
  DSH_APP_LOGIN_ENABLED:appLogin?'true':'false',DSH_TRUSTED_HOST:canonical,DSH_ADMIN_USERS:'admin',DSH_ALLOW_REGISTRATION:'false'};
 child=cp.spawn(process.execPath,[path.join(baseline?__dirname+'/dsh-live-source':SOURCE,'auth_proxy.js')],{env,stdio:['ignore','pipe','pipe']});
 child.stdout.on('data',b=>log+=b);child.stderr.on('data',b=>log+=b);
 for(let i=0;i<60;i++){
  if(child.exitCode!==null)throw Error('Gateway startup failed: '+log.slice(-1500));
  try{await req(canonical,'/api/app-links');return;}catch{await new Promise(r=>setTimeout(r,50));}
 }
 throw Error('Gateway startup timed out');
}
async function stop(){if(child&&child.exitCode===null){const current=child;const exited=new Promise(r=>current.once('exit',r));current.kill('SIGTERM');await exited;}}
async function login(user,mode='off'){
 const body=new URLSearchParams({username:user,password:fixturePassword,internet:mode,application:'dsh'}).toString();
 const r=await req(canonical,'/login',{method:'POST',body,headers:{'Content-Type':'application/x-www-form-urlencoded'}});
 assert.equal(r.status,302,r.text.slice(0,200));
 return r.headers['set-cookie'].find(x=>x.startsWith('fixture_dsh=')).split(';')[0];
}
async function save(cookie,csrf,fields){
 return req(canonical,'/api/app-links',{method:'POST',cookie,headers:{Origin:'https://'+canonical,'Content-Type':'application/x-www-form-urlencoded','X-DSH-App-CSRF':csrf},body:new URLSearchParams(fields).toString()});
}
function openSocket(cookie){
 return new Promise((resolve,reject)=>{
  const r=http.request({host:'127.0.0.1',port:9150,path:'/socket',headers:{Host:alias,Cookie:cookie,Origin:'https://'+alias,Connection:'Upgrade',Upgrade:'websocket','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':'dGhlIHNhbXBsZSBub25jZQ=='}});
  const timer=setTimeout(()=>{r.destroy();reject(Error('Gateway WebSocket timeout'));},4000);
  r.on('upgrade',(res,socket)=>{clearTimeout(timer);resolve({status:res.statusCode,socket});});
  r.on('response',res=>{clearTimeout(timer);res.resume();resolve({status:res.statusCode});});
  r.on('error',reject);r.end();
 });
}
test('actual DSH source, external-target registry and persistent login',{timeout:45000},async t=>{
 fs.mkdirSync(ROOT,{mode:0o700});
 const {hashPassword}=require(SOURCE+'/password_store');
 fs.writeFileSync(ROOT+'/users.json',JSON.stringify({alice:hashPassword(fixturePassword),bobby:hashPassword(fixturePassword)}));
 const target={host:'127.0.0.1',port:39999,tokenFile:'/runtime-tokens/nonexistent-fixture-only'};
 fs.writeFileSync(ROOT+'/routes.json',JSON.stringify({alice:{secure:target,internet:target},bobby:{secure:target,internet:target}}));
 fs.writeFileSync(ROOT+'/inventory.json',JSON.stringify({observedAt:new Date().toISOString(),domain,reservedNames:['reserved'],wildcardReady:true,wildcardConflict:false}));
 fs.writeFileSync(ROOT+'/external-policies.json',JSON.stringify({[upstreamOrigin]:{addresses:[upstreamIP],ca:cert.toString()}}));
 const upstream=https.createServer({key,cert},(r,s)=>{
  upstreamHeaders=r.headers;
  if(r.url==='/base/login'&&r.method==='POST'){
   let body='';r.on('data',b=>body+=b);r.on('end',()=>{upstreamBody=body;s.writeHead(303,{Location:upstreamOrigin+'/base/private','Set-Cookie':'app_session=target-login; Path=/base; HttpOnly'});s.end();});return;
  }
  if(r.url==='/base/logout'){s.end('Target application logout; DSH session remains separate');return;}
  if(r.url==='/base/private'){
   if(!(r.headers.cookie||'').includes('app_session=target-login')){s.writeHead(401);s.end('Target login required');return;}
   s.end('Actual target fixture content with source ref source-002');return;
  }
  s.end(JSON.stringify({path:r.url}));
 });
 upstream.on('upgrade',(r,socket)=>{
  upstreamHeaders=r.headers;
  const accept=crypto.createHash('sha1').update(r.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
  socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n');socket.on('data',b=>{const size=b[1]&127;if(!(b[1]&128)||size>125||b.length<size+6)return socket.destroy();const data=Buffer.from(b.subarray(6,6+size));for(let i=0;i<size;i++)data[i]^=b[2+i%4];socket.write(Buffer.concat([Buffer.from([0x81,size]),data]));});socket.on('error',()=>socket.destroy());
 });
 await new Promise(r=>upstream.listen(9443,'0.0.0.0',r));
 try{
  await start();let alice,bobby,csrf,heldSocket;
  await t.test('anonymous API is refused by actual DSH code',async()=>assert.equal((await req(canonical,'/api/app-links')).status,401));
  await t.test('actual DSH login produces a persisted session',async()=>{alice=await login('alice');bobby=await login('bobby');assert(fs.existsSync(ROOT+'/sessions.json'));});
  await t.test('registration retains default limit eight',async()=>{const r=await req(canonical,'/api/app-links',{cookie:alice});const v=JSON.parse(r.text);assert.equal(v.limit,8);csrf=v.csrfToken;});
  await t.test('application-manager login uses a fixed local landing path',async()=>{const body=new URLSearchParams({username:'alice',password:fixturePassword,internet:'off',application:'applications'}).toString();const r=await req(canonical,'/login',{method:'POST',body,headers:{'Content-Type':'application/x-www-form-urlencoded'}});assert.equal(r.status,302);assert.equal(r.headers.location,'/applications');});

  await t.test('optional Test-host allowlist refuses aliases without a Test ingress',async()=>{const file=ROOT+'/inventory.json',saved=fs.readFileSync(file);const inv=JSON.parse(saved);inv.allowedNames=['external'];fs.writeFileSync(file,JSON.stringify(inv));assert.equal(JSON.parse((await req(canonical,'/api/app-links?name=external',{cookie:alice})).text).available,true);assert.equal(JSON.parse((await req(canonical,'/api/app-links?name=unrouted',{cookie:alice})).text).available,false);fs.writeFileSync(file,saved);});

  await t.test('external target requires approved origin',async()=>assert.equal((await save(alice,csrf,{action:'save',name:'external',type:'external',targetUrl:'https://foreign.invalid/'})).status,400));
  await t.test('CSRF is checked before a mapping is saved',async()=>assert.equal((await save(alice,'wrong',{action:'save',name:'external',type:'external',targetUrl:upstreamOrigin+'/base/'})).status,403));
  await t.test('external mapping is persisted under the signed-in owner',async()=>{assert.equal((await save(alice,csrf,{action:'save',name:'external',type:'external',targetUrl:upstreamOrigin+'/base/'})).status,200);const v=JSON.parse(fs.readFileSync(ROOT+'/app-links.json'));assert.equal(v.external.owner,'alice');assert.equal(v.external.targets.off.url,upstreamOrigin+'/base/');assert.equal(v.external.ports.off,undefined);});
  await t.test('actual application list includes external URL and type',async()=>{const r=await req(canonical,'/api/app-links',{cookie:alice});const v=JSON.parse(r.text).links.find(x=>x.name==='external');assert.equal(v.type,'external');assert.equal(v.url,'https://'+alias+'/');assert.equal(v.targetUrl,upstreamOrigin+'/base/');});
  await t.test('anonymous alias redirects to canonical DSH sign-in',async()=>{const r=await req(alias,'/');assert.equal(r.status,303);assert.equal(r.headers.location,'https://'+canonical+'/login?app=external');});
  await t.test('another account cannot access or overwrite the alias',async()=>{assert.equal((await req(alias,'/private',{cookie:bobby})).status,404);const x=JSON.parse((await req(canonical,'/api/app-links',{cookie:bobby})).text);assert.equal((await save(bobby,x.csrfToken,{action:'save',name:'external',type:'external',targetUrl:upstreamOrigin+'/base/'})).status,409);});
  await t.test('target /login reaches target instead of DSH login handler',async()=>{const r=await req(alias,'/login',{method:'POST',cookie:alice,body:'user=fixture-target',headers:{Origin:'https://'+alias}});assert.equal(r.status,303);assert.equal(r.headers.location,'https://'+alias+'/private');assert.equal(upstreamBody,'user=fixture-target');assert.equal(upstreamHeaders.cookie,undefined);assert(!/domain=/i.test(r.headers['set-cookie'][0]));});
  await t.test('target authenticated content and sources are actually returned',async()=>{const r=await req(alias,'/private',{cookie:alice+'; app_session=target-login; dsh-auth-fixture=private',headers:{Authorization:'Bearer private'}});assert.equal(r.status,200);assert.match(r.text,/source-002/);assert.equal(upstreamHeaders.cookie,'app_session=target-login');assert.equal(upstreamHeaders.authorization,undefined);});
  await t.test('target logout does not intercept DSH sign-out',async()=>{const r=await req(alias,'/logout',{cookie:alice});assert.match(r.text,/Target application logout/);assert.equal((await req(canonical,'/api/auth/session',{cookie:alice})).status,200);});
  await t.test('local port mapping still saves and consumes the same quota',async()=>{assert.equal((await save(alice,csrf,{action:'save',name:'localapp',type:'port',port:'8110'})).status,200);const v=JSON.parse((await req(canonical,'/api/app-links',{cookie:alice})).text);assert.equal(v.used,2);assert.equal(v.links.find(x=>x.name==='localapp').port,8110);});
  await t.test('candidate restart retains sessions and external mappings',async()=>{await stop();await start();assert.equal((await req(alias,'/private',{cookie:alice+'; app_session=target-login'})).status,200);});
  await t.test('baseline rollback retains storage and local mappings',async()=>{await stop();await start(true);assert.equal((await req(canonical,'/api/auth/session',{cookie:alice})).status,200);assert.equal((await req(alias,'/private',{cookie:alice})).status,404);const v=JSON.parse(fs.readFileSync(ROOT+'/app-links.json'));assert.equal(v.localapp.ports.off,8110);assert.equal(v.external.targets.off.url,upstreamOrigin+'/base/');});
  await t.test('return to candidate restores external route with retained login',async()=>{await stop();await start();assert.equal((await req(alias,'/private',{cookie:alice+'; app_session=target-login'})).status,200);});
  await t.test('recovery disables app presentation while preserving external content and login',async()=>{await stop();await start(false,false);const page=await req(canonical,'/login');assert.equal(page.status,200);assert(page.text.includes('Jupyter'));const r=await req(alias,'/private',{cookie:alice+'; app_session=target-login'});assert.equal(r.status,200);assert(r.text.includes('source-002'));assert.equal((await req(alias,'/')).headers.location,'https://'+canonical+'/login');await stop();await start(false,true);const a=await req(canonical,'/login?app=external');assert.equal(a.status,200);assert(a.text.includes('Sign in to external'));assert(!a.text.includes('Jupyter'));assert.equal((await req(alias,'/private',{cookie:alice+'; app_session=target-login'})).status,200);});
  await t.test('actual DSH WebSocket denies anonymous and other account at origin guard',async()=>{assert.equal((await openSocket('')).status,401);assert.equal((await openSocket(bobby)).status,403);});
  await t.test('actual DSH WebSocket authenticates and forwards a masked client frame',async()=>{
   const result=await openSocket(alice+'; app_session=target-login; dsh-auth-fixture=private');assert.equal(result.status,101);heldSocket=result.socket;
   await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('No target WS frame')),3000);heldSocket.once('data',b=>{clearTimeout(timer);try{assert.deepEqual(b,Buffer.from([0x81,2,0x4f,0x4b]));assert.equal(upstreamHeaders.cookie,'app_session=target-login');resolve();}catch(e){reject(e);}});heldSocket.once('error',reject);heldSocket.write(Buffer.from([0x81,0x82,1,2,3,4,0x4f^1,0x4b^2]));});
  });
  await t.test('same alias does not cross the selected environment',async()=>{const v=JSON.parse(fs.readFileSync(ROOT+'/users.json'));v.alice.internetAllowed=true;fs.writeFileSync(ROOT+'/users.json',JSON.stringify(v));const online=await login('alice','on');assert.equal((await req(alias,'/private',{cookie:online})).status,404);});
  await t.test('Public option saves in actual settings and retains destination login',async()=>{const data=JSON.parse((await req(canonical,'/api/app-links',{cookie:alice})).text);const saved=await save(alice,data.csrfToken,{action:'save',name:'publicdemo',type:'external',targetUrl:upstreamOrigin+'/base/',accessMode:'public'});assert.equal(saved.status,200,saved.text);const map=JSON.parse(fs.readFileSync(ROOT+'/app-links.json')).publicdemo;assert.equal(map.accessMode,'public');assert.equal(map.publicEnvironment,'off');const r=await req('publicdemo.'+domain,'/private');assert.equal(r.status,401);assert.equal(r.text,'Target login required');});
  await t.test('Public alias forwards no DSH credentials or authorization',async()=>{const r=await req('publicdemo.'+domain,'/content',{cookie:alice,headers:{Authorization:'Bearer synthetic-only'}});assert.equal(r.status,200);assert.equal(upstreamHeaders.authorization,undefined);assert(!(upstreamHeaders.cookie||'').includes('fixture_dsh'));});
  await t.test('Public alias returns application content rather than DSH management',async()=>{const r=await req('publicdemo.'+domain,'/api/admin/users');assert.equal(r.status,200);assert.equal(JSON.parse(r.text).path,'/base/api/admin/users');assert.equal((await req(canonical,'/api/admin/users')).status,401);});
  await t.test('canonical DSH logout revokes alias access and active WebSocket',async()=>{const closed=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Logout did not close WebSocket')),3000);heldSocket.once('close',()=>{clearTimeout(timer);resolve();});});assert.equal((await req(canonical,'/logout',{cookie:alice})).status,302);await closed;assert.equal((await req(alias,'/private',{cookie:alice+'; app_session=target-login'})).status,303);});
 }finally{await stop();upstream.closeAllConnections();upstream.close();fs.writeFileSync(__dirname+'/GATEWAY_FIXTURE_RUNTIME.log',log);}
});
