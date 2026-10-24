'use strict';
// A transport layer only: the original legacy gateway remains the sole auth writer.
const http=require('http'),crypto=require('crypto'),fs=require('fs'),path=require('path');
const {createController,page}=require('./jupyter_on_demand');
function read(cfg,route,cookie='',limit=16384){return new Promise(resolve=>{
 let done=false,timer;const finish=v=>{if(!done){done=true;clearTimeout(timer);resolve(v);}};
 const req=http.get({host:cfg.upstreamHost,port:cfg.upstreamPort,path:route,headers:{Host:cfg.publicHost,Cookie:cookie,Origin:'https://'+cfg.publicHost}},res=>{let size=0,chunks=[];res.on('data',b=>{size+=b.length;if(size>limit){req.destroy();finish({});}else chunks.push(b);});res.on('end',()=>finish({status:res.statusCode,type:res.headers['content-type']||'',body:Buffer.concat(chunks).toString()}));res.on('error',()=>finish({}));});req.setTimeout(3000,()=>req.destroy());req.on('error',()=>finish({}));
 timer=setTimeout(()=>{req.destroy();finish({});},3000);
});}
function settings(file){
 let fd;try{fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);const st=fs.fstatSync(fd);if(!st.isFile()||st.nlink!==1||st.size>16384)throw Error('control');const v=JSON.parse(fs.readFileSync(fd));if(typeof v.allowed!=='boolean'||!v.services||Array.isArray(v.services)||Object.keys(v.services).length>4)throw Error('control');return v;}finally{if(fd!==undefined)fs.closeSync(fd);}
}
function cookieIdentity(cookie,name){const values=String(cookie||'').split(';').map(v=>v.trim()).filter(v=>v.startsWith(name+'='));return values.length===1&&values[0].length<256?values[0]:null;}
function startTransport(cfg,ctx,{WebSocket=require(require.resolve('ws',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']})),launcher=fs.readFileSync(path.join(__dirname,'jupyter_launcher.py'),'utf8')}={}){
 return new Promise(async resolve=>{
  const failed=()=>resolve({state:'failed',code:'JUPYTER_START_FAILED'});
  if(!await ctx.check()||!ctx.allowed())return failed();
  const r=await read(cfg,'/proxy/7681/token',ctx.cookie,8192);let token;try{token=JSON.parse(r.body).token;}catch{}
  if(r.status!==200||typeof token!=='string'||token.length>4096||!await ctx.check()||!ctx.allowed())return failed();
  const nonce=crypto.randomBytes(16).toString('hex'),prefix='DSH_JUPYTER_START_'+nonce+':';
  const command=` unset HISTFILE; set +o history; /usr/bin/python3 -I -c 'import base64;exec(base64.b64decode("${Buffer.from(launcher).toString('base64')}"))' ${nonce}\r`;
  let ws,done=false,sent=false,output='';const finish=v=>{if(done)return;done=true;clearTimeout(timer);if(ws)try{ws.send('0exit\r');ws.close();}catch{ws.terminate();}resolve(v);};
  const timer=setTimeout(()=>finish({state:'starting'}),36000);
  try{
   ws=new WebSocket(`ws://${cfg.upstreamHost}:${cfg.upstreamPort}/proxy/7681/ws`,'tty',{headers:{Host:cfg.publicHost,Origin:'https://'+cfg.publicHost,Cookie:ctx.cookie},handshakeTimeout:4000});
   ws.on('open',async()=>{try{if(!await ctx.check()||!ctx.allowed())return finish({state:'failed',code:'SESSION_ENDED'});if(!done)ws.send(JSON.stringify({AuthToken:token,columns:120,rows:24}));}catch{finish({state:'failed'});}});
   ws.on('message',async b=>{try{b=Buffer.from(b);if(b[0]!==48||done)return;if(!sent){sent=true;if(!await ctx.check()||!ctx.allowed())return finish({state:'failed',code:'SESSION_ENDED'});if(!done)ws.send('0'+command);}output=(output+b.subarray(1).toString()).slice(-32768);const at=output.indexOf(prefix);if(at<0)return;try{const v=JSON.parse(output.slice(at+prefix.length).split(/[\r\n]/)[0]);if(['listening','starting','failed'].includes(v.state))finish({state:v.state});}catch{}}catch{finish({state:'failed'});}});
   ws.on('error',()=>finish({state:'failed',code:'TERMINAL_UNAVAILABLE'}));ws.on('close',()=>finish({state:'failed',code:'TERMINAL_UNAVAILABLE'}));
  }catch{finish({state:'failed',code:'TERMINAL_UNAVAILABLE'});}
 });
}
function validate(cfg){if(!/^[a-z0-9_.-]{3,30}$/.test(cfg.owner)||!/^[a-z0-9.-]+$/.test(cfg.publicHost)||!/^[a-z0-9.-]+$/.test(cfg.upstreamHost)||!Number.isInteger(cfg.upstreamPort)||cfg.upstreamPort<1024||cfg.upstreamPort>65535||!/^[a-zA-Z0-9_.-]{3,64}$/.test(cfg.cookieName)||!path.isAbsolute(cfg.controlFile))throw Error('Invalid fixed legacy gateway configuration');return cfg;}
function createGateway(config,{launch,clock=Date.now}={}){
 const cfg=validate(config),tokens=new Map();
 async function identity(cookie){const r=await read(cfg,'/api/auth/session',cookie);if(r.status!==200||!r.type.includes('application/json'))return null;try{const v=JSON.parse(r.body);return v.user===cfg.owner&&v.internet==='on'&&v.environment==='internet'?v:null;}catch{return null;}}
 function control(){return settings(cfg.controlFile);}
 const controller=createController({launch:launch|| (ctx=>startTransport(cfg,ctx)),probe:async ctx=>{if(!await ctx.check())return false;const r=await read(cfg,'/proxy/8888/lab',ctx.cookie,2097152);return r.status===200&&r.type.includes('text/html')&&r.body.includes('jupyter-config-data');}});
 async function context(req,create){
  const cookie=req.headers.cookie||'';if(Buffer.byteLength(cookie)>8192)return null;
  const authCookie=cookieIdentity(cookie,cfg.cookieName);if(!authCookie||!await identity(cookie))return null;
  for(const[k,v]of tokens)if(v.expires<=clock())tokens.delete(k);
  const key=crypto.createHash('sha256').update(authCookie).digest('hex');let row=tokens.get(key);
  if(!row&&create){if(tokens.size>=2048)return null;row={jupyterCsrf:crypto.randomBytes(32).toString('hex'),expires:clock()+120000};tokens.set(key,row);}
  if(!row)row={};let valid=true;
  const ctx={cookie,user:cfg.owner,mode:'on',target:{host:cfg.upstreamHost},trustedHost:cfg.publicHost,session:row,authorized:()=>valid&&(!row.expires||row.expires>clock()),allowed:()=>{try{const v=control();return v.allowed&&v.services.jupyter?.enabled!==false;}catch{return false;}},managed:()=>{try{return control().services.jupyter?.enabled===true;}catch{return false;}},audit:()=>{try{process.stdout.write(JSON.stringify({event:'jupyter.start',user:cfg.owner,environment:'internet',at:new Date().toISOString()})+'\n');return true;}catch{return false;}}};
  ctx.check=async()=>{if(!ctx.authorized())return false;valid=Boolean(await identity(cookie));return valid;};return ctx;
 }
 function forward(req,res){const up=http.request({host:cfg.upstreamHost,port:cfg.upstreamPort,path:req.url,method:req.method,headers:{...req.headers,host:cfg.publicHost,'x-forwarded-host':cfg.publicHost}},r=>{
  // Correct only the fixed login-page hint; never buffer workspace drafts/streams.
  if(req.method==='GET'&&new URL(req.url,'https://'+cfg.publicHost).pathname==='/login'&&r.statusCode===200&&(r.headers['content-type']||'').includes('text/html')&&!r.headers['content-encoding']){
   let chunks=[],size=0,streaming=false;r.on('data',b=>{if(streaming)return res.write(b);size+=b.length;chunks.push(b);if(size>262144){streaming=true;res.writeHead(r.statusCode,r.headers);for(const x of chunks)res.write(x);chunks=[];}});r.on('end',()=>{if(streaming)return res.end();const original=Buffer.concat(chunks),text=original.toString();const fixed=text.includes('login_username')?text.replace('If Jupyter is stopped, start it from Web Terminal with jupyter lab.','If Jupyter is stopped, opening Jupyter starts it automatically. Existing servers and kernels are reused.'):text;const body=Buffer.from(fixed),headers={...r.headers,'content-length':body.length};delete headers['transfer-encoding'];res.writeHead(r.statusCode,headers);res.end(body);});r.on('error',()=>res.destroy());return;
  }
  res.writeHead(r.statusCode,r.headers);r.pipe(res);
 });up.on('error',()=>{if(!res.headersSent){res.writeHead(502,{'Content-Type':'text/plain','Cache-Control':'no-store'});res.end('The existing DSH gateway is unavailable.');}else res.destroy();});req.on('aborted',()=>up.destroy());res.on('close',()=>up.destroy());req.pipe(up);}
 const server=http.createServer(async(req,res)=>{try{
  if(req.url==='/_jupyter_gateway/health'){const r=await read(cfg,'/login','',262144);const healthy=r.status===200&&r.type.includes('text/html')&&r.body.includes('login_username');res.writeHead(healthy?200:503,{'Content-Type':'application/json','Cache-Control':'no-store'});return res.end(JSON.stringify({upstreamLoginReachable:healthy}));}
  if(req.headers.host!==cfg.publicHost||!req.url.startsWith('/')||req.url.startsWith('//')){res.writeHead(421);return res.end('Unexpected gateway host or request path.');}
  const route=new URL(req.url,'https://'+cfg.publicHost).pathname;
  if(route==='/logout'){const key=cookieIdentity(req.headers.cookie,cfg.cookieName);if(key)tokens.delete(crypto.createHash('sha256').update(key).digest('hex'));return forward(req,res);}
  const navigation=req.method==='GET'&&(route==='/jupyter'||route==='/jupyter/start'||/^\/proxy\/(?:8888|jupyter)\/(?:lab(?:\/|$)|$)/.test(route));
  if(route==='/api/jupyter/start'||navigation){const ctx=await context(req,navigation);if(!ctx){if(route==='/api/jupyter/start'){res.writeHead(401,{'Content-Type':'application/json','Cache-Control':'no-store'});return res.end(JSON.stringify({error:'AUTHENTICATION_REQUIRED'}));}return forward(req,res);}
   if(route==='/api/jupyter/start'){await controller.start(req,res,ctx);return;}
   if(route==='/jupyter/start'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Frame-Options':'DENY','Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"});return res.end(page(ctx.session.jupyterCsrf,'/proxy/8888/lab'));}
   if(await controller.navigation(req,res,ctx,'/proxy/8888/lab'))return;
  }
  forward(req,res);
 }catch{if(!res.headersSent){res.writeHead(503,{'Content-Type':'text/plain','Cache-Control':'no-store'});res.end('Jupyter startup is temporarily unavailable.');}else res.destroy();}});
 server.on('upgrade',(req,socket,head)=>{if(req.headers.host!==cfg.publicHost){socket.end('HTTP/1.1 421 Misdirected Request\r\nConnection: close\r\n\r\n');return;}const up=http.request({host:cfg.upstreamHost,port:cfg.upstreamPort,path:req.url,method:'GET',headers:{...req.headers,host:cfg.publicHost,'x-forwarded-host':cfg.publicHost}});up.on('upgrade',(res,remote,remoteHead)=>{socket.write('HTTP/1.1 101 Switching Protocols\r\n'+res.rawHeaders.reduce((s,v,i)=>s+(i%2?v+'\r\n':v+': '),'')+'\r\n');if(remoteHead.length)socket.write(remoteHead);if(head.length)remote.write(head);remote.on('error',()=>socket.destroy());socket.on('error',()=>remote.destroy());remote.on('close',()=>socket.destroy());socket.on('close',()=>remote.destroy());remote.pipe(socket);socket.pipe(remote);});up.on('response',res=>{socket.end('HTTP/1.1 '+res.statusCode+' Upstream refused\r\nConnection: close\r\n\r\n');res.resume();});up.on('error',()=>socket.destroy());socket.on('error',()=>up.destroy());socket.on('close',()=>up.destroy());up.end();});
 return server;
}
if(require.main===module){const server=createGateway({owner:process.env.DSH_LEGACY_OWNER,publicHost:process.env.DSH_TRUSTED_HOST,upstreamHost:process.env.DSH_LEGACY_UPSTREAM,upstreamPort:Number(process.env.DSH_LEGACY_PORT||3080),cookieName:process.env.DSH_COOKIE_NAME,controlFile:process.env.DSH_SERVICE_CONTROL||'/control/config.json'});server.listen(Number(process.env.PORT||3080),'0.0.0.0');}
module.exports={createGateway,validate,cookieIdentity,settings,startTransport};
