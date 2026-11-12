'use strict';
// Login-page "Accounts" bar: registered accounts against what the shared resources allow.
// Public /api/status carries aggregate numbers only; the bar must render at phone width without sideways scrolling.
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http');
const {spawn}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-accounts-bar-')),port=43000+Math.floor(Math.random()*900);
const request=(method,url)=>new Promise((resolve,reject)=>{
 const r=http.request({host:'127.0.0.1',port,path:url,method},s=>{let text='';s.on('data',b=>text+=b);s.on('end',()=>resolve({status:s.statusCode,text}));});r.on('error',reject);r.end();
});
const json=(p,v)=>{fs.mkdirSync(path.dirname(path.join(root,p)),{recursive:true});fs.writeFileSync(path.join(root,p),JSON.stringify(v));};
let child;
async function start(){child=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,
 DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_USER_TARGETS_FILE:path.join(root,'routes.json'),
 DSH_SIGNUP_POOL_FILE:path.join(root,'initial-pool.json'),DSH_CAPACITY_ROOT:path.join(root,'capacity'),DSH_COOKIE_SECURE:'false',DSH_TRUSTED_HOST:'127.0.0.1:'+port},stdio:'ignore'});
 for(let i=0;i<80;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,50));}}throw Error('Candidate did not start');}
const resources=['cpu','memoryGiB','pods','storageGiB'].map(resource=>({resource,available:100,reserve:10,pairBudget:5,afterReserve:90,additionalPairs:18}));
const capacity=(registered,extra,ceiling,limiting)=>({version:1,mainRegistered:registered,additionalDeploymentsComplete:true,additionalAccounts:extra,
 additionalDeployments:extra?[{label:'DSH2',accounts:extra,readyWorkers:1,desiredWorkers:1}]:[],readyPairs:1,additionalPairsPossible:ceiling-registered-1,
 mainPlanningCeiling:ceiling,limitingResources:limiting,centralStorageFreeGiB:500,observedUsage:{timestamp:new Date().toISOString(),cpu:1,memoryGiB:10,reservedCPU:2,reservedMemoryGiB:20},resources});
const status=cap=>json('capacity/inventory/status.json',{observedAt:new Date().toISOString(),available:true,...(cap?{capacity:cap}:{})});
(async()=>{try{
 const name='dsh-u-'+'a'.repeat(16)+'-secure',target={host:name+'.llm.svc.cluster.local',port:3081,tokenFile:'/runtime-tokens/unused'};
 json('users.json',{alice:'synthetic-alice-password',bob:'synthetic-bob-password'});
 json('routes.json',{alice:{secure:target,internet:{...target,host:'dsh-u-'+'a'.repeat(16)+'-internet.llm.svc.cluster.local'}},bob:{secure:target,internet:target}});
 json('initial-pool.json',{slots:{}});json('capacity/inventory/pool.json',{slots:{}});json('capacity/policy/policy.json',{version:1,enabled:true,warmSpareSlots:2});
 json('capacity/inventory/sessions.json',{version:1,observedAt:new Date().toISOString(),available:true,runtimes:{},summary:{running:0,starting:0,waiting:0,stopped:2,startsAvailable:3,idleTimeoutSeconds:3600}});
 status(capacity(2,1,20,['storageGiB']));
 await start();
 // The page script carries the bar; the API carries aggregate numbers only (no names, no slots, no identities).
 assert((await request('GET','/login')).text.includes("row('Accounts'"),'Login page has the Accounts bar');
 let body=JSON.parse((await request('GET','/api/status')).text);
 assert.deepEqual(body.accounts,{registered:3,allowance:21,limitedBy:['storage']});
 assert(!/alice|bob|dsh-u-|cap-/.test(JSON.stringify(body)),'No identities in the public status');
 // Several limits are named in plain words; a stale or missing controller report shows no bar instead of a wrong one.
 status(capacity(2,0,12,['cpu','memoryGiB','inventory']));await new Promise(r=>setTimeout(r,200));
 assert.deepEqual(JSON.parse((await request('GET','/api/status')).text).accounts,{registered:2,allowance:12,limitedBy:['CPU','memory','workspace inventory']});
 status(capacity(5,0,12,['cpu']));await new Promise(r=>setTimeout(r,200));      // registered differs from the real count: inconsistent
 assert.equal(JSON.parse((await request('GET','/api/status')).text).accounts,undefined);
 status(undefined);await new Promise(r=>setTimeout(r,200));
 assert.equal(JSON.parse((await request('GET','/api/status')).text).accounts,undefined);
 json('capacity/inventory/status.json',{observedAt:new Date(Date.now()-600000).toISOString(),available:true,capacity:capacity(2,0,12,['cpu'])});
 assert.equal(JSON.parse((await request('GET','/api/status')).text).accounts,undefined,'a stale report shows no bar');
 // Browser: the bar renders from that API and the page does not scroll sideways at phone widths.
 status(capacity(2,1,20,['storageGiB']));
 const {chromium}=require(process.env.DSH_PLAYWRIGHT||'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}:{})});
 try{
  const page=await (await browser.newContext({viewport:{width:1440,height:900}})).newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+port+'/login');
  await page.waitForFunction(()=>[...document.querySelectorAll('#resourceBars .rs-row')].some(r=>r.textContent.startsWith('Accounts')),{},{timeout:10000});
  const row=await page.evaluate(()=>{const r=[...document.querySelectorAll('#resourceBars .rs-row')].find(x=>x.textContent.startsWith('Accounts'));return {text:r.textContent,now:r.querySelector('.rs-bar').getAttribute('aria-valuenow'),width:r.querySelector('.rs-use').style.width};});
  assert(row.text.includes('3 of 21 accounts the shared resources allow')&&row.text.includes('limited by storage'),row.text);
  assert.equal(row.now,'14');assert(row.width.startsWith('14.28'),row.width);
  for(const width of [1440,768,390,350,330]){
   await page.setViewportSize({width,height:900});
   const layout=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));
   assert(layout.scroll<=layout.viewport+1,JSON.stringify(layout));
  }
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
 console.log(JSON.stringify({passed:true,checks:['bar on the login page','aggregate numbers only','limits named in plain words','stale, missing or inconsistent report shows no bar','renders in a browser','no sideways scroll at 1440/768/390/350/330']}));
}finally{if(child&&child.exitCode===null){const p=child;await new Promise(r=>{p.once('exit',r);p.kill();});}fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
