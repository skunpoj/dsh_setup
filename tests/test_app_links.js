'use strict';
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http');
const {spawn}=require('child_process');const {hashPassword}=require('../scripts/password_store');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-app-links-')),port=39470,backendPort=39471,appPort=39472;
const services=path.join(root,'services');fs.mkdirSync(services);for(const mode of ['off','on']){const key=require('crypto').createHash('sha256').update('127.0.0.1|'+mode).digest('hex').slice(0,24);const dir=path.join(services,key);fs.mkdirSync(dir);fs.writeFileSync(path.join(dir,'ready'),'qualified');fs.writeFileSync(path.join(dir,'config.json'),JSON.stringify({allowed:true,services:{}}));}
const users=path.join(root,'users.json'),token=path.join(root,'token');fs.writeFileSync(token,'synthetic');
const inventory=path.join(root,'inventory.json');const snapshot=()=>fs.writeFileSync(inventory,JSON.stringify({domain:'apps.test.local',observedAt:new Date().toISOString(),reservedNames:['occupied'],wildcardReady:true}));snapshot();
fs.writeFileSync(users,JSON.stringify({admin:hashPassword('synthetic-password'),alice:{...hashPassword('synthetic-password'),internetAllowed:true},bob:hashPassword('synthetic-password')}));
const backend=http.createServer((q,r)=>{if(q.url.startsWith('/?token=')){r.writeHead(302,{'set-cookie':'dsh-backend=synthetic'});return r.end();}r.end('dsh-backend');});
const app=http.createServer((q,r)=>{if(q.url==='/hold'){r.writeHead(200);r.write('stream-open');return;}r.end(JSON.stringify({url:q.url,user:q.headers['x-dsh-user'],mode:q.headers['x-dsh-internet-access']}));});
app.on('upgrade',(q,s)=>s.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nX-Test-User: '+q.headers['x-dsh-user']+'\r\n\r\n'));
function upgrade(cookie){return new Promise((resolve,reject)=>{const socket=require('net').connect(port,'127.0.0.1');let text='';const timer=setTimeout(()=>{socket.destroy();reject(Error('upgrade timeout'));},3000);socket.on('connect',()=>socket.write('GET /proxy/alice-demo/ws HTTP/1.1\r\nHost: dsh.test.local\r\nCookie: '+cookie+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nOrigin: https://dsh.test.local\r\nX-DSH-User: forged\r\n\r\n'));socket.on('data',b=>{text+=b.toString();if(text.includes('\r\n\r\n')){clearTimeout(timer);socket.destroy();resolve(text);}});socket.on('close',()=>{clearTimeout(timer);resolve(text);});socket.on('error',e=>{clearTimeout(timer);reject(e)});});}
let gateway;function start(){gateway=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,DSH_APP_SERVICES_ROOT:services,DSH_USER_STORE_PATH:users,DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_TRUSTED_HOST:'dsh.test.local',DSH_APP_DOMAIN:'apps.test.local',DSH_APP_INVENTORY_FILE:inventory,DSH_COOKIE_SECURE:'false',DSH_OFFLINE_HOST:'127.0.0.1',DSH_ONLINE_HOST:'127.0.0.1',DSH_OFFLINE_PORT:String(backendPort),DSH_ONLINE_PORT:String(backendPort),DSH_OFFLINE_TOKEN_FILE:token,DSH_ONLINE_TOKEN_FILE:token},stdio:'ignore'});}
function request(method,url,body='',cookie='',headers={}){return new Promise((resolve,reject)=>{const q=http.request({host:'127.0.0.1',port,method,path:url,headers:{host:'dsh.test.local',cookie,'content-type':'application/x-www-form-urlencoded',...headers}},r=>{let text='';r.on('data',c=>text+=c);r.on('end',()=>resolve({status:r.statusCode,text,headers:r.headers}));});q.on('error',reject);q.end(body);});}
async function ready(){for(let i=0;i<100;i++){try{await request('GET','/login');return;}catch{await new Promise(r=>setTimeout(r,50));}}throw Error('Gateway not ready');}
async function login(user,mode='off'){const r=await request('POST','/login',new URLSearchParams({username:user,password:'synthetic-password',internet:mode}).toString());assert.equal(r.status,302);return r.headers['set-cookie'][0].split(';')[0];}
async function info(cookie){const r=await request('GET','/api/app-links','',cookie);assert.equal(r.status,200);return JSON.parse(r.text);}
async function change(cookie,csrf,name,value,action='save',origin='https://dsh.test.local'){return request('POST','/api/app-links',new URLSearchParams({action,name,port:value}).toString(),cookie,{'X-DSH-App-CSRF':csrf,Origin:origin});}
async function adminInfo(cookie){const r=await request('GET','/api/admin/apps','',cookie);assert.equal(r.status,200);return JSON.parse(r.text);}
async function adminChange(cookie,token,fields,origin='https://dsh.test.local'){return request('POST','/api/admin/apps',new URLSearchParams(fields).toString(),cookie,{'X-DSH-Admin-CSRF':token,Origin:origin});}
async function heldHttp(cookie){return new Promise((resolve,reject)=>{const q=http.get({host:'127.0.0.1',port,path:'/proxy/alice-demo/hold',headers:{Host:'dsh.test.local',cookie}},r=>r.once('data',()=>resolve(r)));q.once('error',reject);});}
async function heldUpgrade(cookie){return new Promise((resolve,reject)=>{const socket=require('net').connect(port,'127.0.0.1');const timer=setTimeout(()=>{socket.destroy();reject(Error('upgrade timeout'));},3000);socket.once('error',reject);socket.once('data',b=>{clearTimeout(timer);assert(b.toString().includes('101 Switching'));resolve(socket);});socket.once('connect',()=>socket.write('GET /proxy/alice-demo/ws HTTP/1.1\r\nHost: dsh.test.local\r\nCookie: '+cookie+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nOrigin: https://dsh.test.local\r\n\r\n'));});}
async function stop(){await new Promise(resolve=>{gateway.once('exit',resolve);gateway.kill();});}
(async()=>{await Promise.all([new Promise(r=>backend.listen(backendPort,'127.0.0.1',r)),new Promise(r=>app.listen(appPort,'127.0.0.1',r))]);try{
 start();await ready();assert.equal((await request('GET','/api/app-links')).status,401);
 const a=await login('alice'),b=await login('bob'),ai=await info(a),bi=await info(b);assert.equal(ai.defaultName,'alice-jupyter');assert.equal(ai.hostnameDomain,'apps.test.local');
 assert.equal((await change(a,ai.csrfToken,'occupied',appPort)).status,409);
 assert.equal(JSON.parse((await request('GET','/api/app-links?name=occupied','',a)).text).available,false);
 for(const name of ['8501','__proto__','dsh-8000','../escape'])assert.equal((await change(a,ai.csrfToken,name,appPort)).status,400);
 assert.equal((await change(a,'bad','alice-notebook',8888)).status,403);
 assert.equal((await change(a,ai.csrfToken,'alice-notebook',8888,'save','https://evil.test')).status,403);
 for(const value of [3080,3081,4000,4001,22,0,65536])assert.equal((await change(a,ai.csrfToken,'alice-notebook',value)).status,400);
 assert.equal((await change(a,ai.csrfToken,'alice-notebook',8888)).status,200);
 assert.equal((await change(b,bi.csrfToken,'alice-notebook',appPort)).status,409);
 assert.equal(JSON.parse((await request('GET','/api/app-links?name=alice-notebook','',b)).text).available,false);
 assert.equal((await request('GET','/proxy/alice-notebook/lab','',b)).status,404);
 assert.equal((await request('GET','/proxy/alice-notebook/lab','',a)).headers.location,'/proxy/8888/lab');
 assert.equal((await request('GET','/','',b,{Host:'alice-notebook.apps.test.local'})).status,404);
 assert.equal((await request('GET','/','',a,{Host:'alice-notebook.apps.test.local'})).headers.location,'https://dsh.test.local/proxy/8888/lab');
 assert.equal((await change(a,ai.csrfToken,'alice-demo',appPort)).status,200);
 for(const target of ['/login','/applications','/terminal'])assert.equal((await request('GET',target,'',a,{Host:'alice-demo.apps.test.local'})).headers.location,'https://dsh.test.local'+target);
 for(const [application,target] of [['dsh','/'],['terminal','/terminal'],['jupyter','/proxy/8888/lab']]) {
  const reply=await request('POST','/login',new URLSearchParams({username:'alice',password:'synthetic-password',application}).toString(),'',{Host:'alice-demo.apps.test.local'});
  assert.equal(reply.headers.location,'https://dsh.test.local'+target);
 }
 const page=await request('GET','/applications','',a);assert(page.text.includes('id="check" disabled'));assert(page.text.includes('id="saveApp" disabled'));

 assert((await upgrade(a)).includes('X-Test-User: alice'));assert(!(await upgrade(b)).includes('101 Switching'));
 for(const [url,headers] of [['/proxy/alice-demo/hello?x=1',{}],['/hello?x=1',{Host:'alice-demo.apps.test.local'}]]){const r=await request('GET',url,'',a,headers);assert.equal(r.status,200);assert.deepEqual(JSON.parse(r.text),{url:'/hello?x=1',user:'alice',mode:'off'});}
 const admin=await login('admin'),initial=await adminInfo(admin),csrf=initial.csrfToken;
 assert.equal(initial.defaultLimit,8);assert.equal((await info(a)).limit,8);
 assert.equal((await request('GET','/api/admin/apps','',b)).status,403);
 assert.equal((await adminChange(b,csrf,{action:'limit',user:'bob',limit:'12'})).status,403);
 assert.equal((await adminChange(admin,'bad',{action:'limit',user:'alice',limit:'12'})).status,403);
 assert.equal((await adminChange(admin,csrf,{action:'limit',user:'alice',limit:'12'},'https://hostile.test')).status,403);
 for(const value of ['-1','1.5','NaN','4097','1e2',''])assert.equal((await adminChange(admin,csrf,{action:'limit',user:'alice',limit:value})).status,400);
 for(let n=0;n<6;n++)assert.equal((await change(a,ai.csrfToken,'alice-quota-'+n,appPort)).status,200);
 assert.equal((await change(a,ai.csrfToken,'alice-over-limit',appPort)).status,409);
 assert.equal((await adminChange(admin,csrf,{action:'limit',user:'alice',limit:'12'})).status,200);
 assert.equal((await change(a,ai.csrfToken,'alice-over-limit',appPort)).status,200);
 assert.equal((await adminChange(admin,csrf,{action:'limit',user:'alice',limit:'1'})).status,200);
 assert.equal((await info(a)).links.length,9);assert.equal((await info(a)).limit,1);
 assert.equal((await change(a,ai.csrfToken,'alice-demo',appPort)).status,200);
 assert.equal((await change(a,ai.csrfToken,'alice-another',appPort)).status,409);
 assert.equal((await adminChange(admin,csrf,{action:'limit',user:'bob',limit:'0'})).status,200);
 assert.equal((await change(b,bi.csrfToken,'bob-new',appPort)).status,409);
 const stream=await heldHttp(a);const streamClosed=new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('disabled HTTP stream remained open')),3000);stream.once('close',()=>{clearTimeout(t);resolve();});});
 const held=await heldUpgrade(a);const closed=new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error('disabled WebSocket remained open')),3000);held.once('close',()=>{clearTimeout(t);resolve();});});
 assert.equal((await adminChange(admin,csrf,{action:'disable',user:'alice',name:'alice-demo'})).status,200);await Promise.all([closed,streamClosed]);
 for(const [route,headers]of [['/proxy/alice-demo/',{}],['/',{Host:'alice-demo.apps.test.local'}]])assert.equal((await request('GET',route,'',a,headers)).status,404);
 assert(!(await upgrade(a)).includes('101 Switching'));
 assert.equal((await change(a,ai.csrfToken,'alice-demo',appPort)).status,200);assert.equal((await request('GET','/proxy/alice-demo/','',a)).status,404);
 assert.equal((await adminChange(admin,csrf,{action:'enable',user:'alice',name:'alice-demo'})).status,200);
 assert.equal((await adminChange(admin,csrf,{action:'edit',user:'bob',name:'alice-demo',environment:'off',port:String(backendPort)})).status,404);
 assert.equal((await adminChange(admin,csrf,{action:'edit',user:'alice',name:'alice-demo',environment:'off',port:'4000'})).status,400);
 assert.equal((await adminChange(admin,csrf,{action:'edit',user:'alice',name:'alice-demo',environment:'off',port:String(backendPort)})).status,200);
 assert.equal((await request('GET','/proxy/alice-demo/','',a)).text,'dsh-backend');
 assert.equal((await request('GET','/proxy/alice-demo/','',admin)).status,404);
 assert.equal((await adminChange(admin,csrf,{action:'edit',user:'alice',name:'alice-demo',environment:'off',port:String(appPort)})).status,200);
 const audit=JSON.parse((await request('GET','/api/admin/audit','',admin)).text).events;
 assert(audit.some(e=>e.event==='application.limit'&&e.application?.limit===12&&e.application.outcome==='applied'));
 assert(audit.some(e=>e.event==='application.edit'&&e.application?.previousPort===appPort));
 for(const e of audit)assert(!JSON.stringify(e).includes('synthetic-password'));
 for(const name of [...Array.from({length:6},(_,n)=>'alice-quota-'+n),'alice-over-limit'])assert.equal((await adminChange(admin,csrf,{action:'delete',user:'alice',name})).status,200);
 assert.equal((await adminChange(admin,csrf,{action:'disable',user:'alice',name:'alice-notebook'})).status,200);
 const on=await login('alice','on');assert.equal((await request('GET','/proxy/alice-demo/','',on)).status,404);
 fs.writeFileSync(inventory,JSON.stringify({domain:'apps.test.local',observedAt:'2000-01-01T00:00:00Z',reservedNames:[],wildcardReady:true}));
 assert.equal((await change(a,ai.csrfToken,'stale-new',appPort)).status,503);
 assert.equal((await request('GET','/','',a,{Host:'alice-demo.apps.test.local'})).status,404);
 assert.equal((await request('GET','/proxy/alice-demo/','',a)).status,200);snapshot();
 await stop();start();await ready();const anew=await login('alice');assert.equal((await info(anew)).links.length,2);assert.equal((await info(anew)).limit,1);assert.equal((await request('GET','/proxy/alice-notebook/lab','',anew)).status,404);
 const fresh=await info(anew);assert.equal((await change(anew,fresh.csrfToken,'alice-demo',appPort,'delete')).status,200);assert.equal((await info(anew)).links.length,1);
 const adminAgain=await login('admin');const policyFile=path.join(root,'app-policy.json'),policyBytes=fs.readFileSync(policyFile);fs.writeFileSync(policyFile,'not-json');assert.equal((await request('GET','/api/admin/apps','',adminAgain)).status,503);fs.writeFileSync(policyFile,policyBytes);
 const appFile=path.join(root,'app-links.json'),appBytes=fs.readFileSync(appFile);fs.writeFileSync(appFile,'not-json');assert.equal((await request('GET','/api/admin/apps','',adminAgain)).status,503);fs.writeFileSync(appFile,appBytes);
 const managed=await adminInfo(adminAgain),serviceFields={action:'service-save',user:'alice',environment:'off',service:'jupyter',kind:'jupyter',cwd:'/workspace'};
 assert.equal((await adminChange(adminAgain,managed.csrfToken,serviceFields)).status,200);
 assert.equal((await adminChange(adminAgain,managed.csrfToken,{...serviceFields,action:'service-start'})).status,200);
 let row=(await adminInfo(adminAgain)).managedServices.find(r=>r.user==='alice'&&r.mode==='off');assert(row.services.find(s=>s.name==='jupyter').enabled);
 assert.equal((await adminChange(adminAgain,managed.csrfToken,{...serviceFields,action:'service-stop'})).status,200);
 row=(await adminInfo(adminAgain)).managedServices.find(r=>r.user==='alice'&&r.mode==='off');assert.equal(row.services[0].enabled,false);
 const statusDir=path.join(services,require('crypto').createHash('sha256').update('127.0.0.1|off').digest('hex').slice(0,24),'status');fs.mkdirSync(statusDir,{recursive:true});fs.writeFileSync(path.join(statusDir,'status.json'),'x'.repeat(70000));assert.equal((await adminInfo(adminAgain)).managedServices.find(r=>r.user==='alice'&&r.mode==='off').services[0].phase,'unknown');

 for(const cwd of ['/root','/workspace/../root'])assert.equal((await adminChange(adminAgain,managed.csrfToken,{...serviceFields,cwd})).status,400);
 assert.equal((await adminChange(await login('bob'),bi.csrfToken,serviceFields)).status,403);
 assert.equal((await adminChange(adminAgain,'bad',serviceFields)).status,403);
 assert.equal((await adminChange(adminAgain,managed.csrfToken,{...serviceFields,action:'service-delete'})).status,200);
 console.log('Admin app inventory, editable per-user limits, quota boundaries, preserved over-limit mappings, port edits, revocation, audit, role/CSRF checks and persistence passed.');
 console.log('App URLs: owned aliases, collision checks, exact port forwarding, approved hostname routing, Jupyter canonical URL, CSRF, management-port denial, environment separation and restart persistence passed.');
 }finally{if(gateway?.exitCode===null)await stop();backend.close();app.close();fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
