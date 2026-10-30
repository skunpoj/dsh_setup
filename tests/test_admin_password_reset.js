// Real HTTP gateway acceptance for the administrator "Reset password" action. Disposable identities only.
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http');
const {spawn}=require('child_process');
const {hashPassword}=require('../scripts/password_store');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-reset-password-'));
const port=39640,backendPort=39641;
const request=(method,route,body='',cookie='',headers={})=>new Promise((resolve,reject)=>{
 const r=http.request({host:'127.0.0.1',port,path:route,method,headers:{cookie,'Content-Type':'application/x-www-form-urlencoded',...headers}},res=>{let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,headers:res.headers,cookie:(res.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));});r.on('error',reject);r.end(body);
});
const signIn=(user,password)=>request('POST','/login',new URLSearchParams({username:user,password,internet:'off',auth_provider:'local'}).toString());
const login=async(user,password)=>(await signIn(user,password)).cookie;
const changePassword=(user,oldPassword,newPassword)=>request('POST','/change-password',new URLSearchParams({username:user,old_password:oldPassword,new_password:newPassword}).toString());
const CREATE_RULE='Use a password of at least 12 characters without surrounding spaces.';
let gateway,backend;
async function start(){gateway=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_USER_TARGETS_FILE:path.join(root,'targets.json'),DSH_ADMIN_SUMMARY_FILE:path.join(root,'summary.json'),DSH_AUDIT_DIR:path.join(root,'audit'),DSH_COOKIE_SECURE:'false',DSH_TRUSTED_HOST:'127.0.0.1:'+port},stdio:'ignore'});for(let i=0;i<80;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,50));}}throw Error('Gateway did not start');}
async function stop(){const child=gateway;gateway=null;await new Promise(r=>{child.once('exit',r);child.kill();});}
(async()=>{try{
 const RESET='reset-synthetic-password',NEXT='chosen-synthetic-password';
 const aliceExtra={internetAllowed:true,createdAt:'2026-10-20T07:14:49.317Z',credentialSubject:'u-'+'a'.repeat(32)};
 fs.writeFileSync(path.join(root,'users.json'),JSON.stringify({admin:hashPassword('synthetic-admin'),
   alice:{...hashPassword('synthetic-alice-old'),...aliceExtra},
   directory:{...hashPassword('unused-directory-secret'),authProvider:'ldap',ldapSubject:'synthetic-subject',internetAllowed:false}}));
 const target={host:'127.0.0.1',port:backendPort,tokenFile:'/runtime-tokens/synthetic'};
 fs.writeFileSync(path.join(root,'targets.json'),JSON.stringify(Object.fromEntries(['admin','alice','directory'].map(u=>[u,{secure:target,internet:target}]))));
 fs.writeFileSync(path.join(root,'summary.json'),JSON.stringify({observedAt:new Date().toISOString(),environments:[],model:{},performance:[],gaps:[]}));
 backend=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<html><body>Isolated test backend</body></html>');});
 await new Promise(r=>backend.listen(backendPort,'127.0.0.1',r));await start();
 const admin=await login('admin','synthetic-admin');let alice=await login('alice','synthetic-alice-old');assert(admin&&alice);
 const info=JSON.parse((await request('GET','/api/admin/users','',admin)).text);
 const responses=[];
 const reset=async(user,password,extra={},cookie=admin)=>{const r=await request('POST','/api/admin/users',new URLSearchParams({action:'reset-password',user,password}).toString(),cookie,{'X-DSH-Admin-CSRF':info.csrfToken,...extra});responses.push(r.text);return r;};

 // Same guards as every account action: CSRF token, same origin, administrator session.
 assert.equal((await reset('alice',RESET,{'X-DSH-Admin-CSRF':'wrong-token'})).status,403,'Bad CSRF token');
 assert.equal((await reset('alice',RESET,{Origin:'https://evil.example'})).status,403,'Cross-origin denied');
 assert.equal((await reset('alice',RESET,{},alice)).status,403,'Non-administrator denied');
 // Scope and the create-account password rule (shared function, identical message).
 assert.equal((await reset('directory',RESET)).status,409,'AD accounts keep the directory password');
 assert.equal((await reset('admin',RESET)).status,409,'Administrator accounts are operator-managed');
 assert.equal((await reset('nobody',RESET)).status,404);
 for(const bad of ['short',' '+RESET,RESET+' ']){const r=await reset('alice',bad);assert.equal(r.status,400);assert.equal(JSON.parse(r.text).error,CREATE_RULE,'Same message as account creation');}
 assert.equal(JSON.parse((await request('POST','/api/admin/users',new URLSearchParams({action:'create',user:'bob',password:'short'}).toString(),admin,{'X-DSH-Admin-CSRF':info.csrfToken})).text).error,CREATE_RULE);
 const before=JSON.parse(fs.readFileSync(path.join(root,'users.json'))).alice;
 assert(!('mustChangePassword' in before),'Refused requests change nothing');

 // Reset: sessions revoked, old password invalid, only scheme/salt/hash (+ change flag) differ.
 assert.equal((await request('GET','/api/auth/session','',alice)).status,200);
 assert.equal((await reset('alice',RESET)).status,200);
 assert.equal((await request('GET','/api/auth/session','',alice)).status,401,'Existing sessions are revoked');
 const after=JSON.parse(fs.readFileSync(path.join(root,'users.json'))).alice;
 for(const [k,v] of Object.entries(aliceExtra))assert.deepEqual(after[k],v,'Unchanged field '+k);
 assert.deepEqual(Object.keys(after).sort(),[...Object.keys(before),'mustChangePassword'].sort());
 assert.notEqual(after.hash,before.hash);assert.notEqual(after.salt,before.salt);assert.equal(after.scheme,'scrypt-v1');
 assert.equal((await signIn('alice','synthetic-alice-old')).cookie,'','The old password no longer works');
 // The reset password verifies, but only unlocks the change step.
 const gated=await signIn('alice',RESET);
 assert.equal(gated.status,403);assert.equal(gated.cookie,'');assert.equal(gated.headers['x-dsh-auth-error'],'PASSWORD_CHANGE_REQUIRED');
 assert.equal(JSON.parse((await request('GET','/api/admin/users','',admin)).text).users.find(u=>u.user==='alice').passwordChangeRequired,true);
 assert.equal((await changePassword('alice',RESET,RESET)).status,400,'Reusing the reset password is refused');
 assert.equal((await changePassword('alice',RESET,NEXT)).status,200);
 alice=await login('alice',NEXT);assert(alice);assert.equal((await request('GET','/api/auth/session','',alice)).status,200);
 const final=JSON.parse(fs.readFileSync(path.join(root,'users.json'))).alice;
 assert(!('mustChangePassword' in final));for(const [k,v] of Object.entries(aliceExtra))assert.deepEqual(final[k],v);

 // Never echoed, logged or audited.
 const audit=fs.readFileSync(path.join(root,'audit','events.jsonl'),'utf8'),store=fs.readFileSync(path.join(root,'users.json'),'utf8');
 for(const secret of [RESET,NEXT]){assert(!audit.includes(secret));assert(!store.includes(secret));assert(!responses.some(t=>t.includes(secret)),'Response echoed a password');}
 const events=audit.trim().split('\n').map(JSON.parse);
 const resetEvent=events.find(e=>e.event==='account.reset-password');
 assert.deepEqual(Object.keys(resetEvent).sort(),['environment','event','subject','time','user']);assert.equal(resetEvent.user,'admin');assert.equal(resetEvent.subject,'alice');
 assert(events.some(e=>e.event==='account.password-changed'&&e.user==='alice'));
 const auditView=JSON.parse((await request('GET','/api/admin/audit','',admin)).text).events;
 assert(auditView.some(e=>e.event==='account.reset-password'),'Administrator audit view lists resets');

 // Admin page: the button exists only on local, non-administrator rows; the inline form clears itself.
 const {chromium}=require(process.env.DSH_PLAYWRIGHT||'playwright');
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}:{})});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addCookies([{name:'dsh_auth',value:admin.split('=')[1],url:'http://127.0.0.1:'+port}]);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+port+'/admin');await page.waitForFunction(()=>document.querySelectorAll('#users tr').length===3);
  const row=name=>page.locator('#users tr').filter({has:page.locator('td').filter({hasText:new RegExp('^'+name+'$')})});
  assert.equal(await row('alice').getByRole('button',{name:'Reset password'}).count(),1,'Local account has the button');
  assert.equal(await row('directory').getByRole('button',{name:'Reset password'}).count(),0,'AD account has no button');
  assert.equal(await row('admin').getByRole('button',{name:'Reset password'}).count(),0,'Administrator has no button');
  assert.equal(await page.locator('#resetPassword').isHidden(),true);
  await row('alice').getByRole('button',{name:'Reset password'}).click();
  assert.equal(await page.locator('#resetUser').textContent(),'alice');
  for(const id of ['#resetPasswordValue','#resetPasswordConfirm'])assert.equal(await page.locator(id).getAttribute('type'),'password');
  await page.fill('#resetPasswordValue','mismatch-synthetic-one');await page.fill('#resetPasswordConfirm','mismatch-synthetic-two');
  await page.getByRole('button',{name:'Reset password',exact:true}).last().click();
  await page.waitForFunction(()=>document.getElementById('userMessage').textContent.includes('do not match'));
  assert.equal(await page.locator('#resetPasswordValue').inputValue(),'');assert.equal(await page.locator('#resetPasswordConfirm').inputValue(),'');
  assert.equal(JSON.parse(fs.readFileSync(path.join(root,'users.json'))).alice.hash,final.hash,'A mismatch changes nothing');
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
 console.log(JSON.stringify({passed:true,checks:['CSRF, origin and admin session required','AD and admin 409, unknown 404','create rule and message reused','sessions revoked','old password invalidated','other fields unchanged','change required before a session','flag cleared after change','never echoed, stored in clear or audited','audit records actor, mode and subject only','button only on local non-admin rows','inline password fields cleared','mismatch changes nothing']}));
}finally{if(gateway)await stop();if(backend){backend.closeAllConnections();await new Promise(r=>backend.close(r));}fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
