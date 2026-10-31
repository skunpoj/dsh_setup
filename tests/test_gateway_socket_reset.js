// Actual authenticated upgrade/reset lifecycle against synthetic loopback peers.
const assert=require('assert'),fs=require('fs'),os=require('os'),path=require('path');
const http=require('http'),net=require('net'),{spawn}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-socket-reset-'));
const held=new Set();let gateway,stderr='';
const backend=http.createServer((req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify({user:req.headers['x-dsh-user']}));});
backend.on('upgrade',(req,socket)=>{held.add(socket);socket.on('error',()=>socket.destroy());socket.on('end',()=>socket.destroy());socket.on('close',()=>held.delete(socket));socket.resume();socket.write('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');});
async function freePort(){const server=net.createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const port=server.address().port;await new Promise(r=>server.close(r));return port;}
function request(port,method,route,body='',cookie=''){
 return new Promise((resolve,reject)=>{const q=http.request({host:'127.0.0.1',port,method,path:route,headers:{Host:'dsh.test.local',Cookie:cookie,'Content-Type':'application/x-www-form-urlencoded','Content-Length':Buffer.byteLength(body)}},r=>{let text='';r.on('data',b=>text+=b);r.on('end',()=>resolve({status:r.statusCode,text,cookie:r.headers['set-cookie']?.[0]?.split(';')[0]}));});q.on('error',reject);q.setTimeout(3000,()=>q.destroy(new Error('Fixture request deadline')));q.end(body);});
}
function resetUpgrade(port,route,cookie){
 return new Promise((resolve,reject)=>{let response='';const s=net.connect(port,'127.0.0.1',()=>s.write(`GET ${route} HTTP/1.1\r\nHost: dsh.test.local\r\nOrigin: http://dsh.test.local\r\nCookie: ${cookie}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n`));s.setTimeout(5000,()=>s.destroy(new Error('Upgrade deadline')));s.on('error',reject);s.on('data',b=>{response+=b;if(response.includes('\r\n\r\n')){assert(response.startsWith('HTTP/1.1 101'));s.resetAndDestroy();}});s.on('close',()=>resolve());});
}
(async()=>{
 fs.writeFileSync(path.join(root,'users.json'),JSON.stringify({alice:'synthetic-reset-password'}));
 await new Promise(r=>backend.listen(0,'127.0.0.1',r));const backendPort=backend.address().port,gatewayPort=await freePort();
 gateway=spawn(process.execPath,[process.env.DSH_SOCKET_GATEWAY_SOURCE||path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(gatewayPort),WORKSPACE_ROOT:root,DSH_AUTH_PASS:'',DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_OFFLINE_HOST:'127.0.0.1',DSH_OFFLINE_PORT:String(backendPort),DSH_ONLINE_PORT:String(backendPort),DSH_TRUSTED_HOST:'dsh.test.local',DSH_COOKIE_SECURE:'false'},stdio:['ignore','pipe','pipe']});
 gateway.stdout.resume();gateway.stderr.on('data',b=>stderr+=b);
 try{
  let ready=false;for(let i=0;i<80;i++){try{await request(gatewayPort,'GET','/login');ready=true;break;}catch{await new Promise(r=>setTimeout(r,40));}}assert(ready);
  const login=await request(gatewayPort,'POST','/login','username=alice&password=synthetic-reset-password&internet=off');assert.equal(login.status,302);assert(login.cookie);
  for(const route of ['/socket',`/proxy/${backendPort}/socket`]){
   await resetUpgrade(gatewayPort,route,login.cookie);await new Promise(r=>setTimeout(r,150));
   assert.equal(gateway.exitCode,null,'Gateway exited after client reset: '+stderr.slice(-600));
   assert.equal(held.size,0,'Disconnected peer retained an upstream WebSocket');
   const after=await request(gatewayPort,'GET','/identity','',login.cookie);assert.equal(after.status,200);assert.equal(JSON.parse(after.text).user,'alice');
  }
  console.log(JSON.stringify({passed:true,actualTCPReset:true,authenticatedUpgradeRoutes:2,sameProcessAndLoginCookieRetained:true,productionRequests:0}));
 }finally{
  if(gateway.exitCode===null){gateway.kill();await new Promise(r=>gateway.once('exit',r));}
  for(const socket of held)socket.destroy();await new Promise(r=>backend.close(r));
  assert(root.startsWith(path.join(os.tmpdir(),'dsh-socket-reset-')));fs.rmSync(root,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
