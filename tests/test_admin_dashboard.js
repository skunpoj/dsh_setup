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
  model:{backendContext:1048576,userContext:131072,concurrencyCeiling:16,checkpoint:'DO_NOT_EXPORT',revision:'DO_NOT_EXPORT'},performance:['Short: 0.23 seconds'],
  gaps:['<img src=x onerror="window.dashboardXSS=true">'],password:'DO_NOT_EXPORT',rawSecret:{token:'DO_NOT_EXPORT'}};
 fs.writeFileSync(path.join(root,'summary.json'),JSON.stringify(snapshot));
 fs.mkdirSync(path.join(root,'audit/legacy/legacy-dsh2'),{recursive:true});
 fs.writeFileSync(path.join(root,'audit/legacy/legacy-dsh2/events.jsonl'),JSON.stringify({time:new Date().toISOString(),event:'terminal.open',user:'user2',environment:'legacy-dsh2/internet',password:'PROJECTION_SECRET'})+'\n');
 fs.writeFileSync(path.join(root,'audit/legacy/legacy-dsh2/status.json'),JSON.stringify({observedAt:'2026-10-17T00:00:00Z',instances:[{name:'legacy-dsh2',events:1}],password:'PROJECTION_SECRET'}));
 const backend=http.createServer((req,res)=>{res.writeHead(200,{'content-type':'text/html'});res.end('<html><body>DSH fixture</body></html>');});
 await new Promise(r=>backend.listen(backendPort,'127.0.0.1',r));
 const gateway=spawn(process.execPath,[source],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,
  DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),
  DSH_ADMIN_USERS:'admin',DSH_ADMIN_SUMMARY_FILE:path.join(root,'summary.json'),
  DSH_TARGET_PORT:String(backendPort),DSH_TRUSTED_HOST:'127.0.0.1',DSH_COOKIE_SECURE:'false'},stdio:'ignore'});
 let browser;
 try{
  for(let i=0;i<80;i++){try{await request('GET','/login');break;}catch{await new Promise(r=>setTimeout(r,50));}}
  for(const route of ['/admin','/api/admin/summary','/api/admin/telemetry']){
   const anonymous=await request('GET',route);if(route.startsWith('/api/')){assert.equal(anonymous.status,401);assert.equal(JSON.parse(anonymous.text).error,'AUTHENTICATION_REQUIRED');}else assert(anonymous.text.includes('id="pane-login"'));assert(!anonymous.text.includes('registeredAccounts'));
  }
  const login=async(username,password)=>(await request('POST','/login',new URLSearchParams({username,password,internet:'off'}).toString())).cookie;
  const ordinary=await login('alice','synthetic-ordinary');const admin=await login('admin','synthetic-admin');
  for(const route of ['/admin','/api/admin/summary','/api/admin/telemetry']) assert.equal((await request('GET',route,'',ordinary,{'x-dsh-user':'admin','x-dsh-role':'admin'})).status,403);
  assert.equal((await request('POST','/api/admin/summary','',admin)).status,405);
  assert.equal((await request('POST','/api/admin/telemetry','',admin)).status,405);
  const telemetry=await request('GET','/api/admin/telemetry','',admin);
  assert.equal(telemetry.status,200);assert.equal(telemetry.headers['cache-control'],'no-store');
  assert.equal(JSON.parse(telemetry.text).configuredRuntimes,0);
  assert(!telemetry.text.includes('DO_NOT_EXPORT'));assert(!telemetry.text.includes('synthetic-admin'));
  const result=await request('GET','/api/admin/summary','',admin);const data=JSON.parse(result.text);
  assert.equal(data.registeredAccounts,2);assert.equal(data.privateUserRouting,false);assert.equal(data.snapshot.model.userContext,131072);
  assert.equal(data.audit.legacy.instances[0].events,1);
  const merged=await request('GET','/api/admin/audit','',admin);assert(merged.text.includes('legacy-dsh2/internet'));assert(!merged.text.includes('PROJECTION_SECRET'));
  assert(!result.text.includes('DO_NOT_EXPORT'));assert(!result.text.includes('synthetic-admin'));assert.equal(result.headers['cache-control'],'no-store');
  assert((await request('GET','/','',admin)).text.includes('id="dsh-admin-dashboard"'));
  assert(!(await request('GET','/','',ordinary)).text.includes('id="dsh-admin-dashboard"'));
  const {chromium}=require(process.env.DSH_PLAYWRIGHT || 'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
  const executablePath=process.env.DSH_BROWSER_EXECUTABLE || (process.platform==='win32'?'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe':undefined);
  browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
  const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'en-US'});
  await context.addCookies([{name:'dsh_auth',value:admin.split('=')[1],url:`http://127.0.0.1:${port}`}]);
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/admin`);await page.waitForFunction(()=>document.getElementById('accounts').textContent==='2');
  assert.equal(await page.locator('#routing').textContent(),'Shared pools');assert.equal(await page.locator('#gaps img').count(),0);
  assert.equal(await page.evaluate(()=>Boolean(window.dashboardXSS)),false);assert.deepEqual(errors,[]);
  await page.click('#refresh');assert((await page.locator('#freshness').textContent()).includes(snapshot.observedAt));
  const usageFixture={observedAt:'2026-10-19T04:00:00Z',configuredRuntimes:2,availableRuntimes:2,
   totals:{sessions:3,runningAgents:1,queuedMessages:2,turns:7,llmSteps:12,inputTokens:5500,outputTokens:900,usageSessions:3,recordedDecodeTokensPerSecond:25,recentDecodeTokensPerSecond:80,outputTokensPerSecond:2.5},
   runtimes:[{user:'alice',environment:'secure',available:true,runningAgents:1,sessions:2,turns:5,llmSteps:8,inputTokens:3500,outputTokens:600,recordedDecodeTokensPerSecond:30}],
   storage:{observedAt:'2026-10-19T03:00:00Z',runtimes:[{user:'alice',environment:'secure',workspaceFileBytes:67108864,workspaceScanComplete:true,durableStateFileBytes:33554432,durableStateScanComplete:false,stateUsedBytes:1073741824,stateCapacityBytes:5368709120}]},
   prompt:'PRIVATE_TELEMETRY',password:'PRIVATE_TELEMETRY'};
  await page.route('**/api/admin/telemetry',route=>route.fulfill({json:usageFixture}));await page.click('#refresh');
  await page.waitForFunction(()=>document.getElementById('usageSessions').textContent==='3');
  assert.equal(await page.locator('#usageAgents').textContent(),'1');assert.equal(await page.locator('#usageTokens').textContent(),'5,500 / 900');
  assert.equal(await page.locator('#usageRecentDecode').textContent(),'80');assert.equal(await page.locator('#usageRows tr').count(),1);
  assert((await page.locator('#usageRows').textContent()).includes('(partial)'));assert(!(await page.locator('body').textContent()).includes('PRIVATE_TELEMETRY'));
  for(const width of [1440,768,390]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));}
  await page.setViewportSize({width:1440,height:1000});assert.deepEqual(errors,[]);
  if(process.env.DSH_ADMIN_QA_OUTPUT){fs.mkdirSync(process.env.DSH_ADMIN_QA_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.DSH_ADMIN_QA_OUTPUT,'admin-dashboard.png'),fullPage:true});await page.locator('section').filter({has:page.getByRole('heading',{name:'DSH usage and activity',exact:true})}).screenshot({path:path.join(process.env.DSH_ADMIN_QA_OUTPUT,'admin-usage-fixture.png')});}
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
