const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const {spawn} = require('child_process');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-admin-'));
const source = path.join(__dirname, '../scripts/auth_proxy.js');
const port = 39590, backendPort = 39591;
const request = (method, route, body='', cookie='', extra={}) => new Promise((resolve,reject)=>{
 const req=http.request({host:'127.0.0.1',port,path:route,method,headers:{cookie,
  'content-type':'application/x-www-form-urlencoded','content-length':Buffer.byteLength(body),...extra}},res=>{
  let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,headers:res.headers,
   cookie:(res.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));});req.on('error',reject);req.end(body);
});
(async()=>{
 fs.writeFileSync(path.join(root,'users.json'),JSON.stringify({admin:'synthetic-admin',alice:'synthetic-ordinary'}));
 const snapshot={observedAt:'2026-10-16T06:32:56Z',environments:[{name:'No Internet',ready:true,storage:'CIFS',network:'HTTPS denied'}],
  model:{backendContext:1048576,userContext:131072,concurrencyCeiling:16},performance:['Short: 0.23 seconds'],
  gaps:['<img src=x onerror="window.dashboardXSS=true">'],password:'DO_NOT_EXPORT',rawSecret:{token:'DO_NOT_EXPORT'}};
 fs.writeFileSync(path.join(root,'summary.json'),JSON.stringify(snapshot));
 const backend=http.createServer((req,res)=>{res.writeHead(200,{'content-type':'text/html'});res.end('<html><body>DSH fixture</body></html>');});
 await new Promise(r=>backend.listen(backendPort,'127.0.0.1',r));
 const gateway=spawn(process.execPath,[source],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,
  DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),
  DSH_ADMIN_USERS:'admin',DSH_ADMIN_SUMMARY_FILE:path.join(root,'summary.json'),
  DSH_TARGET_PORT:String(backendPort),DSH_TRUSTED_HOST:'127.0.0.1',DSH_COOKIE_SECURE:'false'},stdio:'ignore'});
 let browser;
 try{
  for(let i=0;i<80;i++){try{await request('GET','/login');break;}catch{await new Promise(r=>setTimeout(r,50));}}
  for(const route of ['/admin','/api/admin/summary']){
   const anonymous=await request('GET',route);assert(anonymous.text.includes('id="pane-login"'));assert(!anonymous.text.includes('registeredAccounts'));
  }
  const login=async(username,password)=>(await request('POST','/login',new URLSearchParams({username,password,internet:'off'}).toString())).cookie;
  const ordinary=await login('alice','synthetic-ordinary');const admin=await login('admin','synthetic-admin');
  for(const route of ['/admin','/api/admin/summary']) assert.equal((await request('GET',route,'',ordinary,{'x-dsh-user':'admin','x-dsh-role':'admin'})).status,403);
  assert.equal((await request('POST','/api/admin/summary','',admin)).status,405);
  const result=await request('GET','/api/admin/summary','',admin);const data=JSON.parse(result.text);
  assert.equal(data.registeredAccounts,2);assert.equal(data.privateUserRouting,false);assert.equal(data.snapshot.model.userContext,131072);
  assert(!result.text.includes('DO_NOT_EXPORT'));assert(!result.text.includes('synthetic-admin'));assert.equal(result.headers['cache-control'],'no-store');
  assert((await request('GET','/','',admin)).text.includes('id="dsh-admin-dashboard"'));
  assert(!(await request('GET','/','',ordinary)).text.includes('id="dsh-admin-dashboard"'));
  const {chromium}=require(process.env.DSH_PLAYWRIGHT || 'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addCookies([{name:'dsh_auth',value:admin.split('=')[1],url:`http://127.0.0.1:${port}`}]);
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/admin`);await page.waitForFunction(()=>document.getElementById('accounts').textContent==='2');
  assert.equal(await page.locator('#routing').textContent(),'Shared pools');assert.equal(await page.locator('#gaps img').count(),0);
  assert.equal(await page.evaluate(()=>Boolean(window.dashboardXSS)),false);assert.deepEqual(errors,[]);
  await page.click('#refresh');assert((await page.locator('#freshness').textContent()).includes(snapshot.observedAt));
  if(process.env.DSH_ADMIN_QA_OUTPUT){fs.mkdirSync(process.env.DSH_ADMIN_QA_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.DSH_ADMIN_QA_OUTPUT,'admin-dashboard.png'),fullPage:true});}
  await browser.close();browser=null;
  fs.unlinkSync(path.join(root,'summary.json'));const missing=JSON.parse((await request('GET','/api/admin/summary','',admin)).text);assert.equal(missing.snapshot.observedAt,null);assert.deepEqual(missing.snapshot.environments,[]);
  await request('GET','/logout','',admin);assert((await request('GET','/admin','',admin)).text.includes('id="pane-login"'));
  const audit=fs.readFileSync(path.join(root,'audit/events.jsonl'),'utf8');
  assert(!audit.includes('synthetic-admin')&&!audit.includes('synthetic-ordinary'));
  assert(audit.includes('login.success')&&audit.includes('admin.denied')&&audit.includes('logout'));
  for(const line of audit.trim().split('\n'))assert.deepEqual(Object.keys(JSON.parse(line)).sort(),['environment','event','time','user']);
  fs.writeFileSync(path.join(root,'audit/events.jsonl'),'x'.repeat(5*1024*1024));
  fs.writeFileSync(path.join(root,'audit/events.5.jsonl'),'preserved archive');
  const full=await request('POST','/login','username=admin&password=synthetic-admin&internet=off');
  assert.equal(full.status,503);assert(!full.headers['set-cookie']);
  assert.equal(fs.readFileSync(path.join(root,'audit/events.5.jsonl'),'utf8'),'preserved archive');
  const evidence={passed:true,timeUTC:new Date().toISOString(),gatewayOverlaySHA256:crypto.createHash('sha256').update(fs.readFileSync(source,'utf8').replace(/\r\n/g,'\n')).digest('hex'),
   checks:['anonymous denied','ordinary user denied despite forged admin headers','admin access','read-only methods','secret projection','admin-only navigation','browser rendering','snapshot timestamps','DOM injection inert','missing snapshot unknown','logout revokes access','audit contains no passwords','audit schema constrained','full audit capacity denies new login and preserves archives']};
  if(process.env.DSH_TEST_EVIDENCE_OUTPUT)fs.writeFileSync(process.env.DSH_TEST_EVIDENCE_OUTPUT,JSON.stringify(evidence,null,2));
  console.log(JSON.stringify(evidence));
 }finally{if(browser)await browser.close();gateway.kill();await new Promise(r=>gateway.once('exit',r));await new Promise(r=>backend.close(r));fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
