'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http');
const {spawn}=require('node:child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-capacity-')),port=19488;
const store=path.join(root,'users.json');
const route=tag=>({host:tag+'.internal.invalid',port:3081,tokenFile:'/runtime-tokens/'+tag});
fs.writeFileSync(store,JSON.stringify({admin:'synthetic-admin-password'}));
fs.writeFileSync(path.join(root,'routes.json'),JSON.stringify({admin:{secure:route('admin-secure'),internet:route('admin-internet')}}));
fs.writeFileSync(path.join(root,'pool.json'),JSON.stringify({slots:{'one-slot':{secure:route('one-secure'),internet:route('one-internet')},'two-slot':{secure:route('two-secure'),internet:route('two-internet')}}}));
const request=(method,url,fields={})=>new Promise((resolve,reject)=>{const body=new URLSearchParams(fields).toString();const q=http.request({host:'127.0.0.1',port,path:url,method,headers:{'Content-Type':'application/x-www-form-urlencoded'}},r=>{let text='';r.on('data',b=>text+=b);r.on('end',()=>resolve({status:r.statusCode,text,headers:r.headers}));});q.on('error',reject);q.end(method==='GET'?'':body);});
let gateway,browser;
(async()=>{try{
 const clean=Object.fromEntries(Object.entries(process.env).filter(([key])=>!/^(DSH_|AUTH_|WORKSPACE_ROOT$)/.test(key)));
 gateway=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...clean,PORT:String(port),WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:store,DSH_USER_TARGETS_FILE:path.join(root,'routes.json'),DSH_SIGNUP_POOL_FILE:path.join(root,'pool.json'),DSH_ALLOW_REGISTRATION:'true',DSH_TRUSTED_HOST:'127.0.0.1:'+port,DSH_COOKIE_SECURE:'false'},stdio:'ignore'});
 for(let i=0;i<80;i++){try{await request('GET','/login');break;}catch{await new Promise(r=>setTimeout(r,50));}}
 const before=await request('GET','/api/signup-capacity');assert.equal(before.status,200);assert.equal(before.headers['cache-control'],'no-store');
 const data=JSON.parse(before.text);assert.equal(data.remainingSlots,2);assert.equal(data.registrationEnabled,true);
 assert.deepEqual(Object.keys(data).sort(),['observedAt','registrationEnabled','remainingSlots']);
 assert.equal((await request('POST','/api/signup-capacity')).status,405);
 const {chromium}=require(process.env.DSH_PLAYWRIGHT||'playwright');
 browser=await chromium.launch({headless:true,executablePath:process.env.DSH_BROWSER_EXECUTABLE||(process.platform==='win32'?'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe':undefined)});
 const artifacts=process.env.DSH_CAPACITY_ARTIFACT_DIR;if(artifacts)fs.mkdirSync(artifacts,{recursive:true});
 const context=await browser.newContext({viewport:{width:1280,height:900},...(artifacts?{recordVideo:{dir:artifacts,size:{width:1280,height:900}}}:{})});
 // Speed up only the polling clock in this test; the shipped source stays 15s.
 await context.addInitScript(()=>{const original=window.setInterval;window.setInterval=(fn,delay,...args)=>original(fn,delay===15000?250:delay,...args);});
 const page=await context.newPage();const base='http://127.0.0.1:'+port;
 await page.goto(base+'/login');await page.locator('#tab-register').click();
 await page.waitForFunction(()=>document.querySelector('#signupSlots')?.textContent==='Registration is open.');
 if(artifacts){await page.screenshot({path:path.join(artifacts,'signup-capacity.png')});await page.waitForTimeout(1000);}
 for(const [index,user]of ['demo_one','demo_two'].entries()){
  assert.equal((await request('POST','/register',{username:user,password:'synthetic-long-password',confirm_password:'synthetic-long-password'})).status,200);
  await page.waitForFunction(n=>document.querySelector('#signupSlots')?.textContent===(n>0?'Registration is open.':'No new-user workspace is prepared. Please contact the administrator.'),1-index);
  assert.equal(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots,1-index);
  if(artifacts)await page.waitForTimeout(1300);
 }
 await page.route('**/api/signup-capacity',r=>r.fulfill({status:503,contentType:'application/json',body:'{"error":"Unavailable"}'}));
 await page.waitForFunction(()=>document.querySelector('#signupSlots')?.textContent.includes('Registration status unavailable'));
 await page.unroute('**/api/signup-capacity');
 await page.waitForFunction(()=>document.querySelector('#signupSlots')?.textContent==='No new-user workspace is prepared. Please contact the administrator.');
 await page.request.post(base+'/login',{form:{username:'admin',password:'synthetic-admin-password',internet:'off'}});
 await page.goto(base+'/admin');await page.waitForFunction(()=>document.querySelector('#newUserSlots')?.textContent==='0');
 const summary=await (await page.request.get(base+'/api/admin/summary')).json();
 assert.deepEqual({...summary.capacity,observedAt:undefined},{observedAt:undefined,registrationEnabled:true,provisionedSlots:2,assignedSlots:2,remainingSlots:0,enabledAccounts:3,disabledAccounts:0});
 assert((await page.locator('#slotDetail').innerText()).includes('2 / 2 prepared slots assigned'));
 if(artifacts){await page.screenshot({path:path.join(artifacts,'admin-capacity.png')});await page.waitForTimeout(1700);}
 const users=JSON.parse(fs.readFileSync(store));users.demo_one.disabled=true;fs.writeFileSync(store,JSON.stringify(users));
 await page.click('#refresh');await page.waitForFunction(()=>document.querySelector('#slotDetail')?.textContent.includes('2 enabled / 1 disabled'));
 assert.equal(JSON.parse((await request('GET','/api/signup-capacity')).text).remainingSlots,0,'Disabled accounts retain their assigned slot');
 await context.close();
 console.log(JSON.stringify({passed:true,aggregateOnly:true,browserCountUpdates:[2,1,0],staleFailureReplaced:true,adminCapacityReadback:true,disabledAccountSlotNotReused:true}));
}finally{if(browser)await browser.close();if(gateway&&gateway.exitCode===null){gateway.kill();await new Promise(r=>gateway.once('exit',r));}fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});

// Automatic capacity uses the existing CI entry point without workflow changes.
require('child_process').execFileSync(process.execPath,[require('path').join(__dirname,'test_capacity_policy.js')],{stdio:'inherit'});
require('child_process').execFileSync(process.execPath,[require('path').join(__dirname,'test_admin_capacity.js')],{stdio:'inherit'});
