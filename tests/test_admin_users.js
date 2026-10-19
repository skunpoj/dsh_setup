// Real HTTP gateway acceptance; only disposable identities, storage and backend.
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http');
const {spawn}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-users-'));
const port=39630,backendPort=39631;
const request=(method,route,body='',cookie='',headers={})=>new Promise((resolve,reject)=>{
 const r=http.request({host:'127.0.0.1',port,path:route,method,headers:{cookie,'Content-Type':'application/x-www-form-urlencoded',...headers}},res=>{let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,cookie:(res.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));});r.on('error',reject);r.end(body);
});
const login=async(user,password)=>(await request('POST','/login',new URLSearchParams({username:user,password,internet:'off'}).toString())).cookie;
let gateway,backend;
async function start(){gateway=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_USER_TARGETS_FILE:path.join(root,'targets.json'),DSH_ADMIN_SUMMARY_FILE:path.join(root,'summary.json'),DSH_COOKIE_SECURE:'false',DSH_TRUSTED_HOST:'127.0.0.1:'+port},stdio:'ignore'});for(let i=0;i<80;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,50));}}throw Error('Gateway did not start');}
async function stop(){const child=gateway;gateway=null;await new Promise(r=>{child.once('exit',r);child.kill();});}
(async()=>{try{
 fs.writeFileSync(path.join(root,'users.json'),JSON.stringify({admin:'synthetic-admin',alice:'synthetic-alice'}));
 const target={host:'127.0.0.1',port:backendPort,tokenFile:'/runtime-tokens/synthetic'};
 fs.writeFileSync(path.join(root,'targets.json'),JSON.stringify(Object.fromEntries(['admin','alice','bob','charlie','dana'].map(u=>[u,{secure:target,internet:target}]))));
 fs.writeFileSync(path.join(root,'summary.json'),JSON.stringify({observedAt:new Date().toISOString(),environments:[{name:'No Internet / Internal',ready:true,storage:'Private central workspace and history',network:'Public access blocked; approved internal services allowed'},{name:'Internet',ready:true,storage:'Separate private workspace and history',network:'Public dependency registries allowed'}],model:{backendContext:1048576,userContext:1048576,concurrencyCeiling:16},performance:['See the LLM setup guide for workload-specific measurements.'],gaps:[]}));
 backend=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<html><body>Isolated test backend</body></html>');});
 backend.on('upgrade',(req,socket)=>{socket.write('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');socket.on('data',()=>{});socket.on('error',()=>{});});
 await new Promise(r=>backend.listen(backendPort,'127.0.0.1',r));await start();
 let admin=await login('admin','synthetic-admin'),alice=await login('alice','synthetic-alice');assert(admin&&alice);
 assert.equal((await request('GET','/api/admin/users','',alice,{'x-dsh-role':'admin'})).status,403);
 const info=JSON.parse((await request('GET','/api/admin/users','',admin)).text);assert.equal(info.users.length,2);assert(info.provisionedIdentities.includes('bob'));assert(!JSON.stringify(info).includes('salt'));assert(!JSON.stringify(info).includes('hash'));assert(!JSON.stringify(info).includes('synthetic-admin'));
 const action=(action,user,password='',extra={})=>request('POST','/api/admin/users',new URLSearchParams({action,user,password}).toString(),admin,{'X-DSH-Admin-CSRF':info.csrfToken,...extra});
 assert.equal((await request('POST','/api/admin/users','action=disable&user=alice',admin)).status,403);
 assert.equal((await action('disable','alice','',{Origin:'https://evil.example'})).status,403);
 assert.equal((await action('disable','admin')).status,409);
 const internetLogin=(user,password)=>request('POST','/login',new URLSearchParams({username:user,password,internet:'on'}).toString());
 const permission=(user,password)=>request('POST','/api/login-environments',new URLSearchParams({username:user,password}).toString());
 assert.equal((await internetLogin('alice','synthetic-alice')).status,403);
 assert.equal(JSON.parse((await permission('alice','synthetic-alice')).text).internetAllowed,false);
 assert.equal(JSON.parse((await permission('admin','wrong')).text).internetAllowed,false);
 assert.equal(JSON.parse((await permission('admin','synthetic-admin')).text).internetAllowed,true);
 assert.equal((await internetLogin('admin','synthetic-admin')).status,302);
 assert.equal((await action('allow-internet','alice')).status,200);console.log('permission grant passed');
 assert.equal(JSON.parse((await permission('alice','synthetic-alice')).text).internetAllowed,true);
 const granted=await internetLogin('alice','synthetic-alice');assert.equal(granted.status,302);
 assert.equal((await request('POST','/api/admin/users','action=allow-internet&user=bob',alice)).status,403);
 assert.equal((await action('deny-internet','alice')).status,200);
 assert.equal((await internetLogin('alice','synthetic-alice')).status,403);
 assert((await request('GET','/api/auth/session','',granted.cookie)).text.includes('pane-login'));
 alice=await login('alice','synthetic-alice');

 assert.equal((await action('create','unprovisioned','long-test-password')).status,409);
 assert.equal((await action('create','bob','short')).status,400);
 assert.equal((await action('create','bob','long-synthetic-password')).status,200);
 assert.equal((await action('create','bob','long-synthetic-password')).status,409);
 assert(await login('bob','long-synthetic-password'));
 // An active upgraded terminal/application connection must close on revocation.
 let socket;let closed=false;
 const upgraded=new Promise((resolve,reject)=>{const r=http.request({host:'127.0.0.1',port,path:'/',headers:{cookie:alice,Connection:'Upgrade',Upgrade:'websocket'}});r.on('upgrade',(res,s)=>{socket=s;s.on('error',()=>{});s.on('close',()=>{closed=true;});s.resume();resolve();});r.on('error',reject);r.end();});await upgraded;
 assert.equal((await action('revoke','alice')).status,200);
 for(let i=0;i<30&&!closed;i++)await new Promise(r=>setTimeout(r,20));assert(closed,'Live upgraded connection remained open');
 assert((await request('GET','/api/auth/session','',alice)).text.includes('pane-login'));
 alice=await login('alice','synthetic-alice');assert(alice);
 assert.equal((await action('disable','alice')).status,200);assert.equal(await login('alice','synthetic-alice'),'');
 assert((await request('GET','/api/auth/session','',alice)).text.includes('pane-login'));
 assert.equal((await request('POST','/change-password','username=alice&old_password=synthetic-alice&new_password=changed-password')).status,401);
 const store=JSON.parse(fs.readFileSync(path.join(root,'users.json')));assert.equal(store.alice.disabled,true);assert.equal(store.bob.scheme,'scrypt-v1');assert(!fs.readFileSync(path.join(root,'users.json'),'utf8').includes('long-synthetic-password'));
 await stop();await start();assert.equal(await login('alice','synthetic-alice'),'');
 admin=await login('admin','synthetic-admin');const fresh=JSON.parse((await request('GET','/api/admin/users','',admin)).text);info.csrfToken=fresh.csrfToken;
 assert.equal((await action('enable','alice')).status,200);assert(await login('alice','synthetic-alice'));
 const audit=JSON.parse((await request('GET','/api/admin/audit','',admin)).text).events;
 for(const event of ['create','disable','enable','revoke'])assert(audit.some(r=>r.event==='account.'+event&&r.user==='admin'&&r.subject));
 const {chromium}=require(process.env.DSH_PLAYWRIGHT||'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}:{})});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1050}});

  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  console.log('browser selector start');await page.goto('http://127.0.0.1:'+port+'/login');assert(await page.locator('#internet-option').isDisabled());
  await page.fill('#login_username','alice');await page.fill('#login_password','synthetic-alice');await page.locator('#login_password').blur();await page.waitForTimeout(350);assert(await page.locator('#internet-option').isDisabled());
  await page.fill('#login_username','admin');await page.fill('#login_password','synthetic-admin');await page.locator('#login_password').blur();await page.waitForFunction(()=>!document.getElementById('internet-option').disabled,{},{timeout:5000});console.log('browser selector passed');
  await context.addCookies([{name:'dsh_auth',value:admin.split('=')[1],url:'http://127.0.0.1:'+port}]);
  await page.goto('http://127.0.0.1:'+port+'/admin');await page.waitForFunction(()=>document.querySelectorAll('#users tr').length===3);
  const row=page.locator('#users tr').filter({has:page.locator('td').filter({hasText:/^bob$/})});
  await row.getByRole('button',{name:'Disable',exact:true}).click();await page.waitForFunction(()=>document.getElementById('userMessage').textContent==='disable completed for bob.');
  assert.equal(await login('bob','long-synthetic-password'),'');
  await row.getByRole('button',{name:'Enable',exact:true}).click();await page.waitForFunction(()=>document.getElementById('userMessage').textContent==='enable completed for bob.');assert(await login('bob','long-synthetic-password'));
  await page.selectOption('#newUser','charlie');await page.fill('#newPassword','another-synthetic-password');await page.getByRole('button',{name:'Create account',exact:true}).click();await page.waitForFunction(()=>document.getElementById('userMessage').textContent==='create completed for charlie.');assert(await login('charlie','another-synthetic-password'));assert.equal(await page.locator('#newPassword').inputValue(),'');
  for(const width of [1440,760,390]){await page.setViewportSize({width,height:1050});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);}
  await page.setViewportSize({width:1440,height:1050});assert.deepEqual(errors,[]);
  if(process.env.DSH_ADMIN_QA_OUTPUT){fs.mkdirSync(process.env.DSH_ADMIN_QA_OUTPUT,{recursive:true});await page.screenshot({path:path.join(process.env.DSH_ADMIN_QA_OUTPUT,'admin-user-management.png'),fullPage:true});}
 } finally {await browser.close();}
  const evidence={passed:true,checks:['administrator-only list','no credential projection','CSRF and origin denial','protected admin roles','private-runtime prerequisite','hashed creation','duplicate refusal','active WebSocket closure','session revocation','disable denies login and password-change bypass','disabled state survives restart','enable restores login','actor and target audit','browser create/disable/enable','password field cleared','three responsive viewports']};
 console.log(JSON.stringify(evidence));
 }finally{if(gateway)await stop();if(backend){backend.closeAllConnections();await new Promise(r=>backend.close(r));}fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
