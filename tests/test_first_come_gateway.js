'use strict';
// Gateway behaviour for first-come, first-reserved workspaces: a signed-in user
// whose workspace is stopped or queued gets a waiting page (browsers) or a 503
// with Retry-After (API clients); the sign-in page shows aggregate status only.
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http');
const {spawn}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-first-come-')),port=42000+Math.floor(Math.random()*1000);
const request=(method,url,body='',cookie='',extra={})=>new Promise((resolve,reject)=>{
 const r=http.request({host:'127.0.0.1',port,path:url,method,headers:{cookie,'Content-Type':'application/x-www-form-urlencoded',...extra}},s=>{let text='';s.on('data',b=>text+=b);s.on('end',()=>resolve({status:s.statusCode,text,headers:s.headers,cookie:(s.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));});r.on('error',reject);r.end(body);
});
const json=(p,v)=>fs.writeFileSync(path.join(root,p),JSON.stringify(v));
const read=p=>JSON.parse(fs.readFileSync(path.join(root,p),'utf8'));
let child;
(async()=>{try{
 fs.mkdirSync(path.join(root,'capacity/policy'),{recursive:true});fs.mkdirSync(path.join(root,'capacity/inventory'),{recursive:true});
 const name='dsh-u-'+'a'.repeat(16)+'-secure';
 const target={host:name+'.llm.svc.cluster.local',port:3081,tokenFile:'/runtime-tokens/unused'};
 json('users.json',{alice:'synthetic-alice-password'});json('routes.json',{alice:{secure:target,internet:{...target,host:'dsh-u-'+'a'.repeat(16)+'-internet.llm.svc.cluster.local'}}});
 json('initial-pool.json',{slots:{}});json('capacity/inventory/pool.json',{slots:{}});
 json('capacity/policy/policy.json',{version:1,enabled:true,warmSpareSlots:2});
 const sessions=(state,position)=>json('capacity/inventory/sessions.json',{version:1,observedAt:new Date().toISOString(),available:true,
  runtimes:{[name]:{state,...(position?{position}:{})}},summary:{running:state==='running'?1:0,starting:state==='starting'?1:0,waiting:state==='waiting'?1:0,stopped:0,startsAvailable:0,idleTimeoutSeconds:3600}});
 child=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,
  DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_USER_TARGETS_FILE:path.join(root,'routes.json'),
  DSH_SIGNUP_POOL_FILE:path.join(root,'initial-pool.json'),DSH_CAPACITY_ROOT:path.join(root,'capacity'),
  DSH_COOKIE_SECURE:'false',DSH_TRUSTED_HOST:'127.0.0.1:'+port},stdio:'ignore'});
 for(let i=0;i<80;i++){try{await request('GET','/login');break;}catch{await new Promise(r=>setTimeout(r,50));}}
 // Sign-in page carries the live status panel; the API is aggregate only.
 assert((await request('GET','/login')).text.includes('id="resourceStatus"'));
 sessions('waiting',3);
 const status=JSON.parse((await request('GET','/api/status')).text);
 assert.equal(status.available,true);assert.deepEqual(status.workspaces,{running:0,starting:0,waiting:1,stopped:0,capacity:0});
 assert(!JSON.stringify(status).includes('dsh-u-')&&!JSON.stringify(status).includes('alice'),'No identities in public status');
 assert.equal((await request('POST','/api/status')).status,405);
 const cookie=(await request('POST','/login',new URLSearchParams({username:'alice',password:'synthetic-alice-password',internet:'off'}).toString())).cookie;assert(cookie);
 // Queued: browsers get a self-refreshing page with their position.
 const page=await request('GET','/','',cookie,{Accept:'text/html'});
 assert.equal(page.status,200);assert.equal(page.headers.refresh,'3');assert(page.text.includes('number 3 in the queue'));assert(!page.text.includes('<script'));
 // API clients get 503 + Retry-After instead of a proxied error.
 const api=await request('GET','/api/session/list','',cookie,{Accept:'application/json'});
 assert.equal(api.status,503);assert.equal(api.headers['retry-after'],'3');assert.equal(JSON.parse(api.text).state,'waiting');
 sessions('starting');assert((await request('GET','/','',cookie,{Accept:'text/html'})).text.includes('Your workspace is starting'));
 // Spawn progress: bar, current stage, 3 s refresh, and the same progress for API clients.
 json('capacity/inventory/sessions.json',{version:1,observedAt:new Date().toISOString(),available:true,
  runtimes:{[name]:{state:'starting',progress:{stage:'pulling-image',percent:45,detail:'Loading the workspace image'}}},summary:{running:0,starting:1,waiting:0,stopped:0,startsAvailable:0,idleTimeoutSeconds:3600}});
 const spawnPage=await request('GET','/','',cookie,{Accept:'text/html'});
 assert.equal(spawnPage.headers.refresh,'3');assert(spawnPage.text.includes('role="progressbar"')&&spawnPage.text.includes('aria-valuenow="45"')&&spawnPage.text.includes('45%'));
 assert(spawnPage.text.includes('class="now"')&&spawnPage.text.includes('Loading the workspace image')&&!spawnPage.text.includes('<script'));
 assert.deepEqual(JSON.parse((await request('GET','/api/x','',cookie,{Accept:'application/json'})).text).progress,{stage:'pulling-image',percent:45,detail:'Loading the workspace image'});
 assert((await request('GET','/login')).text.includes('id="resourceBars"'),'Sign-in page has the utilisation bars');
 // Demand is published without user names and keeps the first request time.
 await new Promise(r=>setTimeout(r,5500));
 const demand=read('capacity/policy/demand.json');assert(demand.runtimes[name],'Signed-in use is published as demand');assert(!JSON.stringify(demand).includes('alice'));
 // Running: the gateway proxies as before (the synthetic host does not resolve, so no waiting page).
 sessions('running');const proxied=await request('GET','/','',cookie,{Accept:'text/html'});assert(!proxied.text.includes('Starting your workspace'));
 // Signing out releases the workspace at once.
 await request('GET','/logout','',cookie);await new Promise(r=>setTimeout(r,5500));
 assert.deepEqual(read('capacity/policy/demand.json').runtimes,{},'Sign-out releases demand');
 console.log(JSON.stringify({status:'passed',statusPanel:true,aggregateOnly:true,queuePage:true,apiRetryAfter:true,demandPublished:true,signOutRelease:true}));
}finally{if(child&&child.exitCode===null){await new Promise(r=>{child.once('exit',r);child.kill();});}fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
