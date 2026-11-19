'use strict';
const http=require('http'),crypto=require('crypto'),CONFIRM=require('./agent_task_confirm');
// Private server-context selection; never enabled by HTTP fields.
const BANKING_CONFIRMATIONS=new WeakMap();
const HEADERS={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY'};

// Claude Code runs with --output-format stream-json, so each output line is a JSON event. Show the answer, not the JSON:
// assistant text, tool names, and the final result only when no assistant text came through. Other runtimes print text.
// Embedded verbatim in the page script (no backticks or template placeholders allowed in this function).
function renderTaskOutput(runtime,text,state){
 if(typeof text!=='string')return '';
 if(runtime!=='claude')return text;
 const line=text.trim();
 if(line.charAt(0)!=='{')return text;
 let row;try{row=JSON.parse(line);}catch(error){return text;}
 if(!row||typeof row!=='object')return text;
 if(row.type==='assistant'&&row.message&&Array.isArray(row.message.content)){
  let out='';
  for(const part of row.message.content){
   if(part&&part.type==='text'&&typeof part.text==='string'&&part.text){out+=part.text;state.answered=true;}
   else if(part&&part.type==='tool_use'&&typeof part.name==='string')out+=(out&&!out.endsWith('\n')?'\n':'')+'[tool: '+part.name+']\n';
  }
  return out&&!out.endsWith('\n')?out+'\n':out;
 }
 if(row.type==='result'){
  if(row.is_error===true)return '\n[error: '+String(typeof row.result==='string'&&row.result?row.result:row.subtype||'failed').slice(0,2000)+']\n';
  if(!state.answered&&typeof row.result==='string'&&row.result){state.answered=true;return row.result+'\n';}
  return '';
 }
 return '';
}

function page(token){const data=JSON.stringify({token}).replaceAll('<','\\u003c');return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Managed agent tasks</title><style>body{font:16px/1.55 system-ui;max-width:920px;margin:28px auto;padding:20px;background:#f4f7fb;color:#13283d}main{background:white;padding:28px;border-radius:14px}label{display:block;margin:12px 0}input,select,textarea,button{font:inherit;padding:9px}textarea{width:100%;min-height:110px;box-sizing:border-box}button{margin-right:8px}.pending{color:#8a4b08}pre{white-space:pre-wrap;background:#071522;color:#e7f2ff;padding:16px;min-height:140px;max-height:420px;overflow:auto}</style></head><body><main><nav><a href="/">DSH</a> · <a href="/terminal">Web Terminal</a> · <a href="/manual/AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html">Guide</a></nav><h1>Managed agent task</h1><p>Choose the runtime separately from its execution backend. A bounded optional handoff lets one agent pass its captured result to a different agent through the same authenticated broker and guard.</p><form id="task"><label>Agent runtime <select id="runtime"><option value="sdk">DSH Python SDK</option><option value="claude">Claude Code</option><option value="deepagents">Deep Agents</option><option value="kilo">Kilo</option></select></label><label>Execution backend <select id="backend"><option value="private">Private DSH workspace</option><option value="openshell" disabled>OpenShell isolated workspace — qualification pending</option></select></label><label>Project below /workspace <input id="project" value="." required maxlength="512"></label><label><input id="writes" type="checkbox"> Allow workspace edits for this task</label><label>Task <textarea id="prompt" maxlength="65536" required></textarea></label><label>Optional handoff to <select id="handoff"><option value="">No handoff</option><option value="sdk">DSH Python SDK</option><option value="claude">Claude Code</option><option value="deepagents">Deep Agents</option><option value="kilo">Kilo</option></select></label><label>Handoff instruction <textarea id="handoffPrompt" maxlength="65536">Review the previous agent result and produce the final checked answer.</textarea></label><label><input id="approved" type="checkbox" required> I approve this runtime, optional handoff, project, backend and write mode for this task.</label><button id="start">Start task</button><button type="button" id="approve" disabled>Approve paused SDK action</button><button type="button" id="reject" disabled>Reject SDK action</button><button type="button" id="cancel" disabled>Cancel</button></form><p id="status" role="status"></p><pre id="output" aria-live="polite"></pre><script>(()=>{const d=${data},q=id=>document.getElementById(id),status=q('status'),out=q('output');const renderOutput=${renderTaskOutput.toString()};let renderState={};let task=null,cursor=0,timer=null,nativeTicket=null;async function api(path,options={}){options.credentials='same-origin';options.headers={...(options.headers||{}),'X-DSH-Agent-CSRF':d.token};if(options.body)options.headers['Content-Type']='application/json';const r=await fetch(path,options),v=await r.json();if(!r.ok)throw Error(v.error||'Task request failed');return v}async function poll(){if(!task)return;let v=null;try{v=await api('/api/agent-tasks/'+task+'/events?after='+cursor);cursor=v.next;nativeTicket=v.nativeApproval||null;for(const e of v.events){if(e.type==='output'){const rt=e.data.runtime||'';out.textContent+=renderOutput(rt,e.data.text,renderState[rt]||(renderState[rt]={}));}else if(e.type==='handoff')status.textContent='Handing off '+e.data.from+' → '+e.data.to;else status.textContent='Task '+e.data.state;}out.scrollTop=out.scrollHeight;q('approve').disabled=v.state!=='awaiting_approval'||Boolean(nativeTicket&&!nativeTicket.allowOnceAdmitted);q('approve').textContent=nativeTicket?'Allow SDK action once':'Approve paused SDK action';q('reject').disabled=!nativeTicket;if(nativeTicket)status.textContent='SDK decision required: '+nativeTicket.toolName;if(['completed','failed','cancelled','interrupted'].includes(v.state)&&!v.more){q('start').disabled=false;q('approve').disabled=true;q('reject').disabled=true;q('cancel').disabled=true;nativeTicket=null;task=null;return}}catch(e){status.textContent=e.message;timer=setTimeout(poll,700);return}timer=setTimeout(poll,v&&v.more?0:700)}q('task').onsubmit=async e=>{e.preventDefault();q('start').disabled=true;out.textContent='';renderState={};status.textContent='Submitting approved task…';try{const body={runtime:q('runtime').value,backend:q('backend').value,project:q('project').value,prompt:q('prompt').value,writes:q('writes').checked,approved:q('approved').checked};if(q('handoff').value){body.handoffRuntime=q('handoff').value;body.handoffPrompt=q('handoffPrompt').value}const v=await api('/api/agent-tasks',{method:'POST',body:JSON.stringify(body)});task=v.taskId;cursor=0;q('cancel').disabled=false;poll()}catch(e){q('start').disabled=false;status.textContent=e.message}};q('approve').onclick=async()=>{if(!task)return;try{await api('/api/agent-tasks/'+task+'/approve',{method:'POST',body:JSON.stringify(nativeTicket?{approvalId:nativeTicket.approvalId,generation:nativeTicket.generation,outcome:'allowed-once'}:{approved:true})});q('approve').disabled=true;q('reject').disabled=true;status.textContent='SDK decision sent'}catch(e){status.textContent=e.message}};q('reject').onclick=async()=>{if(!task||!nativeTicket)return;try{await api('/api/agent-tasks/'+task+'/approve',{method:'POST',body:JSON.stringify({approvalId:nativeTicket.approvalId,generation:nativeTicket.generation,outcome:'rejected'})});q('approve').disabled=true;q('reject').disabled=true;status.textContent='SDK action rejected'}catch(e){status.textContent=e.message}};q('cancel').onclick=async()=>{if(!task)return;try{await api('/api/agent-tasks/'+task,{method:'DELETE'});status.textContent='Cancellation requested'}catch(e){status.textContent=e.message}};api('/api/agent-tasks/capabilities').then(v=>{const o=[...q('backend').options].find(x=>x.value==='openshell'),c=v.backends.find(x=>x.id==='openshell');if(c){o.disabled=!c.enabled;o.textContent=c.enabled?'OpenShell isolated workspace':'OpenShell unavailable — '+c.reason}const sdk=v.runtimeDetails&&v.runtimeDetails.sdk;if(sdk){const r=[...q('runtime').options].find(x=>x.value==='sdk');if(r){r.disabled=!sdk.enabled;r.textContent=sdk.enabled?'DSH Python SDK - official native':'DSH Python SDK unavailable - '+sdk.reason}const h=[...q('handoff').options].find(x=>x.value==='sdk');if(h){h.disabled=!sdk.handoffEnabled;if(h.disabled)h.textContent='SDK handoff - qualification pending'}if(r&&r.disabled&&q('runtime').value==='sdk'){const first=[...q('runtime').options].find(x=>!x.disabled);if(first)q('runtime').value=first.value}const update=()=>{const blocked=q('runtime').value==='sdk'&&!sdk.handoffEnabled;q('handoff').disabled=blocked;if(blocked)q('handoff').value=''};q('runtime').onchange=update;update()}}).catch(e=>status.textContent=e.message)})();</script></main></body></html>`;}

function collect(req,limit=131072){return new Promise((resolve,reject)=>{let size=0,chunks=[];req.on('data',b=>{size+=b.length;if(size>limit){reject(Object.assign(Error('REQUEST_TOO_LARGE'),{status:413}));req.destroy();}else chunks.push(b)});req.on('end',()=>resolve(Buffer.concat(chunks)));req.on('error',reject);});}
function proxy(req,res,ctx,body){return new Promise(resolve=>{const headers={'Authorization':'Bearer '+ctx.token,'Accept':'application/json','X-DSH-Subject':ctx.user};if(body.length){headers['Content-Type']='application/json';headers['Content-Length']=body.length;}const upstream=http.request({host:ctx.target.host,port:7682,path:ctx.upstreamPath,method:req.method,headers,timeout:10000},reply=>{res.writeHead(reply.statusCode,{...HEADERS,'Content-Type':'application/json; charset=utf-8'});reply.pipe(res);reply.on('end',resolve)});upstream.on('timeout',()=>upstream.destroy());upstream.on('error',()=>{if(!res.headersSent){res.writeHead(503,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:'TASK_BROKER_UNAVAILABLE'}));}resolve()});if(body.length)upstream.write(body);upstream.end();});}
// One JSON call to the workspace broker (loopback of the workspace pod, runtime token, session subject). Used where the gateway
// must read an answer itself instead of piping it: the confirmation flow reads the proposal it is about to sign for.
function brokerJson(ctx,method,path,body,subject=ctx.user){return new Promise(resolve=>{
 const payload=body===undefined?null:Buffer.from(JSON.stringify(body));
 const headers={'Authorization':'Bearer '+ctx.token,'Accept':'application/json','X-DSH-Subject':subject};
 if(payload){headers['Content-Type']='application/json';headers['Content-Length']=payload.length;}
 const upstream=http.request({host:ctx.target.host,port:7682,path,method,headers,timeout:10000},reply=>{let text='';reply.setEncoding('utf8');reply.on('data',c=>{if(text.length<1048576)text+=c});
  reply.on('end',()=>{let json=null;try{json=JSON.parse(text)}catch{}resolve({status:reply.statusCode,json})})});
 upstream.on('timeout',()=>upstream.destroy());upstream.on('error',()=>resolve({status:503,json:{error:'TASK_BROKER_UNAVAILABLE'}}));
 if(payload)upstream.write(payload);upstream.end();});}
const send=(res,status,value)=>{res.writeHead(status,{...HEADERS,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(value));return true;};
// What the browser may show: the proposal as the broker holds it, nothing else (no subject, no receipt material).
const VIEW=['id','state','runtime','project','writes','backend','prompt','promptSha256','origin','createdAt','expiresAt','taskId','error'];
const view=item=>Object.fromEntries(VIEW.filter(k=>item&&item[k]!==undefined).map(k=>[k,item[k]]));
async function confirmProposal(req,res,ctx,id){
 let shown;try{shown=JSON.parse((await collect(req,4096)).toString('utf8'));}catch{return send(res,400,{error:'INVALID_REQUEST'});}
 if(!shown||typeof shown.promptSha256!=='string'||!/^[a-f0-9]{64}$/.test(shown.promptSha256))return send(res,400,{error:'INVALID_REQUEST'});
 if(!CONFIRM.available())return send(res,503,{error:'CONFIRMATION_KEY_UNAVAILABLE'});
 const current=await brokerJson(ctx,'GET','/v1/proposals/'+id);
 if(current.status!==200||!current.json)return send(res,current.status===404?404:503,{error:current.status===404?'PROPOSAL_NOT_FOUND':'TASK_BROKER_UNAVAILABLE'});
 const made=CONFIRM.buildReceipt(current.json,ctx.user,shown);
 if(made.error)return send(res,made.status,{error:made.error});
 let answer;
 const factory=BANKING_CONFIRMATIONS.get(ctx);
 if(factory){
  try{
   const adapter=await factory({serverContext:ctx,originalBrokerConfirm:async q=>{
    if(q.subject!==ctx.user||q.proposalId!==id||JSON.stringify(q.receipt)!==JSON.stringify(made.receipt))throw Error('EXISTING_CONFIRMATION_CHANGED');
    const actual=await brokerJson(ctx,'POST','/v1/tasks/'+id+'/confirm',made.receipt);
    return {status:actual.status,body:actual.json};
   }});
   if(!adapter||typeof adapter.confirm!=='function')throw Error();
   const result=await adapter.confirm({serverContext:ctx,proposal:current.json,receipt:made.receipt});
   if(result?.state!=='accepted'||result.proposalId!==id||!/^[a-f0-9]{32}$/.test(result.taskId))throw Error();
   answer={status:202,json:{id,state:'approved',taskId:result.taskId}};
  }catch{return send(res,503,{error:'BANKING_CONFIRMATION_UNKNOWN_NO_RETRY'});}
 }else answer=await brokerJson(ctx,'POST','/v1/tasks/'+id+'/confirm',made.receipt);
 if(ctx.audit)ctx.audit(answer.status===202?'agent-task.confirmed':'agent-task.confirm-refused',{taskId:id,runtime:made.receipt.runtime,writes:made.receipt.writes,promptSha256:made.receipt.promptSha256,status:answer.status});
 return send(res,answer.status,answer.json||{error:'TASK_BROKER_UNAVAILABLE'});
}
function safeEqual(a,b){return typeof a==='string'&&typeof b==='string'&&/^[a-f0-9]{64}$/.test(a)&&/^[a-f0-9]{64}$/.test(b)&&crypto.timingSafeEqual(Buffer.from(a),Buffer.from(b));}
async function handle(req,res,ctx){
 const pathname=ctx.pathname;
 if(pathname==='/agent-tasks'){
  if(!ctx.authorized()){res.writeHead(401,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:'AUTHENTICATION_REQUIRED'}));return true;}
  if(req.method!=='GET'){res.writeHead(405,{...HEADERS,Allow:'GET'});res.end();return true;}
  ctx.session.agentCsrf ||= crypto.randomBytes(32).toString('hex');
  const body=page(ctx.session.agentCsrf);res.writeHead(200,{...HEADERS,'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"});res.end(body);return true;
 }
 if(!pathname.startsWith('/api/agent-tasks'))return false;
 if(!ctx.authorized()){res.writeHead(401,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:'AUTHENTICATION_REQUIRED'}));return true;}
 if(pathname==='/api/agent-tasks/csrf'&&req.method==='GET'){
  // Lets the small card on every page learn the per-session token. Same-origin reads only: a cross-site page cannot read this answer,
  // and a browser that says the request is cross-site is refused outright.
  const site=req.headers['sec-fetch-site'];if(site&&site!=='same-origin')return send(res,403,{error:'SAME_ORIGIN_REQUIRED'});
  ctx.session.agentCsrf ||= crypto.randomBytes(32).toString('hex');return send(res,200,{token:ctx.session.agentCsrf});
 }
 if(!safeEqual(req.headers['x-dsh-agent-csrf'],ctx.session.agentCsrf)){res.writeHead(403,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:'INVALID_TASK_TOKEN'}));return true;}
 if(['POST','DELETE'].includes(req.method)&&req.headers.origin!=='https://'+ctx.trustedHost){res.writeHead(403,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:'SAME_ORIGIN_REQUIRED'}));return true;}
 const suffix=pathname.slice('/api/agent-tasks'.length);
 if(suffix==='/capabilities'&&req.method==='GET')ctx.upstreamPath='/v1/capabilities';
 else if(suffix===''&&req.method==='POST'){if(BANKING_CONFIRMATIONS.has(ctx))return send(res,403,{error:'BANKING_SIGNED_CONFIRMATION_REQUIRED'});ctx.upstreamPath='/v1/tasks';}
 else if(suffix==='/proposed'&&req.method==='GET'){
  const listed=await brokerJson(ctx,'GET','/v1/tasks?state=proposed');
  if(listed.status!==200||!listed.json)return send(res,503,{error:'TASK_BROKER_UNAVAILABLE'});
  return send(res,200,{proposals:(listed.json.proposals||[]).map(view),signing:CONFIRM.available()});
 }
 else if(/^\/[a-f0-9]{32}\/confirm$/.test(suffix)&&req.method==='POST')return confirmProposal(req,res,ctx,suffix.slice(1,33));
 else if(/^\/[a-f0-9]{32}\/deny$/.test(suffix)&&req.method==='POST'){const gone=await brokerJson(ctx,'DELETE','/v1/tasks/'+suffix.slice(1,33));
  if(ctx.audit&&gone.status<300)ctx.audit('agent-task.denied',{taskId:suffix.slice(1,33)});return send(res,gone.status,gone.json||{error:'TASK_BROKER_UNAVAILABLE'});}
 else if(/^\/[a-f0-9]{32}\/approve$/.test(suffix)&&req.method==='POST')ctx.upstreamPath='/v1/tasks'+suffix;
 else if(/^\/[a-f0-9]{32}\/events$/.test(suffix)&&req.method==='GET')ctx.upstreamPath='/v1/tasks'+suffix+(ctx.query||'');
 else if(/^\/[a-f0-9]{32}$/.test(suffix)&&req.method==='DELETE')ctx.upstreamPath='/v1/tasks'+suffix;
 else{res.writeHead(404,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:'NOT_FOUND'}));return true;}
 let body=Buffer.alloc(0);try{if(req.method==='POST')body=await collect(req);}catch(error){res.writeHead(error.status||400,{...HEADERS,'Content-Type':'application/json'});res.end(JSON.stringify({error:error.message}));return true;}
 await proxy(req,res,ctx,body);return true;
}
function createBankingGateway({confirmationFactory}){
 if(typeof confirmationFactory!=='function')throw Error('BOUND_BANKING_CONFIRMATION_FACTORY_REQUIRED');
 return Object.freeze({async handle(req,res,ctx){
  const ownedContext={...ctx};BANKING_CONFIRMATIONS.set(ownedContext,confirmationFactory);
  try{return await handle(req,res,ownedContext);}finally{BANKING_CONFIRMATIONS.delete(ownedContext);}
 }});
}
module.exports={handle,page,renderTaskOutput,createBankingGateway};
