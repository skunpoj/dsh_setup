'use strict';
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http'),crypto=require('crypto');
const {spawn}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-capacity-')),port=41000+Math.floor(Math.random()*1000);
const request=(method,url,body='',cookie='',extra={})=>new Promise((resolve,reject)=>{
 const r=http.request({host:'127.0.0.1',port,path:url,method,headers:{cookie,'Content-Type':'application/x-www-form-urlencoded',...extra}},s=>{let text='';s.on('data',b=>text+=b);s.on('end',()=>resolve({status:s.statusCode,text,cookie:(s.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));});r.on('error',reject);r.end(body);
});
let child;
async function start(){child=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,
 DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_USER_TARGETS_FILE:path.join(root,'routes.json'),
 DSH_SIGNUP_POOL_FILE:path.join(root,'initial-pool.json'),DSH_CAPACITY_ROOT:path.join(root,'capacity'),DSH_ALLOW_REGISTRATION:'true',
 DSH_COOKIE_SECURE:'false',DSH_TRUSTED_HOST:'127.0.0.1:'+port},stdio:'ignore'});
 for(let i=0;i<80;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,50));}}throw Error('Candidate did not start');}
async function stop(){if(child&&child.exitCode===null){const p=child;await new Promise(r=>{p.once('exit',r);p.kill();});}}
const login=async(user,password)=>(await request('POST','/login',new URLSearchParams({username:user,password,internet:'off'}).toString())).cookie;
const json=(p,v)=>fs.writeFileSync(path.join(root,p),JSON.stringify(v));
(async()=>{try{
 fs.mkdirSync(path.join(root,'capacity/policy'),{recursive:true});fs.mkdirSync(path.join(root,'capacity/inventory'),{recursive:true});
 json('users.json',{admin:'synthetic-admin',alice:'synthetic-alice'});
 const target={host:'127.0.0.1',port:3081,tokenFile:'/runtime-tokens/unused'};
 json('routes.json',{admin:{secure:target,internet:target},alice:{secure:target,internet:target}});
 json('initial-pool.json',{slots:{}});json('capacity/policy/policy.json',{version:1,enabled:true,warmSpareSlots:2});
 const healthy=registered=>({observedAt:new Date().toISOString(),available:true,capacity:{version:1,mainRegistered:registered,additionalDeploymentsComplete:true,additionalAccounts:2,
  additionalDeployments:[{label:'DSH2',accounts:1},{label:'DSH3',accounts:1}],observedUsage:{timestamp:new Date().toISOString(),cpu:1,memoryGiB:10,reservedCPU:2,reservedMemoryGiB:20},
  resources:['cpu','memoryGiB','pods','storageGiB'].map(resource=>({resource,available:10,reserve:2,pairBudget:1}))}});
 json('capacity/inventory/status.json',healthy(2));
 const pool={slots:{}};json('capacity/inventory/pool.json',pool);
 fs.writeFileSync(path.join(root,'history-preservation-marker'),'existing private data');
 await start();let admin=await login('admin','synthetic-admin'),alice=await login('alice','synthetic-alice');assert(admin&&alice);
 assert.equal((await request('GET','/api/admin/capacity','',alice,{'X-DSH-Role':'admin'})).status,403);
 let d=JSON.parse((await request('GET','/api/admin/capacity','',admin)).text);assert.equal(d.automaticProvisioning.policy.warmSpareSlots,2);
 const save=(body,extra={})=>request('POST','/api/admin/capacity',new URLSearchParams(body).toString(),admin,{'X-DSH-Admin-CSRF':d.csrfToken,...extra});
 const value={enabled:'true',warmSpareSlots:'2'};
 assert.equal((await request('POST','/api/admin/capacity',new URLSearchParams(value).toString(),admin)).status,403);
 assert.equal((await save(value,{Origin:'https://evil.example'})).status,403);
 for(const bad of [{warmSpareSlots:'-1'},{warmSpareSlots:'9'},{warmSpareSlots:'2.5'},{enabled:'shell'}])assert.equal((await save({...value,...bad})).status,400);
 assert.equal((await save(value)).status,200);
 // A controller publication becomes available without replacing the gateway.
 for(let i=0;i<2;i++){
  const slot='cap-'+crypto.randomBytes(8).toString('hex')+'-01',id=crypto.createHash('sha256').update(slot).digest('hex').slice(0,16);
  pool.slots[slot]=Object.fromEntries(['secure','internet'].map(env=>[env,{host:`dsh-u-${id}-${env}.llm.svc.cluster.local`,port:3081,tokenFile:`/runtime-tokens/capacity/${id}/${env}/token`}]));
 }
 json('capacity/inventory/pool.json',pool);
 let capacity=JSON.parse((await request('GET','/api/signup-capacity')).text);assert.equal(capacity.remainingSlots,2,'Accounts are not capped: every ready slot is offered');
 const register=user=>request('POST','/register',new URLSearchParams({username:user,password:'synthetic-new-password',confirm_password:'synthetic-new-password',internet:'on',role:'admin'}).toString());
 const intact=fs.readFileSync(path.join(root,'users.json')),policyBeforePressure=fs.readFileSync(path.join(root,'capacity/policy/policy.json'));
 const checkPaused=async snapshot=>{
  json('capacity/inventory/status.json',snapshot);
  const cap=await request('GET','/api/signup-capacity');assert.equal(cap.status,200);assert.equal(JSON.parse(cap.text).remainingSlots,0);
  assert.equal((await register('pressure_refused')).status,503,'Pressure must refuse even a ready spare');
  const adminCreate=await request('POST','/api/admin/users',new URLSearchParams({action:'create',user:'pressure_admin',password:'synthetic-new-password'}).toString(),admin,{'X-DSH-Admin-CSRF':d.csrfToken});
  assert.equal(adminCreate.status,503,'Admin create must not bypass the shared pressure gate');
  assert.deepEqual(fs.readFileSync(path.join(root,'users.json')),intact);
  assert.deepEqual(fs.readFileSync(path.join(root,'capacity/policy/policy.json')),policyBeforePressure);
 };
 // Compute pressure no longer blocks registration: an account holds storage only.
 for(const resource of ['cpu','memoryGiB','pods']){
  const s=healthy(2);s.capacity.resources.find(x=>x.resource===resource).available=0;json('capacity/inventory/status.json',s);
  assert.equal(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots,2,'Compute pressure keeps registration open');
 }
 { const s=healthy(2);s.capacity.resources.find(x=>x.resource==='storageGiB').available=0;await checkPaused(s); }
 const stale=healthy(2);stale.observedAt=new Date(Date.now()-120000).toISOString();await checkPaused(stale);
 const missing=healthy(2);missing.capacity.additionalDeploymentsComplete=false;await checkPaused(missing);
 assert(await login('alice','synthetic-alice'),'Existing login remains available while signup is paused');
 json('capacity/inventory/status.json',healthy(2));
 assert.equal(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots,2,'Healthy report automatically reopens warm spares without restart');
 assert.equal((await register('capacity_bob')).status,200);assert.equal(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots,0,'Signup waits for a controller report that counts the new account');
 json('capacity/inventory/status.json',healthy(3));
 assert.equal((await register('capacity_charlie')).status,200,'No account cap: the last ready slot is assigned');
 assert.equal((await request('POST','/login',new URLSearchParams({username:'capacity_bob',password:'synthetic-new-password',internet:'on'}).toString())).status,403);
 const before=JSON.parse(fs.readFileSync(path.join(root,'users.json')));assert(before.capacity_bob.runtimeSlot);assert.equal(before.capacity_bob.internetAllowed,false);
 // A policy stored before the account limit was removed (here a limit below the
 // registered count) must not break reads or saves. GET changes nothing.
 json('capacity/policy/policy.json',{version:1,enabled:true,warmSpareSlots:2,maxAccounts:2});
 const limitedPolicy=fs.readFileSync(path.join(root,'capacity/policy/policy.json'));
 const retainedStore=fs.readFileSync(path.join(root,'users.json'));
 const full=await request('GET','/api/signup-capacity');assert.equal(full.status,200);assert.equal(JSON.parse(full.text).remainingSlots,0);
 assert.equal(JSON.parse((await request('GET','/api/admin/capacity','',admin)).text).remainingSlots,0);
 assert(await login('admin','synthetic-admin'));assert(await login('alice','synthetic-alice'));
 assert.equal((await register('still_full')).status,503,'New account waits for the next prepared slot');
 assert.deepEqual(fs.readFileSync(path.join(root,'users.json')),retainedStore);
 assert.deepEqual(fs.readFileSync(path.join(root,'capacity/policy/policy.json')),limitedPolicy);
 assert.equal((await save(value)).status,200,'A legacy stored limit never blocks an admin save');
 assert.equal('maxAccounts' in JSON.parse(fs.readFileSync(path.join(root,'capacity/policy/policy.json'))),false,'Saving drops the legacy limit');
 assert.equal((await register('still_full')).status,503,'With no ready slot a new account still waits; no limit is involved');
 await stop();await start();assert.equal(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots,0);
 admin=await login('admin','synthetic-admin');d=JSON.parse((await request('GET','/api/admin/capacity','',admin)).text);
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'users.json'))),before);
 assert.equal((await save({...value,enabled:'false'})).status,200,'Saving the policy reserves nothing');
 json('capacity/inventory/status.json',{observedAt:new Date().toISOString(),available:true,capacity:{version:1,mainRegistered:4,additionalDeploymentsComplete:true,additionalAccounts:2,mainPlanningCeiling:5,readyPairs:1,additionalPairsPossible:1,resources:['cpu','memoryGiB','pods','storageGiB'].map(resource=>({resource,available:10,reserve:2,pairBudget:1,afterReserve:8,additionalPairs:8})),additionalDeployments:[{label:'DSH2',accounts:1,readyWorkers:1,desiredWorkers:1},{label:'DSH3',accounts:1,readyWorkers:1,desiredWorkers:1}]}});
 const measured=JSON.parse((await request('GET','/api/admin/capacity','',admin)).text).automaticProvisioning.controller.capacity;
 assert.equal(measured.totalRegistered,6);assert.equal(measured.mainPlanningCeiling,5);
 assert((await request('GET','/admin','',admin)).text.includes('capacityResources'));
 assert.equal((await save({...value,enabled:'false',warmSpareSlots:'1'})).status,200,'Accounts are admitted by storage, not a count or compute ceiling');
 assert.equal((await save({...value,enabled:'false'})).status,200);
 assert(!(await request('GET','/admin','',admin)).text.includes('capacityMax'),'The admin form has no account-limit field');
 json('capacity/inventory/status.json',healthy(4));
 await new Promise(r=>setTimeout(r,5200));const projection=JSON.parse(fs.readFileSync(path.join(root,'capacity/policy/assignments.json')));
 assert.equal(projection.registeredAccounts,4);assert.deepEqual(projection.assignedSlots,[before.capacity_bob.runtimeSlot,before.capacity_charlie.runtimeSlot].sort());assert(!JSON.stringify(projection).includes('password'));
 await stop();await start();admin=await login('admin','synthetic-admin');d=JSON.parse((await request('GET','/api/admin/capacity','',admin)).text);
 assert.equal(d.automaticProvisioning.policy.enabled,false);assert.equal('maxAccounts' in d.automaticProvisioning.policy,false);assert.equal(d.remainingSlots,0);
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(root,'users.json'))),before);assert.equal(fs.readFileSync(path.join(root,'history-preservation-marker'),'utf8'),'existing private data');
 const events=fs.readFileSync(path.join(root,'audit/events.jsonl'),'utf8').trim().split('\n').map(JSON.parse);assert(events.some(e=>e.event==='capacity.policy'&&e.capacity?.outcome==='applied'));
 console.log(JSON.stringify({status:'passed',adminAuthorization:true,csrfAndOriginDenials:true,capacityBounds:true,dynamicPublicationWithoutRestart:true,noAccountCapAndDefaultInternetDenial:true,policyAndAssignmentsPersisted:true,existingDataUnchanged:true,privateProjection:true}));
}finally{await stop();fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
