'use strict';
// Default: synthetic directory. An operator may explicitly supply a private
// credential-file reference to repeat the same gateway checks against real AD.
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http'),cp=require('node:child_process');
const runtime=process.env.DSH_LDAP_TEST_SCRIPTS||path.join(__dirname,'../scripts');
const realFile=process.env.DSH_LDAP_TEST_CREDENTIAL_FILE;
const credential=realFile?JSON.parse(fs.readFileSync(realFile,'utf8')):{username:'person',password:'AD-fixture-only',domain:'example.com'};
const issuer='dsh.example.test',localPassword='local-fixture-only',adminPassword='admin-fixture-only';
function request(port,route,{fields,cookie,csrf}={}) {
  return new Promise((resolve,reject)=>{
    const body=fields?new URLSearchParams(fields).toString():'';
    const req=http.request({host:'127.0.0.1',port,path:route,method:fields?'POST':'GET',headers:{Host:issuer,
      ...(fields?{Origin:'https://'+issuer,'Content-Type':'application/x-www-form-urlencoded','Content-Length':Buffer.byteLength(body)}:{}),
      ...(cookie?{Cookie:cookie}:{}),...(csrf?{'X-DSH-Admin-CSRF':csrf}:{})}},res=>{
      let text='';res.on('data',x=>text+=x);res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:text}));
    });req.setTimeout(30000,()=>req.destroy(Error('Bounded gateway test timeout')));req.on('error',reject);req.end(body);
  });
}
const cookieFor=(result,name='dsh_auth')=>(result.headers['set-cookie']||[]).find(x=>x.startsWith(name+'='))?.split(';')[0];
test('actual gateway enforces directory identity, conflict, approval and restart rules',{timeout:180000},async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-ldap-http-'));
  const {hashPassword}=require(path.join(runtime,'password_store'));
  const user=credential.username,usersFile=path.join(root,'users.json'),settingsFile=path.join(root,'settings.json');
  const users={admin:hashPassword(adminPassword),[user]:hashPassword(localPassword)};
  fs.writeFileSync(usersFile,JSON.stringify(users));
  let child,logs='',backend;const sockets=new Set();
  t.after(async()=>{if(child&&!child.killed){child.kill();await new Promise(r=>child.once('exit',r));}for(const s of sockets)s.destroy();if(backend)await new Promise(r=>backend.close(r));fs.rmSync(root,{recursive:true,force:true});});
  backend=http.createServer((_req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({fixture:'private-runtime'}));});
  backend.on('connection',s=>{sockets.add(s);s.once('close',()=>sockets.delete(s));});
  await new Promise(r=>backend.listen(0,'127.0.0.1',r));
  const probe=http.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
  const dest={host:'127.0.0.1',port:backend.address().port,tokenFile:'/runtime-tokens/synthetic-only'};
  fs.writeFileSync(root+'/routes.json',JSON.stringify({admin:{secure:dest,internet:dest},[user]:{secure:dest,internet:dest}}));
  fs.writeFileSync(root+'/app-links.json',JSON.stringify({'private-ldap-app':{owner:user,ports:{off:3000},accessMode:'authenticated'}}));
  const preload=root+'/directory-fixture.cjs';
  fs.writeFileSync(preload,`const key=require.resolve(${JSON.stringify(path.join(runtime,'ldap_auth'))});const actual=require(key);require.cache[key].exports={...actual,Directory:class{constructor(){this.config={allowSignUp:true};}async authenticate(name,password){if(password!==${JSON.stringify(credential.password)})throw new actual.DirectoryError('INVALID_CREDENTIALS',401,'Denied');return {username:actual.normalizeUsername(name,${JSON.stringify(credential.domain)}),subject:'ab'.repeat(16)};}}};`);
  async function start() {
    const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('DSH_')&&!key.startsWith('AUTH_')&&key!=='WORKSPACE_ROOT'));
    Object.assign(env,{PORT:String(port),DSH_TRUSTED_HOST:issuer,WORKSPACE_ROOT:root+'/users',DSH_USER_STORE_PATH:usersFile,
      DSH_USER_SETTINGS_PATH:settingsFile,DSH_USER_TARGETS_FILE:root+'/routes.json',DSH_AUDIT_DIR:root+'/audit',
      DSH_ADMIN_USERS:'admin',DSH_APP_DOMAIN:'apps.example.test',DSH_APP_LOGIN_ENABLED:'true',
      DSH_LDAP_CONFIG_FILE:realFile?credential.configFile:root+'/synthetic-config.json'});
    child=cp.spawn(process.execPath,[...(!realFile?['--require',preload]:[]),path.join(runtime,'auth_proxy.js')],{env,stdio:['ignore','pipe','pipe']});
    child.stdout.on('data',x=>logs+=x);child.stderr.on('data',x=>logs+=x);
    for(let i=0;i<150;i++){if(child.exitCode!==null)throw Error('Gateway fixture exited before ready');try{const r=await request(port,'/login');if(r.status===200)return;}catch{}await new Promise(r=>setTimeout(r,50));}
    throw Error('Gateway did not start');
  }
  async function stop(){const c=child;child=null;if(c&&c.exitCode===null){c.kill();await new Promise(r=>c.once('exit',r));}}
  const login=(provider,password=credential.password,internet='off',name=user)=>request(port,'/login',{fields:{username:name,password,auth_provider:provider,internet}});
  await start();
  await t.test('AD and local choices are visible without changing local behavior',async()=>{
    const page=await request(port,'/login');assert.match(page.body,/name="auth_provider"/);assert.match(page.body,/AD \/ LDAP/);
    const local=await login('local',localPassword);assert.equal(local.status,302);assert.ok(cookieFor(local));
  });
  await t.test('valid AD credential with an existing local username returns explicit 409 and changes nothing',async()=>{
    const before=fs.readFileSync(usersFile),r=await login('ldap');assert.equal(r.status,409);assert.equal(r.headers['x-dsh-auth-error'],'LDAP_LOCAL_ACCOUNT_CONFLICT');
    assert.match(r.body,/administrator to delete the locally created account/);assert.equal(cookieFor(r),undefined);assert.deepEqual(fs.readFileSync(usersFile),before);
  });
  await t.test('app-focused login offers both providers and retains its collision error',async()=>{
    const page=await request(port,'/login?app=private-ldap-app');assert.equal(page.status,200);assert.match(page.body,/name="auth_provider"/);
    const token=page.body.match(/name="app_login" value="([a-f0-9]+)"/)[1];const cookie=cookieFor(page,'__Host-dsh_app_login');
    const r=await request(port,'/login',{fields:{app_login:token,username:user,password:credential.password,auth_provider:'ldap'},cookie});
    assert.equal(r.status,409);assert.match(r.body,/administrator to delete/);assert.match(r.body,/Sign in to private-ldap-app/);
  });
  // Remove only the locally generated fixture record, never a live user account.
  await stop();const existing=JSON.parse(fs.readFileSync(usersFile));delete existing[user];fs.writeFileSync(usersFile,JSON.stringify(existing));await start();
  let adCookie;
  await t.test('first AD sign-in creates a private No Internet identity without saving its password',async()=>{
    const r=await login('ldap');assert.equal(r.status,302);adCookie=cookieFor(r);assert.ok(adCookie);
    const stored=JSON.parse(fs.readFileSync(usersFile));assert.equal(stored[user].authProvider,'ldap');assert.equal(stored[user].internetAllowed,false);assert.match(stored[user].ldapSubject,/^[a-f0-9]{32}$/);
    assert.ok(!fs.readFileSync(usersFile,'utf8').includes(credential.password));
    const session=await request(port,'/api/auth/session',{cookie:adCookie});assert.equal(session.status,200);assert.equal(JSON.parse(session.body).user,user);assert.equal(JSON.parse(session.body).internet,'off');
  });
  await t.test('AD user cannot choose Internet until an administrator grants access',async()=>{
    assert.equal((await login('ldap',credential.password,'on')).status,403);
    const admin=await login('local',adminPassword,'off','admin'),cookie=cookieFor(admin);assert.equal(admin.status,302);
    const inventory=await request(port,'/api/admin/users',{cookie}),data=JSON.parse(inventory.body);assert.equal(inventory.status,200);assert.equal(data.users.find(x=>x.user===user).authProvider,'AD / LDAP');
    const approved=await request(port,'/api/admin/users',{cookie,csrf:data.csrfToken,fields:{action:'allow-internet',user}});assert.equal(approved.status,200);
    const r=await login('ldap',credential.password,'on');assert.equal(r.status,302);const session=await request(port,'/api/auth/session',{cookie:cookieFor(r)});assert.equal(JSON.parse(session.body).internet,'on');
  });
  await t.test('directory password changes use the corporate flow and the local placeholder cannot sign in',async()=>{
    assert.equal((await login('local',credential.password)).status,401);
    const r=await request(port,'/change-password',{fields:{username:user,old_password:'unused-fixture',new_password:'replacement-fixture-only',confirm_password:'replacement-fixture-only'}});
    assert.equal(r.status,403);assert.match(r.body,/corporate directory/);
  });
  await t.test('account identity, local records and an existing AD session survive gateway replacement',async()=>{
    const before=fs.readFileSync(usersFile),adminBefore=JSON.parse(before).admin;fs.writeFileSync(root+'/workspace-marker','preserved');
    await stop();await start();assert.deepEqual(fs.readFileSync(usersFile),before);assert.deepEqual(JSON.parse(fs.readFileSync(usersFile)).admin,adminBefore);assert.equal(fs.readFileSync(root+'/workspace-marker','utf8'),'preserved');
    const r=await request(port,'/api/auth/session',{cookie:adCookie});assert.equal(r.status,200);assert.equal(JSON.parse(r.body).user,user);
    assert.ok(!logs.includes(credential.password),'Directory password must not appear in logs');
  });
});
