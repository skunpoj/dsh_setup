'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http'),cp=require('node:child_process');
const {AppSignIn}=require('../../scripts/app_signin');
const issuer='https://dsh.aiportal.example.internal',domain='aiportal.example.internal';
function fixture(){let now=0;const maps={demo:{owner:'alice',ports:{off:8501},accessMode:'authenticated'}};const auth=new AppSignIn({domain,issuer,mappings:()=>maps,now:()=>now,limit:2});return{auth,maps,advance:()=>now=300001};}
function form(auth){const headers={};const html=auth.begin('demo',{setHeader:(n,v)=>headers[n]=v});return{html,token:html.match(/name="app_login" value="([a-f0-9]+)"/)[1],cookie:headers['Set-Cookie'].split(';')[0]};}
function submit(auth,f,extra={}){return auth.consume({headers:{origin:issuer,host:new URL(issuer).host,cookie:f.cookie,...extra}},new URLSearchParams({app_login:f.token,username:'alice',password:'synthetic-only'}));}

test('issuer canonicalization supports an AD UPN for a shared app without granting owner access',()=>{
 const {normalizeUsername}=require('../../scripts/ldap_auth');
 const {auth,maps}=fixture();
 maps.demo={owner:'alice',ports:{},targets:{off:{type:'external',origin:'https://upstream.example.test'}},visitorPolicy:'signed-in-users',sharedEnvironment:'off',accessMode:'authenticated'};
 const f=form(auth),headers={origin:issuer,host:new URL(issuer).host,cookie:f.cookie};
 const params=new URLSearchParams({app_login:f.token,username:'bobby@example.com',password:'synthetic-only'});
 const app=auth.consume({headers},params,value=>normalizeUsername(value,'example.com'));
 assert.equal(app.visitorPolicy,'signed-in-users');assert.equal(app.sessionInternet,'off');assert.equal(app.owner,'alice');
 assert.equal(app.destination,'https://demo.aiportal.example.internal/');
});
test('app form has no workspace/environment/platform actions and returns registered alias',()=>{const {auth}=fixture(),f=form(auth);for(const term of ['Web Terminal','Jupyter','type="radio"','/register','/change-password'])assert(!f.html.includes(term));assert.equal(submit(auth,f).destination,'https://demo.aiportal.example.internal/');});
test('one use and same browser required',()=>{const {auth}=fixture(),f=form(auth);submit(auth,f);assert.throws(()=>submit(auth,f));const g=form(auth);assert.throws(()=>submit(auth,g,{cookie:'__Host-dsh_app_login='+'f'.repeat(64)}));});
test('reject foreign, null or absent Origin and foreign Host',()=>{for(const headers of [{origin:'https://evil.example'},{host:'evil.example'},{origin:'null'},{origin:undefined}]){const {auth}=fixture();assert.throws(()=>submit(auth,form(auth),headers));}});
test('reject expired and removed mappings',()=>{const f=fixture(),a=form(f.auth);f.advance();assert.throws(()=>submit(f.auth,a));const g=fixture(),b=form(g.auth);delete g.maps.demo;assert.throws(()=>submit(g.auth,b));});
test('reject changed owner, target, enabled state and Public mode',()=>{for(const mutate of [x=>x.owner='bobby',x=>x.ports.off=8502,x=>x.enabled=false,x=>x.accessMode='public']){const f=fixture(),a=form(f.auth);mutate(f.maps.demo);assert.throws(()=>submit(f.auth,a));}});
test('reject wrong user and duplicate fields',()=>{for(const fields of [{username:'bobby'},null]){const {auth}=fixture(),f=form(auth),p=new URLSearchParams({app_login:f.token,username:'alice',password:'synthetic'});if(fields)p.set('username',fields.username);else p.append('app_login',f.token);assert.throws(()=>auth.consume({headers:{origin:issuer,host:new URL(issuer).host,cookie:f.cookie}},p));}});
test('no open return URL, unknown mode or prototype application',()=>{const {auth}=fixture();for(const name of ['https://evil.example','//evil.example','__proto__','missing'])assert.throws(()=>auth.begin(name,{setHeader(){}}));assert.throws(()=>auth.begin('demo',{setHeader(){}},'','on'));});
test('bounded pending forms; capacity returns after expiry',()=>{const f=fixture();form(f.auth);form(f.auth);assert.throws(()=>form(f.auth));f.advance();assert(form(f.auth));});
test('Public mappings never create DSH password form',()=>{const f=fixture();f.maps.demo.accessMode='public';assert.throws(()=>form(f.auth));});

test('selected recipients bind one-use login and reject changed or malformed lists',()=>{
 for(const allowedUsers of [undefined,[],['bobby','bobby'],['Bobby'],['bobby',null],Array(129).fill('bobby')]){
  const {auth,maps}=fixture();Object.assign(maps.demo,{visitorPolicy:'selected-users',sharedEnvironment:'off',allowedUsers});assert.throws(()=>form(auth));
 }
 const {auth,maps}=fixture();Object.assign(maps.demo,{visitorPolicy:'selected-users',sharedEnvironment:'off',allowedUsers:['bobby']});
 const f=form(auth);assert(!f.html.includes('bobby'));maps.demo.allowedUsers=['charlie'];assert.throws(()=>submit(auth,f));
 const g=form(auth);const current=submit(auth,g);maps.demo.allowedUsers=['bobby'];assert.throws(()=>auth.assertCurrent(current));
});
test('Internet-only app chooses registered mode without presenting platform choices',()=>{const f=fixture();f.maps.demo.ports={on:8501};const a=form(f.auth);assert.equal(submit(f.auth,a).internet,'on');});

function request(port,route,{method='GET',cookie='',fields,origin=issuer}={}){return new Promise((resolve,reject)=>{const body=fields?new URLSearchParams(fields).toString():'';const r=http.request({host:'127.0.0.1',port,path:route,method,headers:{Host:new URL(issuer).host,Origin:origin,...(cookie?{Cookie:cookie}:{}),...(fields?{'Content-Type':'application/x-www-form-urlencoded','Content-Length':Buffer.byteLength(body)}:{})}},s=>{let body='';s.on('data',b=>body+=b);s.on('end',()=>resolve({status:s.statusCode,headers:s.headers,body}));});r.setTimeout(5000,()=>r.destroy(Error('timeout')));r.on('error',reject);r.end(body);});}
test('actual latest normal gateway integrates app form, normal auth and safe return',{timeout:30000},async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-app-entry-')),runtime=path.resolve(__dirname,'../../scripts');const {hashPassword}=require(runtime+'/password_store');
 const dummy={host:'127.0.0.1',port:39999,tokenFile:'/runtime-tokens/fixture-only'};
 fs.writeFileSync(root+'/users.json',JSON.stringify({alice:hashPassword('synthetic-fixture-only')}));fs.writeFileSync(root+'/routes.json',JSON.stringify({alice:{secure:dummy,internet:dummy}}));fs.writeFileSync(root+'/app-links.json',JSON.stringify({demo:{owner:'alice',ports:{off:8501},accessMode:'authenticated'}}));
 const probe=http.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const env={PATH:process.env.PATH,SystemRoot:process.env.SystemRoot,HOME:root,PORT:String(port),DSH_LISTEN_HOST:'127.0.0.1',WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:root+'/users.json',DSH_USER_SETTINGS_PATH:root+'/settings.json',DSH_USER_TARGETS_FILE:root+'/routes.json',DSH_SESSION_STORE_PATH:root+'/sessions.json',DSH_AUDIT_DIR:root+'/audit',DSH_APP_LINKS_PATH:root+'/app-links.json',DSH_APP_DOMAIN:domain,DSH_TRUSTED_HOST:new URL(issuer).host,DSH_ALLOW_REGISTRATION:'false',DSH_COOKIE_NAME:'dsh_auth',DSH_COOKIE_SECURE:'true',DSH_APP_LOGIN_ENABLED:'true'};
 const child=cp.spawn(process.execPath,[runtime+'/auth_proxy.js'],{env,stdio:['ignore','pipe','pipe']});let log='';child.stdout.on('data',b=>log+=b);child.stderr.on('data',b=>log+=b);
 try{
  let ready=false;for(let i=0;i<100;i++){if(child.exitCode!==null)throw Error(log);try{await request(port,'/login');ready=true;break;}catch{await new Promise(r=>setTimeout(r,40));}}assert(ready,log);
  let a;
  await t.test('standard platform login still exposes existing platform options',async()=>{a=await request(port,'/login');assert.equal(a.status,200);assert(a.body.includes('Jupyter'));});
  const getForm=async()=>{const r=await request(port,'/login?app=demo');assert.equal(r.status,200,r.body);assert.equal(r.headers['referrer-policy'],'same-origin');assert(!r.body.includes('Jupyter'));return{token:r.body.match(/name="app_login" value="([a-f0-9]+)"/)[1],cookie:r.headers['set-cookie'][0].split(';')[0]};};
  await t.test('null browser Origin remains rejected by the real handler',async()=>{const f=await getForm(),r=await request(port,'/login',{method:'POST',origin:'null',cookie:f.cookie,fields:{app_login:f.token,username:'alice',password:'synthetic-fixture-only'}});assert.equal(r.status,403);assert(!r.headers['set-cookie']);});
  await t.test('incorrect password stays in app presentation',async()=>{const f=await getForm(),r=await request(port,'/login',{method:'POST',cookie:f.cookie,fields:{app_login:f.token,username:'alice',password:'wrong'}});assert.equal(r.status,401);assert(r.body.includes('Sign in to demo'));assert(!r.body.includes('Jupyter'));});
  await t.test('normal credential creates actual issuer session and returns to app',async()=>{const f=await getForm(),r=await request(port,'/login',{method:'POST',cookie:f.cookie,fields:{app_login:f.token,username:'alice',password:'synthetic-fixture-only',internet:'on',application:'terminal',returnTo:'https://evil.example'}});assert.equal(r.status,303,r.body);assert.equal(r.headers.location,'https://demo.aiportal.example.internal/');const cookie=r.headers['set-cookie'].find(x=>x.startsWith('dsh_auth='));assert(cookie.includes('HttpOnly'));assert(cookie.includes('Secure'));const session=await request(port,'/api/auth/session',{cookie:cookie.split(';')[0]});assert.equal(session.status,200);assert.equal(JSON.parse(session.body).user,'alice');assert.equal(JSON.parse(session.body).internet,'off');});
  await t.test('malformed context and arbitrary target do not redirect',async()=>{assert.equal((await request(port,'/login?app=https://evil.example')).status,404);assert.equal((await request(port,'/login',{method:'POST',fields:{app_login:'forged',username:'alice',password:'synthetic-fixture-only'}})).status,403);});
 }finally{if(child.exitCode===null&&child.signalCode===null){const done=new Promise(r=>child.once('exit',r));child.kill();await done;}/* Preserve synthetic fixture and log for review; no user data. */fs.writeFileSync(root+'/qualification.log',log);}
});
