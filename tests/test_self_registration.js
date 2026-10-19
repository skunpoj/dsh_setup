'use strict';
const assert=require('assert'),fs=require('fs'),http=require('http'),os=require('os'),path=require('path');
const {spawn}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-signup-')),port=19486;
const store=path.join(root,'users.json');fs.writeFileSync(store,JSON.stringify({admin:'synthetic-admin-only'}));
const target=(ip,tag)=>({host:ip,port:3081,tokenFile:'/runtime-tokens/signup-tests/'+tag});
const staticRoutes={admin:{secure:target('127.0.0.10','admin-off'),internet:target('127.0.0.20','admin-on')}};
const pool={slots:{'slot-one':{secure:target('127.0.0.11','one-off'),internet:target('127.0.0.21','one-on')},'slot-two':{secure:target('127.0.0.12','two-off'),internet:target('127.0.0.22','two-on')}}};
fs.writeFileSync(path.join(root,'routes.json'),JSON.stringify(staticRoutes));fs.writeFileSync(path.join(root,'pool.json'),JSON.stringify(pool));
const backend=http.createServer((req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({runtime:req.socket.localAddress,user:req.headers['x-dsh-user'],environment:req.headers['x-dsh-internet-access']}));});
let child;
const request=(method,route,fields={},cookie='',headers={})=>new Promise((resolve,reject)=>{
 const body=new URLSearchParams(fields).toString(),r=http.request({host:'127.0.0.1',port,method,path:route,headers:{host:'dsh.example.test',cookie,'Content-Type':'application/x-www-form-urlencoded',...headers}},res=>{let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,cookie:(res.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));});r.setTimeout(10000,()=>r.destroy(Error('request timeout')));r.on('error',reject);r.end(method==='GET'?'':body);
});
async function start(){child=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...Object.fromEntries(Object.entries(process.env).filter(([k])=>!/^(DSH_|AUTH_|WORKSPACE_ROOT$)/.test(k))),PORT:String(port),WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:store,DSH_USER_TARGETS_FILE:path.join(root,'routes.json'),DSH_SIGNUP_POOL_FILE:path.join(root,'pool.json'),DSH_ALLOW_REGISTRATION:'true',DSH_TRUSTED_HOST:'dsh.example.test'},stdio:'ignore'});for(let i=0;i<60;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,60));}}throw Error('gateway did not start');}
async function stop(){if(child&&child.exitCode===null){child.kill();await new Promise(r=>child.once('exit',r));}}
const password='long-synthetic-password',signup=user=>request('POST','/register',{username:user,password,confirm_password:password,internet:'on',role:'admin',runtimeSlot:'slot-one'});
const login=(user,internet='off',pass=password)=>request('POST','/login',{username:user,password:pass,internet});
(async()=>{try{await new Promise(r=>backend.listen(3081,'0.0.0.0',r));await start();
 const page=await request('GET','/login');assert(page.text.includes('id="tab-register"'));assert(page.text.includes('minlength="12"'));
 assert.equal((await request('POST','/register',{username:'evil',password,confirm_password:password},'',{Origin:'https://evil.example'})).status,403);
 for(const user of ['admin','__proto__','constructor'])assert.equal((await signup(user)).status,409);
 assert.equal((await request('POST','/register',{username:'alice',password:'short',confirm_password:'short'})).status,400);
 const concurrent=await Promise.all(['alice','bob','overflow'].map(signup));assert.equal(concurrent.filter(r=>r.status===200).length,2);assert.equal(concurrent.filter(r=>r.status===503).length,1);
 const users=JSON.parse(fs.readFileSync(store));const names=Object.keys(users).filter(u=>u!=='admin');assert.equal(names.length,2);assert.notEqual(users[names[0]].runtimeSlot,users[names[1]].runtimeSlot);
 for(const user of names){assert.equal(users[user].internetAllowed,false);assert.equal(users[user].scheme,'scrypt-v1');assert(!fs.readFileSync(store,'utf8').includes(password));assert.equal((await login(user,'on')).status,403);}
 const a=await login(names[0]),b=await login(names[1]);assert.equal(a.status,302);assert.equal(b.status,302);
 const ra=JSON.parse((await request('GET','/',{},a.cookie,{'X-DSH-User':names[1],'X-DSH-Internet-Access':'on'})).text),rb=JSON.parse((await request('GET','/',{},b.cookie)).text);assert.notEqual(ra.runtime,rb.runtime);assert.equal(ra.user,names[0]);assert.equal(ra.environment,'off');assert.equal((await request('GET','/api/admin/users',{},a.cookie)).status,403);
 const admin=await login('admin','off','synthetic-admin-only');assert.equal(admin.status,302);const info=JSON.parse((await request('GET','/api/admin/users',{},admin.cookie)).text);assert.equal(info.signupWorkspacesAvailable,0);assert(info.users.find(u=>u.user===names[0]).environments.includes('secure'));
 const action=(action,user)=>request('POST','/api/admin/users',{action,user},admin.cookie,{'X-DSH-Admin-CSRF':info.csrfToken});
 assert.equal((await action('allow-internet',names[0])).status,200);const online=await login(names[0],'on');assert.equal(online.status,302);const ro=JSON.parse((await request('GET','/',{},online.cookie)).text);assert.notEqual(ro.runtime,ra.runtime);assert.equal(ro.environment,'on');
 assert.equal((await action('deny-internet',names[0])).status,200);assert.equal((await login(names[0],'on')).status,403);assert((await request('GET','/',{},online.cookie)).text.includes('pane-login'));
 assert.equal((await request('POST','/change-password',{username:names[0],old_password:password,new_password:'replacement-synthetic-password'})).status,200);assert.equal(JSON.parse(fs.readFileSync(store))[names[0]].runtimeSlot,users[names[0]].runtimeSlot);
 assert.equal((await action('disable',names[1])).status,200);assert.equal((await signup('still-full')).status,503);
 await stop();await start();assert.equal((await login(names[0],'off','replacement-synthetic-password')).status,302);assert.equal((await login(names[1])).status,401);assert.equal((await signup('no-reuse')).status,503);
 console.log('Self signup: atomic exclusive allocation, capacity refusal, private routing, default Internet denial, admin grant/revoke, password change and restart persistence passed.');
}finally{await stop();await new Promise(r=>backend.close(r));fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
