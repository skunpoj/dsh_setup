'use strict';
// Administrator Delete with wipe and recycle, gateway half: a real gateway, disposable capacity files, no cluster.
// The controller's answers are written by the test into inventory/retirements/<slot>.json.
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http'),crypto=require('crypto');
const {spawn}=require('child_process');
const {hashPassword}=require('../scripts/password_store');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-wipe-')),port=42000+Math.floor(Math.random()*1000);
const request=(method,url,body='',cookie='',extra={})=>new Promise((resolve,reject)=>{
 const r=http.request({host:'127.0.0.1',port,path:url,method,headers:{cookie,'Content-Type':'application/x-www-form-urlencoded',...extra}},s=>{let text='';s.on('data',b=>text+=b);s.on('end',()=>resolve({status:s.statusCode,text,cookie:(s.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));});
 r.on('error',reject);r.end(body);
});
let child;
async function start(){child=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,
 DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_USER_TARGETS_FILE:path.join(root,'routes.json'),
 DSH_SIGNUP_POOL_FILE:path.join(root,'initial-pool.json'),DSH_CAPACITY_ROOT:path.join(root,'capacity'),DSH_ALLOW_REGISTRATION:'true',DSH_ADMIN_USERS:'admin',
 DSH_COOKIE_SECURE:'false',DSH_TRUSTED_HOST:'127.0.0.1:'+port},stdio:'ignore'});
 for(let i=0;i<80;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,50));}}throw Error('Candidate did not start');}
async function stop(){if(child&&child.exitCode===null){const p=child;await new Promise(r=>{p.once('exit',r);p.kill();});}}
const login=async(user,password)=>(await request('POST','/login',new URLSearchParams({username:user,password,internet:'off'}).toString())).cookie;
const write=(p,v)=>{fs.mkdirSync(path.dirname(path.join(root,p)),{recursive:true});fs.writeFileSync(path.join(root,p),JSON.stringify(v));};
const read=p=>JSON.parse(fs.readFileSync(path.join(root,p),'utf8'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(check,what,ms=15000){const end=Date.now()+ms;for(;;){const v=await check();if(v)return v;if(Date.now()>end)throw Error('Timed out waiting for '+what);await sleep(250);}}
const slotOf=()=>'cap-'+crypto.randomBytes(8).toString('hex')+'-01';
(async()=>{try{
 const target=(slot,env)=>{const id=crypto.createHash('sha256').update(slot).digest('hex').slice(0,16);return {host:`dsh-u-${id}-${env}.llm.svc.cluster.local`,port:3081,tokenFile:`/runtime-tokens/capacity/${id}/${env}/token`};};
 const slotDana=slotOf(),slotErin=slotOf();
 const pool={slots:Object.fromEntries([slotDana,slotErin].map(s=>[s,{secure:target(s,'secure'),internet:target(s,'internet')}]))};
 write('capacity/policy/policy.json',{version:1,enabled:true,warmSpareSlots:2});write('capacity/inventory/pool.json',pool);write('initial-pool.json',{slots:{}});
 write('capacity/inventory/status.json',{observedAt:new Date().toISOString(),available:true});
 const adminTarget={host:'127.0.0.1',port:3081,tokenFile:'/runtime-tokens/unused'};write('routes.json',{admin:{secure:adminTarget,internet:adminTarget}});
 write('users.json',{admin:hashPassword('synthetic-admin'),
  dana:{...hashPassword('dana-synthetic-password'),internetAllowed:false,runtimeSlot:slotDana},erin:{...hashPassword('erin-synthetic-password'),internetAllowed:false,runtimeSlot:slotErin}});
 await start();
 const admin=await login('admin','synthetic-admin');assert(admin);assert(await login('dana','dana-synthetic-password'));
 let info=JSON.parse((await request('GET','/api/admin/users','',admin)).text);
 assert.equal(info.users.find(u=>u.user==='dana').recyclable,true);assert.equal(info.users.find(u=>u.user==='admin').recyclable,false);
 const del=(user,confirm)=>request('POST','/api/admin/users',new URLSearchParams({action:'delete',user,...(confirm===undefined?{}:{confirm})}).toString(),admin,{'X-DSH-Admin-CSRF':info.csrfToken});
 const listed=async user=>JSON.parse((await request('GET','/api/admin/users','',admin)).text).users.find(u=>u.user===user);
 const requestFile=slot=>path.join(root,'capacity','policy','retirements',slot+'.json');
 // Refused deletes create no request and change nothing.
 assert.equal((await del('dana')).status,400);assert.equal((await del('dana','erin')).status,400);assert.equal((await del('admin','admin')).status,409);
 assert(!fs.existsSync(requestFile(slotDana)));assert.equal(read('users.json').dana.deleted,undefined);
 // Delete: tombstone first, then an audited request naming exactly this slot and account.
 const done=await del('dana','dana');assert.equal(done.status,200);assert.equal(JSON.parse(done.text).wipe,'requested');
 const request1=JSON.parse(fs.readFileSync(requestFile(slotDana),'utf8'));
 assert.equal(request1.slot,slotDana);assert.equal(request1.user,'dana');assert.equal(request1.requestedBy,'admin');assert(!fs.existsSync(requestFile(slotErin)),'only the named slot may be requested');
 const tomb=read('users.json').dana;assert.equal(tomb.deleted,true);assert.equal(tomb.disabled,true);assert.equal(tomb.runtimeSlot,slotDana);
 assert.equal(await login('dana','dana-synthetic-password'),'');
 assert.equal((await listed('dana')).wipe,'pending');assert.equal((await listed('dana')).deleted,true);
 // The controller is told this slot is held by a deleted account (its second guard); the live account's slot is not listed.
 const projection=await until(()=>{try{const p=read('capacity/policy/assignments.json');return p.deletedSlots&&p.deletedSlots.includes(slotDana)?p:null;}catch{return null;}},'the assignments projection');
 assert.deepEqual(projection.deletedSlots,[slotDana]);assert(projection.assignedSlots.includes(slotErin)&&projection.assignedSlots.includes(slotDana));
 // A result for another account or another slot never removes the tombstone.
 const resultFile=slot=>path.join(root,'capacity','inventory','retirements',slot+'.json');
 fs.mkdirSync(path.dirname(resultFile(slotDana)),{recursive:true});
 fs.writeFileSync(resultFile(slotDana),JSON.stringify({state:'retiring',slot:slotDana,account:'dana',phase:'stop'}));assert.equal((await listed('dana')).wipe,'retiring');
 fs.writeFileSync(resultFile(slotDana),JSON.stringify({state:'done',slot:slotErin,account:'dana'}));await sleep(6500);assert(read('users.json').dana,'a result for another slot must not remove the tombstone');
 fs.writeFileSync(resultFile(slotDana),JSON.stringify({state:'done',slot:slotDana,account:'erin'}));await sleep(6500);assert(read('users.json').dana,'a result for another account must not remove the tombstone');
 // The controller reports done for exactly this slot and account: the tombstone goes and the person can start clean.
 fs.writeFileSync(resultFile(slotDana),JSON.stringify({state:'done',slot:slotDana,account:'dana'}));
 await until(()=>!read('users.json').dana,'the tombstone to be removed after a done result');
 assert(read('users.json').erin&&!read('users.json').erin.deleted,'other accounts are untouched');
 const audit=JSON.parse((await request('GET','/api/admin/audit','',admin)).text).events;
 for(const event of ['account.delete','account.slot-wipe-requested','account.slot-wiped'])assert(audit.some(r=>r.event===event&&r.subject==='dana'),event);
 assert(!(await listed('dana')));
 // A failed or refused wipe keeps the tombstone and says so; nothing is recycled.
 info=JSON.parse((await request('GET','/api/admin/users','',admin)).text);
 assert.equal((await del('erin','erin')).status,200);
 fs.writeFileSync(resultFile(slotErin),JSON.stringify({state:'quarantined',slot:slotErin,account:'erin',phase:'files',error:'Files could not be removed'}));
 await sleep(6500);assert.equal(read('users.json').erin.deleted,true);assert.equal((await listed('erin')).wipe,'quarantined');
 assert.equal((await del('erin','erin')).status,409,'a deleted account refuses further deletes');
 await stop();await start();
 const again=await login('admin','synthetic-admin');assert.equal(JSON.parse((await request('GET','/api/admin/users','',again)).text).users.find(u=>u.user==='erin').wipe,'quarantined');
 console.log(JSON.stringify({passed:true,checks:['refused deletes change nothing','tombstone before request','request names only the slot','deleted slots projected to the controller','results for another slot or account ignored','done removes the tombstone','audit trail','quarantine keeps the tombstone','survives restart']}));
}finally{await stop();fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
