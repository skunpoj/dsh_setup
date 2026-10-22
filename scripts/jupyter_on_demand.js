'use strict';
const http=require('http'),crypto=require('crypto'),fs=require('fs'),path=require('path');
const HEADERS={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY'};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function sessionAuthorized(active,sessions,stamp,ttlMs,now=Date.now()){
 return Boolean(active&&active.accountStamp===stamp&&Number.isSafeInteger(active.created)&&active.created+ttlMs>now&&[...sessions.values()].includes(active));
}

function request(host,port,route,headers,limit=2097152,timeout=2500){
 return new Promise(resolve=>{
  let done=false;const finish=v=>{if(!done){done=true;resolve(v);}};
  const r=http.get({host,port,path:route,headers},s=>{
   let size=0,chunks=[];s.on('data',b=>{size+=b.length;if(size>limit){r.destroy();finish({state:'unavailable'});}else chunks.push(b);});
   s.on('end',()=>finish({status:s.statusCode,body:Buffer.concat(chunks).toString('utf8'),type:s.headers['content-type']||''}));
   s.on('error',()=>finish({state:'unavailable'}));
  });r.setTimeout(timeout,()=>r.destroy());r.on('error',()=>finish({state:'unavailable'}));
 });
}
function destination(value){
 try{const u=new URL(value,'https://dsh.invalid');if(u.origin==='https://dsh.invalid'&&/^\/proxy\/8888\/lab(?:\/|$)/.test(u.pathname))return u.pathname+u.search+u.hash;}catch{}
 return '/proxy/8888/lab';
}
function page(token,next){
 const data=JSON.stringify({token,next:destination(next)}).replaceAll('<','\\u003c');
 return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Starting Jupyter</title><style>body{font:17px system-ui;background:#0b1220;color:#eef;max-width:640px;margin:12vh auto;padding:24px}button,a{font:inherit;color:#8cf}button{background:#172033;padding:10px;border:1px solid #567;border-radius:6px}</style><h1>Starting Jupyter…</h1><p id="status" role="status">Opening Jupyter in your selected private workspace. Existing notebooks and running kernels are kept.</p><button id="retry" hidden>Try again</button> <a href="/">Back to DSH</a><script>(()=>{const data=${data},status=document.getElementById('status'),retry=document.getElementById('retry');async function start(){retry.hidden=true;status.textContent='Starting Jupyter in your selected workspace…';try{const r=await fetch('/api/jupyter/start',{method:'POST',credentials:'same-origin',headers:{'X-DSH-Jupyter-CSRF':data.token}});const v=await r.json();if(r.status===401){status.textContent='Your sign-in session ended. Sign in again, then reopen Jupyter.';return;}if(!r.ok||v.state!=='ready')throw Error(v.message||'Jupyter is still starting. Try again shortly.');location.replace(data.next);}catch(e){status.textContent=e.message||'Jupyter could not start. Try again or contact the administrator.';retry.hidden=false;}}retry.onclick=start;start();})();</script></html>`;
}
function loadWebSocket(){return require(require.resolve('ws',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));}
function terminalLaunch(ctx,{WebSocket=loadWebSocket(),launcher=fs.readFileSync(path.join(__dirname,'jupyter_launcher.py'),'utf8')}={}){
 return new Promise(async resolve=>{
  const authorized=()=>ctx.authorized()&&(!ctx.allowed||ctx.allowed());
  const fail=()=>resolve({state:'failed',code:'JUPYTER_START_FAILED'});
  if(!authorized())return fail();
  const token=await request(ctx.target.host,7681,'/token',{Host:ctx.trustedHost},8192,3000);
  let auth='';try{auth=JSON.parse(token.body).token||'';}catch{}
  if(typeof auth!=='string'||auth.length>4096||!authorized())return fail();
  const nonce=crypto.randomBytes(16).toString('hex'),prefix='DSH_JUPYTER_START_'+nonce+':';
  const encoded=Buffer.from(launcher).toString('base64');
  // All executable text is fixed. Only a generated hex nonce is appended.
  const command=` unset HISTFILE; set +o history; /usr/bin/python3 -I -c 'import base64;exec(base64.b64decode("${encoded}"))' ${nonce}\r`;
  let ws,done=false,sent=false,text='';
  const finish=value=>{if(done)return;done=true;clearTimeout(timer);if(ws){try{ws.send('0exit\r');ws.close();}catch{ws.terminate();}}resolve(value);};
  const timer=setTimeout(()=>finish({state:'starting'}),36000);
  try{
   ws=new WebSocket('ws://'+ctx.target.host+':7681/ws','tty',{headers:{Host:ctx.trustedHost,Origin:'https://'+ctx.trustedHost},handshakeTimeout:4000});
   ws.on('open',()=>{if(!authorized())return finish({state:'failed',code:'SESSION_ENDED'});ws.send(JSON.stringify({AuthToken:auth,columns:120,rows:24}));});
   ws.on('message',data=>{
    data=Buffer.from(data);if(data[0]!==48)return;
    if(!sent){if(!authorized())return finish({state:'failed',code:'SESSION_ENDED'});sent=true;ws.send('0'+command);}
    text=(text+data.subarray(1).toString()).slice(-32768);
    const at=text.indexOf(prefix);if(at<0)return;
    const line=text.slice(at+prefix.length).split(/[\r\n]/)[0];
    try{const v=JSON.parse(line);if(['listening','starting','failed'].includes(v.state))finish({state:v.state});}catch{}
   });
   ws.on('error',()=>finish({state:'failed',code:'TERMINAL_UNAVAILABLE'}));
   ws.on('close',()=>{if(!done)finish({state:'failed',code:'TERMINAL_UNAVAILABLE'});});
  }catch{finish({state:'failed',code:'TERMINAL_UNAVAILABLE'});}
 });
}
function createController({probe,launch,clock=Date.now,sleep=delay}={}){
 const inFlight=new Map();
 probe=probe|| (async ctx=>{
  const r=await request(ctx.target.host,8888,'/lab',{'Host':'127.0.0.1:8888','X-DSH-User':ctx.user,'X-DSH-Internet':ctx.mode,'X-Forwarded-Host':ctx.trustedHost,'X-Forwarded-Proto':'https'});
  return r.status===200&&r.type.includes('text/html')&&r.body.includes('jupyter-config-data');
 });
 launch=launch||terminalLaunch;
 function valid(ctx){return ctx&&/^[a-z0-9_.-]{1,30}$/.test(ctx.user)&&['off','on'].includes(ctx.mode)&&ctx.target&&/^[a-zA-Z0-9.-]+$/.test(ctx.target.host)&&typeof ctx.authorized==='function'&&ctx.authorized();}
 async function ensure(ctx){
  if(!valid(ctx))return {state:'failed',code:'ACCESS_DENIED'};
  const key=ctx.target.host+'|'+ctx.mode;
  if(inFlight.has(key))return inFlight.get(key);
  const job=(async()=>{
   if(await probe(ctx))return {state:'ready',reused:true};
   if(!ctx.authorized())return {state:'failed',code:'SESSION_ENDED'};
   if(ctx.allowed&&!ctx.allowed())return {state:'failed',code:'START_DISABLED'};
   const started=ctx.managed&&ctx.managed()?{state:'starting'}:await launch(ctx);
   if(started.state==='failed')return {state:'failed',code:started.code||'JUPYTER_START_FAILED'};
   const end=clock()+8000;
   do{if(!ctx.authorized())return {state:'failed',code:'SESSION_ENDED'};if(await probe(ctx))return {state:'ready',reused:false};await sleep(300);}while(clock()<end);
   return {state:'starting',code:'JUPYTER_NOT_READY'};
  })();
  inFlight.set(key,job);try{return await job;}finally{if(inFlight.get(key)===job)inFlight.delete(key);}
 }
 async function navigation(req,res,ctx,next){
  if(await probe(ctx))return false;
  if(!ctx.authorized()){res.writeHead(401,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:'AUTHENTICATION_REQUIRED'}));return true;}
  ctx.session.jupyterCsrf ||=crypto.randomBytes(32).toString('hex');
  const body=page(ctx.session.jupyterCsrf,next);
  res.writeHead(200,{...HEADERS,'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"});res.end(body);return true;
 }
 async function start(req,res,ctx){
  const reply=(status,value)=>{if(!res.destroyed){res.writeHead(status,{...HEADERS,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(value));}};
  if(req.method!=='POST')return reply(405,{error:'METHOD_NOT_ALLOWED'});
  const token=req.headers['x-dsh-jupyter-csrf'],expected=ctx.session.jupyterCsrf;
  if(req.headers.origin!=='https://'+ctx.trustedHost||typeof expected!=='string'||typeof token!=='string'||!/^[a-f0-9]{64}$/.test(token)||!/^[a-f0-9]{64}$/.test(expected)||!crypto.timingSafeEqual(Buffer.from(token),Buffer.from(expected)))return reply(403,{error:'INVALID_START_TOKEN'});
  // No user-supplied command, environment, target, cwd or body is accepted.
  if(req.headers['transfer-encoding']||Number(req.headers['content-length']||0)!==0)return reply(400,{error:'START_BODY_NOT_ALLOWED'});
  if(!valid(ctx))return reply(403,{error:'ACCESS_DENIED'});
  if(ctx.allowed&&!ctx.allowed())return reply(403,{error:'START_DISABLED',message:'Jupyter startup is disabled for this workspace. Contact the administrator.'});
  if(ctx.audit&&!ctx.audit())return reply(503,{error:'AUDIT_UNAVAILABLE'});
  try{
   const value=await ensure(ctx);
   if(!ctx.authorized())return reply(401,{error:'AUTHENTICATION_REQUIRED'});
   if(value.state==='ready')return reply(200,value);
   return reply(503,{...value,message:value.state==='starting'?'Jupyter is still starting. Try again shortly.':'Jupyter could not start. Try again or contact the administrator.'});
  }catch{return reply(503,{state:'failed',message:'Jupyter could not start. Try again or contact the administrator.'});}
 }
 return {ensure,navigation,start,probe};
}
module.exports={createController,terminalLaunch,destination,page,sessionAuthorized};
