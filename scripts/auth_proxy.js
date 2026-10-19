const http = require('http');
const url = require('url');
const fs = require('fs');
const crypto = require('crypto');
const { hashPassword, verifyPassword, migrateUsers, writeAtomicUsers } = require('./password_store');

const PROXY_PORT = Number(process.env.PORT || 3080);
// Kubernetes may inject DSH_PORT=tcp://<service-ip>:3080 for the Service named
// "dsh". Accept only an explicitly numeric port and otherwise use the internal
// DSH web port, avoiding an invalid 127.0.0.1:NaN proxy target.
const requestedDshPort = process.env.DSH_TARGET_PORT || process.env.DSH_PORT || '';
const DSH_TARGET_PORT = /^\d+$/.test(requestedDshPort) ? Number(requestedDshPort) : 3081;
const DSH_TARGET_HOST = process.env.DSH_HOST || '127.0.0.1';
const USER_ROOT = process.env.WORKSPACE_ROOT || '/workspace/users';
const USER_STORE_PATH = process.env.DSH_USER_STORE_PATH || `${USER_ROOT}/.user_auth.json`;
const USER_SETTINGS_PATH = process.env.DSH_USER_SETTINGS_PATH || `${USER_ROOT}/.user_settings.json`;
const COOKIE_NAME = process.env.DSH_COOKIE_NAME || 'dsh_auth';
const COOKIE_TRANSPORT = process.env.DSH_COOKIE_SECURE === 'false' ? '' : '; Secure';
const ADMIN_USERS = new Set((process.env.DSH_ADMIN_USERS || 'admin').split(',').map(x => x.trim()).filter(Boolean));
const ADMIN_SUMMARY_FILE = process.env.DSH_ADMIN_SUMMARY_FILE || '/admin-status/summary.json';
const AUDIT_DIR = process.env.DSH_AUDIT_DIR || `${USER_ROOT}/audit`;
let auditFailures = 0;
function auditEvent(event, actor, mode, subject) {
  try {
    fs.mkdirSync(AUDIT_DIR, { recursive: true, mode: 0o700 });
    const file = `${AUDIT_DIR}/events.jsonl`;
    if (fs.existsSync(file) && fs.statSync(file).size >= 5 * 1024 * 1024) {
      // Preserve old records; stop rather than silently delete an audit archive.
      if (fs.existsSync(`${AUDIT_DIR}/events.5.jsonl`)) throw new Error('Audit retention capacity reached');
      for (let i = 4; i >= 1; i--) if (fs.existsSync(`${AUDIT_DIR}/events.${i}.jsonl`)) fs.renameSync(`${AUDIT_DIR}/events.${i}.jsonl`, `${AUDIT_DIR}/events.${i+1}.jsonl`);
      fs.renameSync(file, `${AUDIT_DIR}/events.1.jsonl`);
    }
    const user = typeof actor === 'string' && /^[a-zA-Z0-9_.-]{1,30}$/.test(actor) ? actor : 'unidentified';
    fs.appendFileSync(file, JSON.stringify({ time: new Date().toISOString(), event, user,
      environment: normalizeInternetMode(mode) === 'on' ? 'internet' : 'secure',
      ...(subject && /^[a-z0-9_.-]{3,30}$/.test(subject) ? {subject} : {}) }) + '\n', { mode: 0o600 });
    return true;
  } catch { auditFailures++; console.error('[AUDIT] Could not persist security event'); return false; }
}
function recentAudit() {
  const events = new Set(['login.success','login.denied','logout','runtime.http','admin.denied','terminal.open','application.websocket','account.create','account.enable','account.disable','account.revoke','account.allow-internet','account.deny-internet']);
  const rows=[];
  for(const file of [`${AUDIT_DIR}/events.jsonl`,`${AUDIT_DIR}/legacy/legacy-dsh2/events.jsonl`,`${AUDIT_DIR}/legacy/legacy-dsh3/events.jsonl`]) {
    try {
      if(fs.statSync(file).size > 8*1024*1024) continue;
      for(const line of fs.readFileSync(file,'utf8').split('\n')) {
        try {
          const r=JSON.parse(line);
          if(!events.has(r.event)||typeof r.time!=='string'||!Number.isFinite(Date.parse(r.time))||! /^[a-zA-Z0-9_.-]{1,30}$/.test(r.user)||!['secure','internet','legacy-dsh2/internet','legacy-dsh3/internet'].includes(r.environment)) continue;
          rows.push({time:r.time,event:r.event,user:r.user,environment:r.environment,
            ...(r.event.startsWith('account.') && typeof r.subject === 'string' && /^[a-z0-9_.-]{3,30}$/.test(r.subject) ? {subject:r.subject} : {})});
        } catch {}
      }
    } catch {}
  }
  return rows.sort((a,b)=>Date.parse(a.time)-Date.parse(b.time)).slice(-100);
}
function legacyAuditStatus() {
  const instances=[];
  for(const name of ['legacy-dsh2','legacy-dsh3']) {
    try {
      const v=JSON.parse(fs.readFileSync(`${AUDIT_DIR}/legacy/${name}/status.json`,'utf8'));
      const r=(v.instances||[]).find(row=>row.name===name);
      if(r&&typeof v.observedAt==='string'&&Number.isFinite(Date.parse(v.observedAt))) instances.push({name,events:Math.max(0,Math.min(1000,Number(r.events)||0)),observedAt:v.observedAt});
    } catch {}
  }
  return {observedAt:instances.length?instances.map(r=>r.observedAt).sort()[0]:null,instances};
}

// BEGIN ADMIN TELEMETRY: expose numeric projections, never conversation bodies.
let telemetryCache = null, telemetryPending = null;
const telemetryCookies = new Map();
function metricInteger(value) { return Number.isSafeInteger(value) && value >= 0 ? value : 0; }
function metricDuration(value) { return typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=Number.MAX_SAFE_INTEGER?value:0; }
function projectSessionMetrics(items, user, environment) {
  if (!Array.isArray(items) || items.length > 2000) throw new Error('Runtime summary exceeds its bound');
  const row = {user, environment, available:true, sessions:items.length, runningAgents:0, queuedMessages:0,
    turns:0, llmSteps:0, inputTokens:0, outputTokens:0, decodeTokens:0, decodeMs:0, usageSessions:0};
  const counters = new Map();
  for (const item of items) {
    const values = item?.projections?.values || {}, usage = values.tokenUsage, stats = values.sessionStats || {};
    row.runningAgents += item?.running === true ? 1 : 0;
    row.queuedMessages += ['next-turn','next-step'].reduce((n,k)=>n+(Array.isArray(values.inbox?.[k])?values.inbox[k].length:0),0);
    row.turns += metricInteger(stats.turns); row.llmSteps += metricInteger(stats.steps);
    row.decodeTokens += metricInteger(stats.decodeTokens); row.decodeMs += metricDuration(stats.decodeMs);
    if (usage && typeof usage === 'object' && ['uncachedInputTokens','cacheReadTokens','cacheWriteTokens','outputTokens'].every(k=>Number.isSafeInteger(usage[k])&&usage[k]>=0)) {
      row.usageSessions++;
      row.inputTokens += metricInteger(usage.uncachedInputTokens)+metricInteger(usage.cacheReadTokens)+metricInteger(usage.cacheWriteTokens);
      row.outputTokens += metricInteger(usage.outputTokens);
      if(typeof item.sessionId==='string' && item.sessionId.length<=128) counters.set(user+'\0'+environment+'\0'+item.sessionId,{
        output:metricInteger(usage.outputTokens), decodeTokens:metricInteger(stats.decodeTokens),decodeMs:metricDuration(stats.decodeMs),
        lastPromptAt:metricInteger(values.sessionListMetadata?.lastPromptAt)});
    }
  }
  for(const value of Object.values(row)) if(typeof value==='number'&&(!Number.isFinite(value)||value<0||value>Number.MAX_SAFE_INTEGER))throw new Error('Runtime counter overflow');
  row.recordedDecodeTokensPerSecond = row.decodeMs ? Math.round(row.decodeTokens*100000/row.decodeMs)/100 : null;
  return {row,counters};
}
function telemetryRequest(target, host, method, route, cookie='', body='', limit=8*1024*1024) {
  return new Promise((resolve,reject)=>{
    let settled=false, bytes=0;const chunks=[];
    const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(deadline);error?reject(error):resolve(value);};
    const request=http.request({host:target.host,port:target.port,path:route,method,
      headers:{Host:host,Origin:'http://'+host,Cookie:cookie,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},response=>{
      response.on('data',chunk=>{bytes+=chunk.length;if(bytes>limit){request.destroy();finish(new Error('Runtime summary exceeds its bound'));}else chunks.push(chunk);});
      response.on('error',()=>finish(new Error('Runtime unavailable')));
      response.on('end',()=>finish(null,{status:response.statusCode,headers:response.headers,body:Buffer.concat(chunks).toString('utf8')}));
    });
    const deadline=setTimeout(()=>{request.destroy();finish(new Error('Runtime unavailable'));},4000);
    request.on('error',()=>finish(new Error('Runtime unavailable')));request.end(body);
  });
}
async function runtimeTelemetry(target,user,environment) {
  const host=process.env.DSH_TRUSTED_HOST || 'localhost';
  const token=getDshToken(target.tokenFile);if(!token)throw new Error('Runtime authentication unavailable');
  const key=target.host+':'+target.port+'|'+target.tokenFile;
  const fingerprint=crypto.createHash('sha256').update(token).digest('hex');
  let cached=telemetryCookies.get(key);
  if(!cached || cached.fingerprint!==fingerprint){
    const auth=await telemetryRequest(target,host,'GET','/?token='+encodeURIComponent(token),'','',65536);
    const cookie=(auth.headers['set-cookie']||[]).find(x=>x.startsWith('dsh-auth-'))?.split(';')[0];
    if(!cookie)throw new Error('Runtime authentication unavailable');
    cached={fingerprint,cookie};telemetryCookies.set(key,cached);
  }
  const response=await telemetryRequest(target,host,'POST','/api/session/list',cached.cookie,JSON.stringify({
    type:'client-request',rpcId:crypto.randomUUID(),method:'session/list',payload:{args:{_request:{}}}}));
  if(response.status!==200){telemetryCookies.delete(key);throw new Error('Runtime summary unavailable');}
  let data;try{data=JSON.parse(response.body);}catch{telemetryCookies.delete(key);throw new Error('Runtime summary unavailable');}
  if(!data?.result?.ok){telemetryCookies.delete(key);throw new Error('Runtime summary unavailable');}
  return projectSessionMetrics(data.result.value.items,user,environment);
}
function capacityProjection() {
  try {
    const file=process.env.DSH_ADMIN_CAPACITY_FILE || `${AUDIT_DIR}/capacity.json`;
    if(fs.statSync(file).size>256*1024)return null;
    const data=JSON.parse(fs.readFileSync(file,'utf8'));
    if(typeof data.observedAt!=='string'||!Number.isFinite(Date.parse(data.observedAt))||!Array.isArray(data.runtimes))return null;
    return {observedAt:data.observedAt,runtimes:data.runtimes.slice(0,128).filter(r=>
      typeof r.user==='string'&&/^[a-z0-9_.-]{3,30}$/.test(r.user)&&['secure','internet'].includes(r.environment))
      .map(r=>({user:r.user,environment:r.environment,workspaceFileBytes:Number.isSafeInteger(r.workspaceFileBytes)&&r.workspaceFileBytes>=0?r.workspaceFileBytes:null,
        workspaceScanComplete:r.workspaceScanComplete===true,
        durableStateFileBytes:Number.isSafeInteger(r.durableStateFileBytes)&&r.durableStateFileBytes>=0?r.durableStateFileBytes:null,
        durableStateScanComplete:r.durableStateScanComplete===true,
        stateUsedBytes:Number.isSafeInteger(r.stateUsedBytes)&&r.stateUsedBytes>=0?r.stateUsedBytes:null,
        stateCapacityBytes:Number.isSafeInteger(r.stateCapacityBytes)&&r.stateCapacityBytes>=0?r.stateCapacityBytes:null}))};
  }catch{return null;}
}
async function adminTelemetry() {
  if(telemetryCache && Date.now()-telemetryCache.sampledAt<15000)return {...telemetryCache.public,storage:capacityProjection()};
  if(telemetryPending)return telemetryPending;
  telemetryPending=(async()=>{
    const targets=USER_TARGETS ? Object.entries(USER_TARGETS).flatMap(([user,environments])=>
      Object.entries(environments).filter(([environment])=>['secure','internet'].includes(environment)).map(([environment,target])=>({user,environment,target}))) : [];
    if(targets.length>128)throw new Error('Too many provisioned runtime targets');
    const samples=new Array(targets.length);let cursor=0;
    await Promise.all(Array.from({length:Math.min(4,targets.length)},async()=>{
      while(cursor<targets.length){const index=cursor++,item=targets[index];
        try{samples[index]=await runtimeTelemetry(item.target,item.user,item.environment);}
        catch{samples[index]={row:{user:item.user,environment:item.environment,available:false},counters:new Map()};}
      }
    }));
    const sampledAt=Date.now(),counters=new Map(),totals={sessions:0,runningAgents:0,queuedMessages:0,turns:0,llmSteps:0,inputTokens:0,outputTokens:0,decodeTokens:0,decodeMs:0,usageSessions:0};
    const counterValue=(row,key)=>key==='decodeMs'?metricDuration(row[key]):metricInteger(row[key]);
    for(const sample of samples){
      if(Object.keys(totals).some(key=>!Number.isFinite(totals[key]+counterValue(sample.row,key))||totals[key]+counterValue(sample.row,key)>Number.MAX_SAFE_INTEGER)){
        sample.row={user:sample.row.user,environment:sample.row.environment,available:false};sample.counters.clear();continue;
      }
      for(const key of Object.keys(totals))totals[key]+=counterValue(sample.row,key);for(const [key,value]of sample.counters)counters.set(key,value);
    }
    for(const value of Object.values(totals))if(!Number.isFinite(value)||value<0||value>Number.MAX_SAFE_INTEGER)throw new Error('Aggregate counter overflow');
    const complete=samples.every(x=>x.row.available),previous=telemetryCache;let outputRate=null,recentDecodeRate=null;
    if(complete && previous?.complete && sampledAt>previous.sampledAt){
      let delta=0,decodeTokens=0,decodeMs=0,reset=false;
      for(const key of previous.counters.keys())if(!counters.has(key))reset=true;
      for(const [key,value]of counters){const old=previous.counters.get(key);
        if(old){if(value.output<old.output||value.decodeTokens<old.decodeTokens||value.decodeMs<old.decodeMs)reset=true;
          else {delta+=value.output-old.output;decodeTokens+=value.decodeTokens-old.decodeTokens;decodeMs+=value.decodeMs-old.decodeMs;}}
        else if(value.lastPromptAt>previous.sampledAt){delta+=value.output;decodeTokens+=value.decodeTokens;decodeMs+=value.decodeMs;}
      }
      if(!reset){outputRate=Math.round(delta*100000/(sampledAt-previous.sampledAt))/100;
        recentDecodeRate=decodeMs?Math.round(decodeTokens*100000/decodeMs)/100:null;}
    }
    const result={observedAt:new Date(sampledAt).toISOString(),sampleWindowSeconds:previous?(sampledAt-previous.sampledAt)/1000:null,
      configuredRuntimes:targets.length,availableRuntimes:samples.filter(x=>x.row.available).length,
      totals:{...totals,recordedDecodeTokensPerSecond:totals.decodeMs?Math.round(totals.decodeTokens*100000/totals.decodeMs)/100:null,
        recentDecodeTokensPerSecond:recentDecodeRate,outputTokensPerSecond:outputRate},
      runtimes:samples.map(x=>x.row),storage:capacityProjection()};
    telemetryCache={sampledAt,counters,complete,public:result};return result;
  })();
  try{return await telemetryPending;}finally{telemetryPending=null;}
}
// END ADMIN TELEMETRY.

function adminSummary() {
  let saved = {};
  try { saved = JSON.parse(fs.readFileSync(ADMIN_SUMMARY_FILE, 'utf8')); } catch {}
  const sessions = { secure: 0, internet: 0 };
  for (const s of SESSIONS.values()) sessions[normalizeInternetMode(s.internet) === 'on' ? 'internet' : 'secure']++;
  // Explicit projection prevents accidental publication of credentials or raw
  // Kubernetes configuration from an operator-supplied snapshot.
  return { generatedAt: new Date().toISOString(), registeredAccounts: Object.keys(loadUsers()).length,
    activeBrowserSessions: sessions, privateUserRouting: Boolean(USER_TARGETS), registrationEnabled: ALLOW_REGISTRATION,
    audit: { failuresSinceStart: auditFailures, recentEvents: recentAudit().length, legacy: legacyAuditStatus() },
    snapshot: { observedAt: typeof saved.observedAt === 'string' ? saved.observedAt : null,
      environments: Array.isArray(saved.environments) ? saved.environments.map(e => ({ name: String(e.name || ''),
        ready: e.ready === true, storage: String(e.storage || ''), network: String(e.network || '') })) : [],
      model: saved.model ? { backendContext: Number(saved.model.backendContext) || null,
        userContext: Number(saved.model.userContext) || null, concurrencyCeiling: Number(saved.model.concurrencyCeiling) || null,
        checkpoint:typeof saved.model.checkpoint==='string'&&/^DeepSeek-[A-Za-z0-9.-]{1,96}$/.test(saved.model.checkpoint)?saved.model.checkpoint:null,
        revision:typeof saved.model.revision==='string'&&/^[a-f0-9]{40}$/.test(saved.model.revision)?saved.model.revision:null,
        observedAt:typeof saved.model.observedAt==='string'&&saved.model.observedAt.length<128&&Number.isFinite(Date.parse(saved.model.observedAt))?saved.model.observedAt:null,
        longConcurrencyCeiling:Number.isSafeInteger(saved.model.longConcurrencyCeiling)&&saved.model.longConcurrencyCeiling>0?saved.model.longConcurrencyCeiling:null,
        maxOutputTokens:Number.isSafeInteger(saved.model.maxOutputTokens)&&saved.model.maxOutputTokens>0?saved.model.maxOutputTokens:null } : null,
      performance: Array.isArray(saved.performance) ? saved.performance.map(String) : [],
      gaps: Array.isArray(saved.gaps) ? saved.gaps.map(String) : [] } };
}

function renderAdminDashboard() {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DSH Admin overview</title>
<style>body{font:16px/1.6 system-ui;background:#f1f5f9;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:32px}a{color:#075985}header{display:flex;gap:24px;align-items:center;flex-wrap:wrap}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}section{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:20px;margin:18px 0}h1,h2{line-height:1.2}strong{font-size:24px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #e2e8f0}.muted{color:#475569}.notice{border-left:5px solid #d97706}button{padding:8px 16px;cursor:pointer}</style>
<main><header><h1>DSH Admin overview</h1><a href="/">Back to DSH</a><a href="/logout">Logout</a><button id="refresh">Refresh</button></header><p id="error" role="alert"></p><p id="time" class="muted"></p>
<div class="cards"><section>Registered accounts<br><strong id="accounts">—</strong></section><section>Main gateway browser sessions<br><strong id="sessions">—</strong><div id="sessionDetail"></div></section><section>User routing<br><strong id="routing">—</strong></section></div>
<section><h2>User management</h2><p>Manage access to existing private runtimes. Disabling an account preserves its files and history. Sign out closes browser and terminal connections; it does not cancel already-running tools.</p><p id="userMessage" role="status"></p><div style="overflow:auto"><table><thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Environments</th><th>Sessions</th><th>Actions</th></tr></thead><tbody id="users"></tbody></table></div><form id="createUser"><h3>Create a provisioned account</h3><label>Identity <select id="newUser" required></select></label> <label>Initial password <input id="newPassword" type="password" minlength="12" maxlength="1024" autocomplete="new-password" required></label> <button id="createButton">Create account</button></form><p id="provisionHelp">New identities require operator-provisioned private environments. Administrator roles are managed by the operator.</p></section>
<section><h2>DSH usage and activity</h2><p id="usageFreshness">Loading runtime summaries…</p><div class="cards"><div>Stored conversations<br><strong id="usageSessions">—</strong></div><div>Running DSH agents<br><strong id="usageAgents">—</strong></div><div>Queued DSH messages<br><strong id="usageQueued">—</strong></div><div>Recorded turns / LLM steps<br><strong id="usageTurns">—</strong></div><div>Accumulated input / output tokens<br><strong id="usageTokens">—</strong></div><div>All-history decode tokens/sec<br><strong id="usageDecode">—</strong></div><div>Recent conversation decode tokens/sec<br><strong id="usageRecentDecode">—</strong></div><div>Recent output tokens/sec<br><strong id="usageRate">—</strong></div></div><div style="overflow:auto"><table><thead><tr><th>Account</th><th>Environment</th><th>Agents</th><th>Conversations</th><th>Turns</th><th>LLM steps</th><th>Input tokens</th><th>Output tokens</th><th>Recorded decode tok/sec</th><th>Workspace / durable files GiB</th><th>Local state used / capacity GiB</th></tr></thead><tbody id="usageRows"></tbody></table></div><p class="muted">Stored totals include imported or copied histories. Decode speed uses recorded decode time; recent output rate uses changes between samples. This panel covers DSH application sessions, not independent terminal-client accounting. Conversation text, files and credentials are excluded.</p><p id="storageFreshness" class="muted"></p></section>
<section class="notice"><h2>Infrastructure observation</h2><p id="freshness"></p><p>Usage is sampled from runtime summaries. Account/browser-session counts and routing are current gateway values. The environment health, model limits and recorded performance below are an operator snapshot. Browser logins and conversations are separate counts.</p></section>
<section><h2>Execution environments</h2><div style="overflow:auto"><table><thead><tr><th>Environment</th><th>Recorded readiness</th><th>Storage</th><th>Recorded network behavior</th></tr></thead><tbody id="environments"></tbody></table></div></section>
<section><h2>Model limits</h2><p id="model"></p><p class="muted">A concurrency ceiling does not guarantee that many maximum-length requests fit.</p></section><section><h2>Recorded performance</h2><ul id="performance"></ul></section><section><h2>Central access audit</h2><p id="audit"></p><a href="/api/admin/audit">Read recent access events</a></section><section class="notice"><h2>Remaining controls</h2><ul id="gaps"></ul></section><p class="muted">Stored passwords, cookies and conversation contents are never displayed.</p></main>
<script>
const put=(id,value)=>document.getElementById(id).textContent=value;
let managementToken='';
async function userAction(action,user,password){try{const body=new URLSearchParams({action,user});if(password)body.set('password',password);const r=await fetch('/api/admin/users',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded','X-DSH-Admin-CSRF':managementToken},body});const d=await r.json();if(!r.ok)throw Error(d.error||'Account update failed.');put('userMessage',action+' completed for '+user+'.');await refreshUsers();await refresh();}catch(e){put('userMessage',e.message);}}
async function refreshUsers(){try{const r=await fetch('/api/admin/users',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw Error('User management unavailable.');const d=await r.json();managementToken=d.csrfToken;const root=document.getElementById('users');root.replaceChildren();for(const u of d.users){const tr=document.createElement('tr');for(const value of [u.user,u.role,u.enabled?'Enabled':'Disabled',u.environments.join(', '),u.sessions]){const td=document.createElement('td');td.textContent=value;tr.append(td);}const td=document.createElement('td');if(u.role!=='Administrator'){for(const action of [u.enabled?'disable':'enable','revoke',u.internetAllowed?'deny-internet':'allow-internet']){const b=document.createElement('button');b.type='button';b.textContent=action==='revoke'?'Sign out':action==='disable'?'Disable':action==='allow-internet'?'Allow Internet':action==='deny-internet'?'Disable Internet':'Enable';b.addEventListener('click',()=>{if(confirm(b.textContent+' '+u.user+'?'))userAction(action,u.user);});td.append(b);}}else td.textContent='Operator-managed';tr.append(td);root.append(tr);}const select=document.getElementById('newUser');select.replaceChildren();for(const user of d.provisionedIdentities){const opt=document.createElement('option');opt.value=user;opt.textContent=user;select.append(opt);}document.getElementById('createButton').disabled=!d.provisionedIdentities.length;}catch(e){put('userMessage',e.message);}}
document.getElementById('createUser').addEventListener('submit',e=>{e.preventDefault();const field=document.getElementById('newPassword');const password=field.value;field.value='';userAction('create',document.getElementById('newUser').value,password);});
function list(id,values){const root=document.getElementById(id);root.replaceChildren();for(const value of values){const li=document.createElement('li');li.textContent=value;root.append(li);}}
async function refresh(){try{const r=await fetch('/api/admin/summary',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw Error('Admin access unavailable ('+r.status+').');const d=await r.json();put('error','');put('time','Gateway read at '+d.generatedAt);put('accounts',d.registeredAccounts);put('sessions',d.activeBrowserSessions.secure+d.activeBrowserSessions.internet);put('sessionDetail','No Internet: '+d.activeBrowserSessions.secure+' · Internet: '+d.activeBrowserSessions.internet);put('routing',d.privateUserRouting?'Per user':'Shared pools');put('freshness',d.snapshot.observedAt?'Snapshot observed at '+d.snapshot.observedAt+'. Refresh does not rerun infrastructure tests.':'No snapshot available. Infrastructure status is unknown.');const root=document.getElementById('environments');root.replaceChildren();for(const e of d.snapshot.environments){const tr=document.createElement('tr');for(const text of [e.name,e.ready?'Ready at observation':'Not verified ready',e.storage,e.network]){const td=document.createElement('td');td.textContent=text;tr.append(td);}root.append(tr);}const m=d.snapshot.model;put('model',m?(m.checkpoint?'Checkpoint: '+m.checkpoint+(m.revision?' ('+m.revision.slice(0,12)+')':'')+' · ':'')+'Backend context: '+m.backendContext+' tokens · DSH/LiteLLM budget: '+m.userContext+' tokens · Running-request ceiling: '+m.concurrencyCeiling+(m.longConcurrencyCeiling?' · Requests above 128K input: '+m.longConcurrencyCeiling+' at a time':'')+(m.maxOutputTokens?' · Maximum output: '+m.maxOutputTokens+' tokens':'')+(m.observedAt?' · Model observed at '+m.observedAt:''):'No recorded limits.');list('performance',d.snapshot.performance);list('gaps',d.snapshot.gaps);}catch(e){put('error',e.message);}}
document.getElementById('refresh').addEventListener('click',refresh);refresh().then(async()=>{try{const r=await fetch('/api/admin/summary',{cache:'no-store'});const d=await r.json();put('audit','Recent main/legacy access events: '+d.audit.recentEvents+' · Write failures since gateway start: '+d.audit.failuresSinceStart+' · Legacy projection observed at: '+(d.audit.legacy?.observedAt||'not available'));}catch{put('audit','Audit status unavailable.');}});
document.getElementById('refresh').addEventListener('click',refreshUsers);refreshUsers();
const metricText=value=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:2}):'—';
const gib=value=>typeof value==='number'?metricText(value/1073741824):'—';
async function refreshUsage(){try{
 const response=await fetch('/api/admin/telemetry',{cache:'no-store',credentials:'same-origin'});
 if(!response.ok)throw Error('Runtime usage unavailable.');const data=await response.json(),t=data.totals;
 put('usageFreshness','Observed '+data.observedAt+' · '+data.availableRuntimes+'/'+data.configuredRuntimes+' private runtimes available · '+t.usageSessions+'/'+t.sessions+' stored sessions have usage records · refreshes every 15 seconds while visible.');
 put('usageSessions',metricText(t.sessions));put('usageAgents',metricText(t.runningAgents));put('usageQueued',metricText(t.queuedMessages));put('usageTurns',metricText(t.turns)+' / '+metricText(t.llmSteps));
 put('usageTokens',metricText(t.inputTokens)+' / '+metricText(t.outputTokens));put('usageDecode',metricText(t.recordedDecodeTokensPerSecond));put('usageRate',metricText(t.outputTokensPerSecond));put('usageRecentDecode',metricText(t.recentDecodeTokensPerSecond));
 const root=document.getElementById('usageRows');root.replaceChildren();
 for(const row of data.runtimes){const storage=data.storage?.runtimes.find(x=>x.user===row.user&&x.environment===row.environment),tr=document.createElement('tr');
  const values=[row.user,row.environment==='secure'?'No Internet':'Internet',...['runningAgents','sessions','turns','llmSteps','inputTokens','outputTokens','recordedDecodeTokensPerSecond'].map(k=>row.available?metricText(row[k]):'Unavailable'),storage?gib(storage.workspaceFileBytes)+' / '+gib(storage.durableStateFileBytes)+(storage.workspaceScanComplete&&storage.durableStateScanComplete?'':' (partial)'):'—',storage?gib(storage.stateUsedBytes)+' / '+gib(storage.stateCapacityBytes):'—'];
  for(const value of values){const cell=document.createElement('td');cell.textContent=value;tr.append(cell);}root.append(tr);
 }
 put('storageFreshness',data.storage?'Storage observed '+data.storage.observedAt+'. Workspace and durable-state bytes are separate file-size scans; partial scans are marked. Local state usage includes filesystem overhead.':'Storage capacity has not been collected.');
 }catch(error){put('usageFreshness',error.message);}}
document.getElementById('refresh').addEventListener('click',refreshUsage);refreshUsage();setInterval(()=>{if(!document.hidden)refreshUsage();},15000);
</script></html>`;
}

// A gateway can route an authenticated session to a dedicated execution pool.
// When these variables are absent the proxy keeps its original single-pod behaviour.
const ENVIRONMENT_TARGETS = {
  off: {
    name: 'secure',
    host: process.env.DSH_OFFLINE_HOST || DSH_TARGET_HOST,
    port: Number(process.env.DSH_OFFLINE_PORT || DSH_TARGET_PORT),
    tokenFile: process.env.DSH_OFFLINE_TOKEN_FILE || '/tmp/dsh_token.txt',
  },
  on: {
    name: 'internet',
    host: process.env.DSH_ONLINE_HOST || DSH_TARGET_HOST,
    port: Number(process.env.DSH_ONLINE_PORT || DSH_TARGET_PORT),
    tokenFile: process.env.DSH_ONLINE_TOKEN_FILE || '/tmp/dsh_token.txt',
  },
};

// Provisioned by an operator. No request header, URL, or form can choose a host.
// Enabling isolation makes missing identities fail closed rather than share a pool.
const USER_TARGETS = process.env.DSH_USER_TARGETS_FILE
  ? JSON.parse(fs.readFileSync(process.env.DSH_USER_TARGETS_FILE, 'utf8')) : null;
// Pilot accounts are provisioned by an administrator. Isolated routing always
// disables registration, including when a legacy opt-in variable is present.
const LEGACY_OWNER = !USER_TARGETS ? (process.env.DSH_SINGLE_USER || process.env.AUTH_USER || '') : '';
const LEGACY_INTERNET_ONLY = !USER_TARGETS && Boolean(process.env.AUTH_USER);
const ALLOW_REGISTRATION = !USER_TARGETS && !LEGACY_OWNER && process.env.DSH_ALLOW_REGISTRATION === 'true';
if (USER_TARGETS) {
  for (const [user, targets] of Object.entries(USER_TARGETS)) {
    if (!/^[a-z0-9_\-.]{3,30}$/.test(user)) throw new Error('Invalid provisioned identity');
    for (const target of Object.values(targets)) {
      if (!target || !/^[a-zA-Z0-9.-]+$/.test(target.host) ||
          !Number.isInteger(target.port) || target.port < 1024 || target.port > 65535 ||
          typeof target.tokenFile !== 'string' || !target.tokenFile.startsWith('/runtime-tokens/')) {
        throw new Error('Invalid provisioned runtime target');
      }
    }
  }
}
function getEnvironmentTarget(mode, user) {
  if (USER_TARGETS) {
    const environment = normalizeInternetMode(mode) === 'on' ? 'internet' : 'secure';
    const targets = Object.prototype.hasOwnProperty.call(USER_TARGETS, user) ? USER_TARGETS[user] : null;
    const target = targets && targets[environment];
    return target ? { ...target, name: environment } : null;
  }
  return ENVIRONMENT_TARGETS[normalizeInternetMode(mode)];
}

// The session cookie is shared with the app subdomains (dsh-<port>.<parent>) through its Domain
// attribute. The domain comes from configuration, never from the request's Host header, and
// defaults to the parent of DSH_TRUSTED_HOST (dsh.example.com -> .example.com); a host with
// fewer than three labels gets a host-only cookie.
function getCookieDomain() {
  if (process.env.DSH_COOKIE_DOMAIN) {
    const d = process.env.DSH_COOKIE_DOMAIN;
    return d.startsWith('.') ? `; Domain=${d}` : `; Domain=.${d}`;
  }
  const trusted = (process.env.DSH_TRUSTED_HOST || '').split(':')[0].toLowerCase();
  if (!trusted || /^(\d{1,3}\.){3}\d{1,3}$/.test(trusted)) return '';
  const parts = trusted.split('.');
  if (parts.length >= 3) {
    return '; Domain=.' + parts.slice(1).join('.');
  }
  return '';
}

// Proxy session cookies (this tenant's, the legacy dsh_auth name, and DSH's dsh-auth-*) are
// removed before a request reaches a user app, so an app cannot read and replay them.
function stripAuthCookies(cookieHeader) {
  if (!cookieHeader) return '';
  return cookieHeader.split(';').map(c => c.trim()).filter(c => c &&
    !c.startsWith(`${COOKIE_NAME}=`) && !c.startsWith('dsh_auth=') && !c.startsWith('dsh-auth-')).join('; ');
}

// In-memory sessions
const SESSIONS = new Map();
const cachedDshAuthCookies = new Map();
const USER_SOCKETS = new Map();
function accountEnabled(user) { const users=loadUsers(); return Object.hasOwn(users,user) && users[user].disabled !== true; }
function revokeUserSessions(user) {
  for (const [sid, session] of SESSIONS) if (session.user === user) SESSIONS.delete(sid);
  for (const socket of USER_SOCKETS.get(user) || []) socket.destroy();
  USER_SOCKETS.delete(user);
}
function internetAllowed(user) { return ADMIN_USERS.has(user) || loadUsers()[user]?.internetAllowed === true; }
function adminAccounts() {
  const users=loadUsers();
  return Object.keys(users).sort().map(user=>({user, enabled:users[user].disabled!==true,
    role:ADMIN_USERS.has(user)?'Administrator':'User', internetAllowed:internetAllowed(user),
    environments:USER_TARGETS ? ['secure','internet'].filter(mode=>Object.hasOwn(USER_TARGETS,user)&&USER_TARGETS[user][mode]) : ['instance'],
    sessions:[...SESSIONS.values()].filter(s=>s.user===user).length}));
}

// --- DYNAMIC APP GATEWAY HELPERS (OPTION 1 & OPTION 2) ---
function resolvePortAlias(alias) {
  if (!alias) return null;
  const key = alias.toLowerCase();
  try {
    const portsPath = '/workspace/.ports.json';
    if (fs.existsSync(portsPath)) {
      const mapping = JSON.parse(fs.readFileSync(portsPath, 'utf8'));
      if (mapping && mapping[key]) {
        return parseInt(mapping[key], 10);
      }
    }
  } catch (e) {
    console.error('[AUTH-PROXY] Error reading .ports.json:', e.message);
  }
  const defaults = {
    'terminal': 7681,
    'ttyd': 7681,
    'streamlit': 8501,
    'dashboard': 8501,
    'api': 8000,
    'fastapi': 8000,
    'web': 3000
  };
  return defaults[key] || null;
}

function parseAppTarget(inHost, reqUrl) {
  const parsed = url.parse(reqUrl, true);
  let port = null;
  let targetPath = reqUrl;

  // 1. Subdomain Check: e.g. dsh-8000.example.com, dsh2-8501, dsh-user2-8000...
  // dsh-user<N> is tried before dsh<N> so dsh-user2-8000 resolves to port 8000, not alias "user2-8000".
  const subMatch = inHost.match(/^(?:dsh-user[0-9]*|dsh[0-9]*)-([a-zA-Z0-9_-]+)\./i);
  if (subMatch) {
    const raw = subMatch[1];
    if (/^\d+$/.test(raw)) {
      port = parseInt(raw, 10);
    } else {
      port = resolvePortAlias(raw);
    }
    targetPath = reqUrl; // Root path preserved for SPA / assets
  }

  // 2. Path Check: e.g. /proxy/8000/ or /proxy/myapp/api
  if (!port) {
    const pathMatch = parsed.pathname.match(/^\/proxy\/([a-zA-Z0-9_-]+)(\/.*)?$/);
    if (pathMatch) {
      const raw = pathMatch[1];
      if (/^\d+$/.test(raw)) {
        port = parseInt(raw, 10);
      } else {
        port = resolvePortAlias(raw);
      }
      targetPath = (pathMatch[2] || '/') + (parsed.search || '');
    }
  }

  // Only user app ports are forwarded; the gateway and DSH ports are never app targets.
  if (!Number.isInteger(port) || port < 1 || port > 65535 || port === PROXY_PORT || port === DSH_TARGET_PORT) {
    port = null;
  }
  return { port, targetPath };
}

function forwardToLocalApp(targetPort, targetPath, req, res, targetHost = '127.0.0.1') {
  const proxyHeaders = { ...req.headers };
  proxyHeaders['host'] = `127.0.0.1:${targetPort}`;
  proxyHeaders['x-forwarded-host'] = req.headers.host;
  const appCookies = stripAuthCookies(req.headers.cookie);
  if (appCookies) {
    proxyHeaders['cookie'] = appCookies;
  } else {
    delete proxyHeaders['cookie'];
  }
  proxyHeaders['x-forwarded-proto'] = req.headers['x-forwarded-proto'] || 'https';

  const proxyReq = http.request({
    host: targetHost,
    port: targetPort,
    path: targetPath,
    method: req.method,
    headers: proxyHeaders
  }, (proxyRes) => {
    const resHeaders = { ...proxyRes.headers };
    if (resHeaders['content-type'] && resHeaders['content-type'].includes('text/html')) {
      resHeaders['cache-control'] = 'no-cache, no-store, must-revalidate';
      resHeaders['pragma'] = 'no-cache';
      resHeaders['expires'] = '0';
    }
    res.writeHead(proxyRes.statusCode, resHeaders);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    console.warn(`[AUTH-PROXY] App forward error on port ${targetPort}:`, err.message);
    res.writeHead(502, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>DSH App Gateway: Port ${targetPort}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0B0F19; color: #F8FAFC; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
    .card { background: #1E293B; border: 1px solid #334155; border-radius: 12px; padding: 32px; max-width: 540px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); width: 100%; }
    h2 { color: #38BDF8; margin-top: 0; display: flex; align-items: center; gap: 10px; font-size: 20px; }
    code { background: #0F172A; padding: 3px 8px; border-radius: 6px; color: #F43F5E; font-size: 14px; font-family: monospace; }
    p { color: #94A3B8; line-height: 1.6; font-size: 14px; }
    .tip { background: rgba(56, 189, 248, 0.1); border-left: 4px solid #38BDF8; padding: 14px 16px; margin: 20px 0; border-radius: 0 8px 8px 0; font-size: 13px; color: #E2E8F0; }
    .code-block { background: #0F172A; padding: 10px 14px; border-radius: 6px; margin-top: 8px; font-family: monospace; color: #A5F3FC; font-size: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>⚡ DSH Application Gateway</h2>
    <p>Target service on port <code>${targetPort}</code> is currently not listening inside this DSH container.</p>
    <div class="tip">
      <strong>How to start your web application:</strong><br>
      Start your server inside the DSH container terminal or via agent, e.g.:
      <div class="code-block">python -m http.server ${targetPort}</div>
      <div class="code-block">streamlit run app.py --server.port ${targetPort}</div>
      <div class="code-block">uvicorn main:app --host 0.0.0.0 --port ${targetPort}</div>
    </div>
    <p style="font-size: 12px; color: #64748B;">Internal status: ${err.message}</p>
  </div>
</body>
</html>`);
  });

  req.pipe(proxyReq);
}

function bindAuthenticatedProxyIdentity(req, user, internetMode) {
  // Every carrier, including custom applications and raw WebSocket upgrades,
  // receives identity from the authenticated session, never the client.
  req.headers['x-dsh-user'] = user;
  req.headers['x-dsh-internet-access'] = internetMode;
  const raw = [];
  for (let i = 0; i < req.rawHeaders.length; i += 2) {
    const name = req.rawHeaders[i].toLowerCase();
    if (name !== 'x-dsh-user' && name !== 'x-dsh-internet-access') {
      raw.push(req.rawHeaders[i], req.rawHeaders[i + 1]);
    }
  }
  raw.push('X-DSH-User', user, 'X-DSH-Internet-Access', internetMode);
  req.rawHeaders = raw;
}

function forwardWebSocketToLocalApp(targetPort, targetPath, req, socket, head, targetHost = '127.0.0.1') {
  const rawHeaders = req.rawHeaders;
  let upgradeReqText = `${req.method} ${targetPath} HTTP/${req.httpVersion}\r\n`;
  for (let i = 0; i < rawHeaders.length; i += 2) {
    const headerKey = rawHeaders[i];
    let headerVal = rawHeaders[i + 1];
    if (headerKey.toLowerCase() === 'host') {
      headerVal = `127.0.0.1:${targetPort}`;
    }
    if (headerKey.toLowerCase() === 'cookie') {
      headerVal = stripAuthCookies(headerVal);
      if (!headerVal) continue;
    }
    upgradeReqText += `${headerKey}: ${headerVal}\r\n`;
  }
  upgradeReqText += `\r\n`;

  const net = require('net');
  const targetSocket = net.connect(targetPort, targetHost, () => {
    targetSocket.write(upgradeReqText);
    if (head && head.length > 0) {
      targetSocket.write(head);
    }
    socket.pipe(targetSocket);
    targetSocket.pipe(socket);
  });

  targetSocket.on('error', (err) => {
    console.warn(`[AUTH-PROXY] WebSocket forward error on port ${targetPort}:`, err.message);
    socket.destroy();
  });
}

function getOrMintDshCookie(clientHost, target, callback) {
  const cacheKey = `${target.name}|${target.host}|${target.port}|${clientHost}`;
  const token = getDshToken(target.tokenFile);
  if (!token) {
    cachedDshAuthCookies.delete(cacheKey);
    return callback(new Error("No DSH launch token available"));
  }
  const fingerprint = crypto.createHash('sha256').update(token).digest('hex');
  const existing = cachedDshAuthCookies.get(cacheKey);
  if (existing?.fingerprint === fingerprint) return callback(null, existing.cookie);
  cachedDshAuthCookies.delete(cacheKey);
  const authReq = http.request({
    host: target.host,
    port: target.port,
    path: `/?token=${encodeURIComponent(token)}`,
    method: "GET",
    headers: { "host": clientHost }
  }, (authRes) => {
    let mintedCookie = null;
    const setCookies = authRes.headers["set-cookie"];
    if (setCookies) {
      for (const sc of setCookies) {
        if (sc.startsWith("dsh-auth-")) {
          mintedCookie = sc.split(";")[0];
          cachedDshAuthCookies.set(cacheKey, { fingerprint, cookie: mintedCookie });
          console.log(`[AUTH-PROXY] Successfully minted and cached upstream DSH cookie for authority ${clientHost}`);
          break;
        }
      }
    }
    authRes.resume();
    callback(null, mintedCookie);
  });
  authReq.on("error", (err) => {
    callback(err);
  });
  authReq.end();
}

// The admin password comes from environment or existing persistent user store
let adminPass = process.env.DSH_AUTH_PASS;
if (!adminPass && !fs.existsSync(USER_STORE_PATH)) {
  console.error('[AUTH-PROXY] DSH_AUTH_PASS is not set and no user store found; refusing to start.');
  process.exit(1);
}
const DEFAULT_USERS = {
  ...(adminPass ? { 'admin': hashPassword(adminPass) } : {})
};

function loadUsers() {
  try {
    if (fs.existsSync(USER_STORE_PATH)) {
      const raw = fs.readFileSync(USER_STORE_PATH, 'utf8');
      const data = JSON.parse(raw);
      return Object.assign(Object.create(null), DEFAULT_USERS, migrateUsers(data));
    }
  } catch (e) {
    console.error('[AUTH-PROXY] Invalid account store; refusing startup/request.');
    throw e;
  }
  return Object.assign({}, DEFAULT_USERS);
}

function saveUsers(users) {
  try {
    writeAtomicUsers(USER_STORE_PATH, users);
    return true;
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to save user store:', e.message);
    return false;
  }
}

function loadUserSettings() {
  try {
    if (fs.existsSync(USER_SETTINGS_PATH)) {
      const data = JSON.parse(fs.readFileSync(USER_SETTINGS_PATH, 'utf8'));
      if (data && typeof data === 'object' && !Array.isArray(data)) return data;
    }
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to load user settings:', e.message);
  }
  return {};
}

function saveUserSettings(settings) {
  try {
    fs.mkdirSync(USER_ROOT, { recursive: true });
    fs.writeFileSync(USER_SETTINGS_PATH, JSON.stringify(settings, null, 2), { encoding: 'utf8', mode: 0o600 });
    return true;
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to save user settings:', e.message);
    return false;
  }
}

function normalizeInternetMode(value) {
  return LEGACY_INTERNET_ONLY ? 'on' : (value === 'on' ? 'on' : 'off');
}

function setUserInternetMode(username, mode) {
  const settings = loadUserSettings();
  settings[username] = { ...(settings[username] || {}), internet: normalizeInternetMode(mode) };
  return saveUserSettings(settings);
}

function injectLogoutControl(html, isAdmin = false) {
  if (typeof html !== 'string' || html.includes('id="dsh-enterprise-logout"')) return html;
  const control = `<a id="dsh-enterprise-logout" href="/logout" aria-label="Logout" title="Logout" style="position:fixed;right:18px;top:14px;z-index:2147483647;display:inline-flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid rgba(148,163,184,.42);border-radius:8px;background:rgba(15,23,42,.94);color:#f8fafc;font:600 13px/1.2 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.28);backdrop-filter:blur(8px)"><span aria-hidden="true">&#x21AA;</span><span>Logout</span></a>`;
  const adminLink = isAdmin ? '<a id="dsh-admin-dashboard" href="/admin" style="position:fixed;right:220px;top:14px;z-index:2147483647;background:#0f172a;color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font:600 13px system-ui">Admin overview</a>' : '';
  if (/<\/body>/i.test(html)) return html.replace(/<\/body>/i, `${control}${adminLink}</body>`);
  return html + control + adminLink;
}

// Initialize user store if missing
let USERS = loadUsers();
// Persist salted hashes before accepting any requests; never fall back to a
// plaintext store or overwrite a corrupt store with default accounts.
if (!saveUsers(USERS)) throw new Error('Account migration could not be persisted');

function getDshToken(tokenFile = '/tmp/dsh_token.txt') {
  try {
    if (fs.existsSync(tokenFile)) {
      return fs.readFileSync(tokenFile, 'utf8').trim();
    }
  } catch (e) {}
  return '';
}

function renderAuthPage({ tab = 'login', errorMsg = '', successMsg = '' } = {}) {
  return `<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login · DeepSeek Harness (DSH) — Enterprise AI Platform</title>
  <style>
    :root {
      --primary-navy: #0F4C81;
      --primary-deep: #0A2540;
      --primary-gold: #C5A880;
      --bg-dark: #0B0F19;
      --card-bg: #131C2E;
      --border: #202E49;
      --text-main: #E2E8F0;
      --text-muted: #94A3B8;
      --success-bg: rgba(16, 185, 129, 0.15);
      --success-border: rgba(16, 185, 129, 0.35);
      --success-text: #34D399;
      --error-bg: rgba(239, 68, 68, 0.15);
      --error-border: rgba(239, 68, 68, 0.35);
      --error-text: #F87171;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Sarabun', -apple-system, sans-serif; }
    body {
      background-color: var(--bg-dark);
      background-image: radial-gradient(circle at top right, #1a2f4d 0%, transparent 60%), radial-gradient(circle at bottom left, #0d1e38 0%, transparent 60%);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .login-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      width: 100%;
      max-width: 460px;
      padding: 36px 32px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05);
      position: relative;
      overflow: hidden;
    }
    .login-card::before {
      content: "";
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 4px;
      background: linear-gradient(90deg, var(--primary-gold), #e8d5b5, var(--primary-navy));
    }
    .brand-header {
      text-align: center;
      margin-bottom: 24px;
    }
    .brand-logo {
      width: 52px;
      height: 52px;
      margin: 0 auto 12px;
      background: linear-gradient(135deg, var(--primary-navy), var(--primary-deep));
      border: 1px solid rgba(197, 168, 128, 0.4);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .brand-logo svg {
      width: 28px;
      height: 28px;
      fill: var(--primary-gold);
    }
    .org-title {
      font-size: 13px;
      letter-spacing: 1px;
      color: var(--primary-gold);
      font-weight: 600;
      text-transform: uppercase;
    }
    .app-title {
      font-size: 20px;
      font-weight: 700;
      color: #FFF;
      margin: 4px 0 2px;
    }
    .app-subtitle {
      font-size: 12px;
      color: var(--text-muted);
    }

    /* Tabs */
    .auth-tabs {
      display: flex;
      background: rgba(11, 15, 25, 0.7);
      border-radius: 8px;
      padding: 4px;
      margin-bottom: 20px;
      border: 1px solid var(--border);
    }
    .auth-tab {
      flex: 1;
      text-align: center;
      padding: 8px 4px;
      font-size: 13px;
      font-weight: 500;
      color: var(--text-muted);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;
      text-decoration: none;
    }
    .auth-tab.active {
      background: var(--primary-navy);
      color: #FFF;
      font-weight: 600;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
    }

    .alert-badge {
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 13px;
      margin-bottom: 18px;
      line-height: 1.4;
    }
    .alert-error {
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      color: var(--error-text);
    }
    .alert-success {
      background: var(--success-bg);
      border: 1px solid var(--success-border);
      color: var(--success-text);
    }

    .form-group {
      margin-bottom: 16px;
    }
    .form-label {
      display: block;
      font-size: 13px;
      font-weight: 500;
      color: var(--text-muted);
      margin-bottom: 6px;
    }
    .form-control {
      width: 100%;
      padding: 11px 14px;
      background: rgba(11, 15, 25, 0.6);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: #FFF;
      font-size: 14px;
      transition: all 0.2s;
    }
    .form-control:focus {
      outline: none;
      border-color: var(--primary-navy);
      box-shadow: 0 0 0 3px rgba(15, 76, 129, 0.25);
      background: rgba(11, 15, 25, 0.9);
    }
    .radio-group {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .radio-option {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: rgba(11, 15, 25, 0.6);
      border: 1px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      font-size: 13px;
    }
    .radio-option:has(input:checked) { border-color: var(--primary-navy); background: rgba(15, 76, 129, 0.2); }
    .form-help { margin-top: 6px; color: var(--text-muted); font-size: 11px; line-height: 1.4; }
    .btn-submit {
      width: 100%;
      padding: 12px;
      background: linear-gradient(135deg, var(--primary-navy), #165b99);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      color: #FFFFFF;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
      box-shadow: 0 4px 12px rgba(15, 76, 129, 0.4);
      margin-top: 6px;
    }
    .btn-submit:hover {
      background: linear-gradient(135deg, #165b99, #1b6cb4);
      transform: translateY(-1px);
    }
    .footer-note {
      text-align: center;
      margin-top: 22px;
      font-size: 11px;
      color: #64748B;
    }
  </style>
  <script>
    function switchTab(name) {
      document.querySelectorAll('.tab-pane').forEach(el => el.style.display = 'none');
      document.querySelectorAll('.auth-tab').forEach(el => el.classList.remove('active'));
      document.getElementById('pane-' + name).style.display = 'block';
      document.getElementById('tab-' + name).classList.add('active');
    }
  </script>
</head>
<body>
  <div class="login-card">
    <div class="brand-header">
      <div class="brand-logo">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
      </div>
      <div class="org-title">Enterprise AI Platform</div>
      <h1 class="app-title">DeepSeek Harness (DSH)</h1>
      <p class="app-subtitle">Enterprise Agentic Coding & Knowledge Gateway</p>
    </div>

    <div class="auth-tabs">
      <div id="tab-login" class="auth-tab ${tab === 'login' ? 'active' : ''}" onclick="switchTab('login')">เข้าสู่ระบบ</div>
      ${ALLOW_REGISTRATION ? `<div id="tab-register" class="auth-tab ${tab === 'register' ? 'active' : ''}" onclick="switchTab('register')">สร้างบัญชีผู้ใช้ใหม่</div>` : ''}
      <div id="tab-change" class="auth-tab ${tab === 'change' ? 'active' : ''}" onclick="switchTab('change')">เปลี่ยนรหัสผ่าน</div>
    </div>

    ${errorMsg ? `<div class="alert-badge alert-error">⚠️ ${errorMsg}</div>` : ''}
    ${successMsg ? `<div class="alert-badge alert-success">✅ ${successMsg}</div>` : ''}

    <!-- 1. Form: เข้าสู่ระบบ -->
    <div id="pane-login" class="tab-pane" style="display: ${tab === 'login' ? 'block' : 'none'};">
      <form method="POST" action="/login">
        <div class="form-group">
          <label class="form-label" for="login_username">ชื่อผู้ใช้งาน (Username)</label>
          <input type="text" id="login_username" name="username" class="form-control" placeholder="เช่น admin หรือชื่อของคุณ" required autofocus>
        </div>
        <div class="form-group">
          <label class="form-label" for="login_password">รหัสผ่าน (Password)</label>
          <input type="password" id="login_password" name="password" class="form-control" placeholder="ระบุรหัสผ่านเพื่อเข้าใช้งาน" required>
        </div>
        <div class="form-group">
          <span class="form-label">Working environment</span>
          <div class="radio-group" role="radiogroup" aria-label="Working environment">
            <label class="radio-option"><input type="radio" name="internet" value="off" ${LEGACY_INTERNET_ONLY ? 'disabled' : 'checked'}> ${LEGACY_INTERNET_ONLY ? 'No Internet unavailable on this legacy instance' : 'No Internet / Internal (Default)'}</label>
            <label class="radio-option"><input type="radio" name="internet" value="on" id="internet-option" disabled> Internet (administrator approval required)</label>
          </div>
          <div class="form-help">${LEGACY_INTERNET_ONLY ? 'Legacy owner-only Internet workspace. Use the main DSH service for separate No Internet and Internet environments.' : 'The environment is fixed for this login session. No Internet / Internal permits approved internal services only; Internet uses a separate staging workspace. These environments do not share project files or chat history.'}</div>
        </div>
        <button type="submit" class="btn-submit">เข้าสู่ระบบ (Sign In)</button>
      </form>
    </div>

    ${ALLOW_REGISTRATION ? `<!-- 2. Form: สร้างบัญชีผู้ใช้ใหม่ -->
    <div id="pane-register" class="tab-pane" style="display: ${tab === 'register' ? 'block' : 'none'};">
      <form method="POST" action="/register">
        <div class="form-group">
          <label class="form-label" for="reg_username">ชื่อผู้ใช้งานใหม่ (New Username)</label>
          <input type="text" id="reg_username" name="username" class="form-control" placeholder="ตัวอักษรภาษาอังกฤษหรือตัวเลข (เช่น johndoe)" pattern="[a-zA-Z0-9_\-\.]{3,30}" title="ยาว 3-30 ตัวอักษร ใช้ได้เฉพาะ a-z, 0-9, _, -" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg_password">รหัสผ่าน (Password)</label>
          <input type="password" id="reg_password" name="password" class="form-control" placeholder="รหัสผ่านอย่างน้อย 6 ตัวอักษร" minlength="6" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg_confirm">ยืนยันรหัสผ่าน (Confirm Password)</label>
          <input type="password" id="reg_confirm" name="confirm_password" class="form-control" placeholder="กรอกรหัสผ่านอีกครั้ง" minlength="6" required>
        </div>
        <button type="submit" class="btn-submit">สร้างบัญชีผู้ใช้ใหม่ (Create Account)</button>
      </form>
    </div>

    ` : ''}
    <!-- 3. Form: เปลี่ยนรหัสผ่าน -->
    <div id="pane-change" class="tab-pane" style="display: ${tab === 'change' ? 'block' : 'none'};">
      <form method="POST" action="/change-password">
        <div class="form-group">
          <label class="form-label" for="chg_username">ชื่อผู้ใช้งาน (Username)</label>
          <input type="text" id="chg_username" name="username" class="form-control" placeholder="ระบุชื่อผู้ใช้งาน" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="chg_old_password">รหัสผ่านเดิม (Current Password)</label>
          <input type="password" id="chg_old_password" name="old_password" class="form-control" placeholder="ระบุรหัสผ่านปัจจุบัน" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="chg_new_password">รหัสผ่านใหม่ (New Password)</label>
          <input type="password" id="chg_new_password" name="new_password" class="form-control" placeholder="รหัสผ่านใหม่อย่างน้อย 6 ตัวอักษร" minlength="6" required>
        </div>
        <button type="submit" class="btn-submit">เปลี่ยนรหัสผ่าน (Update Password)</button>
      </form>
    </div>

    <div class="footer-note">
      ระบบสารสนเทศเฉพาะกิจองค์กร · รักษาความลับข้อมูลขั้นสูงสุด
    </div>
  </div>
<script>
(()=>{const u=document.getElementById('login_username'),p=document.getElementById('login_password'),on=document.getElementById('internet-option');if(!u||!p||!on)return;let generation=0;
function reset(){generation++;on.disabled=true;on.checked=false;const off=document.querySelector('input[name="internet"][value="off"]');if(off&&!off.disabled)off.checked=true;}
async function check(){reset();const g=generation;if(!u.value||!p.value)return;try{const r=await fetch('/api/login-environments',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({username:u.value,password:p.value})});const d=await r.json();if(g===generation)on.disabled=!d.internetAllowed;}catch{}}
u.addEventListener('input',reset);p.addEventListener('input',reset);u.addEventListener('change',check);p.addEventListener('change',check);})();
</script>
</body>
</html>`;
}

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);
  if (req.method === 'POST' && ['/login','/register','/change-password','/api/login-environments'].includes(parsedUrl.pathname)) {
    if (Number(req.headers['content-length']) > 16384) { res.writeHead(413); return res.end('Authentication form too large'); }
    let received = 0;
    req.on('data', chunk => {
      received += chunk.length;
      if (received > 16384 && !res.writableEnded) {
        res.writeHead(413); res.end('Authentication form too large');
        req.removeAllListeners('end'); req.removeAllListeners('data'); req.resume();
      }
    });
  }


  if (req.method === 'POST' && parsedUrl.pathname === '/api/login-environments') {
    let body='';req.on('data',c=>body+=c);req.on('end',async()=>{try{const f=new URLSearchParams(body),u=(f.get('username')||'').trim().toLowerCase();const ok=(!LEGACY_OWNER||u===LEGACY_OWNER)&&accountEnabled(u)&&await verifyPassword((f.get('password')||'').trim(),loadUsers()[u]);res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify({internetAllowed:Boolean(ok&&internetAllowed(u))}));}catch{res.writeHead(503);res.end('{}');}});return;
  }

  // Handle Login Form Submission
  if (req.method === 'POST' && parsedUrl.pathname === '/login') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', async () => {
      const params = new URLSearchParams(body);
      const username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const password = params.get('password') ? params.get('password').trim() : '';
      const internet = normalizeInternetMode(params.get('internet'));

      USERS = loadUsers();
      if ((!LEGACY_OWNER || username === LEGACY_OWNER) && USERS[username]?.disabled !== true && await verifyPassword(password, USERS[username]) && accountEnabled(username)) {
        if (internet === 'on' && !internetAllowed(username)) { res.writeHead(403); return res.end('Internet environment requires administrator approval.'); }
        if (!getEnvironmentTarget(internet, username)) {
          res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end('No dedicated runtime provisioned for this identity and environment.');
        }
        if (!setUserInternetMode(username, internet)) {
          res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' });
          return res.end(renderAuthPage({ tab: 'login', errorMsg: 'ไม่สามารถบันทึกนโยบาย Internet access ได้ กรุณาลองใหม่อีกครั้ง' }));
        }
        if (!auditEvent('login.success', username, internet)) { res.writeHead(503); return res.end('Audit storage unavailable.'); }
        const sessionId = crypto.randomBytes(24).toString('hex');
        SESSIONS.set(sessionId, { user: username, internet, created: Date.now() });

        // Create personal workspace folder for user if not exists
        try {
          fs.mkdirSync(`${USER_ROOT}/${username}`, { recursive: true });
        } catch (e) {}

        console.log(`[AUTH-PROXY] Successful login for user: ${username}`);
        const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
        const target = getEnvironmentTarget(internet, username);
        getOrMintDshCookie(clientHost, target, (err, dshCookie) => {
          const domainAttr = getCookieDomain();
          const cookieHeaders = [`${COOKIE_NAME}=${sessionId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400${domainAttr}${COOKIE_TRANSPORT}`];
          if (dshCookie) {
            cookieHeaders.push(`${dshCookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400${COOKIE_TRANSPORT}`);
          }
          res.writeHead(302, {
            'Set-Cookie': cookieHeaders,
            'Location': '/'
          });
          return res.end();
        });
      } else {
        auditEvent('login.denied', username, 'off');
        console.log(`[AUTH-PROXY] Failed login attempt for user: ${username}`);
        res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', errorMsg: 'ชื่อผู้ใช้งานหรือรหัสผ่านไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง' }));
      }
    });
    return;
  }

  // Handle User Registration Form Submission
  if (req.method === 'POST' && parsedUrl.pathname === '/register') {
    if (!ALLOW_REGISTRATION) {
      res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('Self-registration is disabled. Contact the pilot administrator.');
    }
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      const params = new URLSearchParams(body);
      const username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const password = params.get('password') ? params.get('password').trim() : '';
      const confirmPassword = params.get('confirm_password') ? params.get('confirm_password').trim() : '';

      if (!username || !/^[a-z0-9_\-\.]{3,30}$/.test(username)) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'ชื่อผู้ใช้งานต้องเป็นภาษาอังกฤษ/ตัวเลข ความยาว 3-30 ตัวอักษร' }));
      }

      if (!password || password.length < 6 || Buffer.byteLength(password) > 1024) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'รหัสผ่านต้องมีความยาวอย่างน้อย 6 ตัวอักษร' }));
      }

      if (password !== confirmPassword) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน กรุณาตรวจสอบอีกครั้ง' }));
      }

      USERS = loadUsers();
      if (USERS[username]) {
        res.writeHead(409, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: `ชื่อผู้ใช้งาน "${username}" มีอยู่ในระบบแล้ว กรุณาใช้ชื่ออื่นหรือเข้าสู่ระบบ` }));
      }

      USERS[username] = hashPassword(password);
      if (saveUsers(USERS)) {
        try {
          fs.mkdirSync(`${USER_ROOT}/${username}`, { recursive: true });
        } catch (e) {}
        console.log(`[AUTH-PROXY] Successfully registered new user: ${username}`);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', successMsg: `สร้างบัญชี "${username}" เรียบร้อยแล้ว สามารถเข้าสู่ระบบได้ทันที` }));
      } else {
        res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'เกิดข้อผิดพลาดในการบันทึกข้อมูล กรุณาลองใหม่อีกครั้ง' }));
      }
    });
    return;
  }

  // Handle Password Change Form Submission
  if (req.method === 'POST' && parsedUrl.pathname === '/change-password') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', async () => {
      const params = new URLSearchParams(body);
      const username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const oldPassword = params.get('old_password') ? params.get('old_password').trim() : '';
      const newPassword = params.get('new_password') ? params.get('new_password').trim() : '';

      if (!username || !oldPassword || !newPassword) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'กรุณากรอกข้อมูลให้ครบทุกช่อง' }));
      }

      if (newPassword.length < 6 || Buffer.byteLength(newPassword) > 1024) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'รหัสผ่านใหม่ต้องมีความยาวอย่างน้อย 6 ตัวอักษร' }));
      }

      USERS = loadUsers();
      if ((LEGACY_OWNER && username !== LEGACY_OWNER) || USERS[username]?.disabled === true || !await verifyPassword(oldPassword, USERS[username])) {
        res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'ชื่อผู้ใช้งานหรือรหัสผ่านเดิมไม่ถูกต้อง' }));
      }

      USERS = loadUsers();
      if (USERS[username]?.disabled === true) { res.writeHead(403); return res.end('Account disabled.'); }
      USERS[username] = { ...USERS[username], ...hashPassword(newPassword) };
      if (saveUsers(USERS)) {
        console.log(`[AUTH-PROXY] Successfully changed password for user: ${username}`);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', successMsg: `เปลี่ยนรหัสผ่านสำหรับผู้ใช้ "${username}" สำเร็จแล้ว กรุณาเข้าสู่ระบบด้วยรหัสผ่านใหม่` }));
      } else {
        res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'เกิดข้อผิดพลาดในการบันทึกรหัสผ่านใหม่ กรุณาลองใหม่อีกครั้ง' }));
      }
    });
    return;
  }

  // Handle Logout
  if (parsedUrl.pathname === '/logout') {
    for (const c of (req.headers.cookie || '').split(';').map(v => v.trim())) {
      for (const name of [COOKIE_NAME, 'dsh_auth']) {
        if (c.startsWith(`${name}=`)) {
          const sid = c.substring(name.length + 1);const s = SESSIONS.get(sid);
          if (s) auditEvent('logout', s.user, s.internet);
          SESSIONS.delete(sid);
        }
      }
    }
    const domainAttr = getCookieDomain();
    res.writeHead(302, {
      'Set-Cookie': `${COOKIE_NAME}=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax${domainAttr}${COOKIE_TRANSPORT}`,
      'Location': '/login'
    });
    return res.end();
  }

  // Check Session Cookie
  let authenticated = false;
  let sessionUser = null;
  let activeSession = null;
  const cookieHeader = req.headers.cookie;
  if (cookieHeader) {
    const cookies = cookieHeader.split(';').map(c => c.trim());
    for (const c of cookies) {
      if (c.startsWith(`${COOKIE_NAME}=`)) {
        const sid = c.substring(`${COOKIE_NAME}=`.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          sessionUser = activeSession.user;
          break;
        }
      }
      if (!authenticated && COOKIE_NAME !== 'dsh_auth' && c.startsWith('dsh_auth=')) {
        const sid = c.substring('dsh_auth='.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          sessionUser = activeSession.user;
          break;
        }
      }
    }
  }

  if (authenticated && (!accountEnabled(sessionUser) || (activeSession.internet === 'on' && !internetAllowed(sessionUser)))) { revokeUserSessions(sessionUser); authenticated=false; }
  if (!authenticated) {
    const tab = parsedUrl.query.tab || 'login';
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(renderAuthPage({ tab }));
  }

  // Reserve admin routes before any app forwarding or environment lookup.
  if (parsedUrl.pathname === '/admin' || parsedUrl.pathname.startsWith('/api/admin/')) {
    const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer' };
    if (!ADMIN_USERS.has(sessionUser)) { auditEvent('admin.denied', sessionUser, activeSession.internet); res.writeHead(403, headers); return res.end('Administrator access required.'); }
    if (parsedUrl.pathname === '/api/admin/users') {
      const reply=(status,data)=>{res.writeHead(status,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data));};
      if(req.method==='GET') {
        activeSession.adminCsrf ||= crypto.randomBytes(32).toString('hex');
        return reply(200,{users:adminAccounts(),csrfToken:activeSession.adminCsrf,
          provisionedIdentities:USER_TARGETS ? Object.keys(USER_TARGETS).filter(u=>!ADMIN_USERS.has(u)&&!Object.hasOwn(loadUsers(),u)&&USER_TARGETS[u].secure&&USER_TARGETS[u].internet).sort() : []});
      }
      if(req.method!=='POST') return reply(405,{error:'Use GET or POST.'});
      if(!activeSession.adminCsrf || req.headers['x-dsh-admin-csrf']!==activeSession.adminCsrf) return reply(403,{error:'Invalid management token.'});
      if(req.headers.origin) {
        let expected=process.env.DSH_TRUSTED_HOST || req.headers.host;
        try { if(new URL(req.headers.origin).host!==expected) return reply(403,{error:'Cross-origin management denied.'}); }
        catch { return reply(403,{error:'Invalid origin.'}); }
      }
      if(!String(req.headers['content-type']||'').startsWith('application/x-www-form-urlencoded')) return reply(415,{error:'Form encoding required.'});
      let body='',tooLarge=false;
      req.on('data',chunk=>{if(tooLarge)return;body+=chunk;if(Buffer.byteLength(body)>4096){tooLarge=true;reply(413,{error:'Request too large.'});}});
      req.on('end',()=>{
        if(tooLarge)return;
        try {
          if(!accountEnabled(sessionUser) || ![...SESSIONS.values()].includes(activeSession)) return reply(403,{error:'Session expired.'});
          const fields=new URLSearchParams(body),user=fields.get('user')||'',action=fields.get('action');
          if(!/^[a-z0-9_.-]{3,30}$/.test(user)||!['create','enable','disable','revoke','allow-internet','deny-internet'].includes(action)) return reply(400,{error:'Invalid account or action.'});
          const users=loadUsers();
          if(ADMIN_USERS.has(user)) return reply(409,{error:'Administrator accounts are maintained by the operator.'});
          if(action==='create') {
            if(Object.hasOwn(users,user))return reply(409,{error:'Account already exists.'});
            if(!USER_TARGETS || !Object.hasOwn(USER_TARGETS,user) || !USER_TARGETS[user].secure || !USER_TARGETS[user].internet) return reply(409,{error:'Provision both private environments before creating this account.'});
            const password=fields.get('password')||'';
            if(password.length<12||Buffer.byteLength(password)>1024||password!==password.trim())return reply(400,{error:'Use a password of 12 or more characters without surrounding spaces.'});
            users[user]=hashPassword(password);
          } else {
            if(!Object.hasOwn(users,user))return reply(404,{error:'Account not found.'});
            if(action==='enable'||action==='disable')users[user]={...users[user],disabled:action==='disable'};
            if(action==='allow-internet'||action==='deny-internet')users[user]={...users[user],internetAllowed:action==='allow-internet'};
          }
          if(!auditEvent('account.'+action,sessionUser,activeSession.internet,user))return reply(503,{error:'Audit storage unavailable.'});
          if(action!=='revoke'&&!saveUsers(users))return reply(500,{error:'Account update could not be saved.'});
          if(action==='disable'||action==='revoke'||action==='deny-internet')revokeUserSessions(user);
          return reply(200,{updated:true,user,action});
        } catch {return reply(500,{error:'Account management unavailable.'});}
      });
      return;
    }
    if(!['/admin','/api/admin/summary','/api/admin/audit','/api/admin/telemetry'].includes(parsedUrl.pathname)){res.writeHead(404,headers);return res.end('Unknown admin endpoint.');}
    if (req.method !== 'GET') { res.writeHead(405, { ...headers, Allow: 'GET' }); return res.end('Read-only endpoint.'); }
    if(parsedUrl.pathname==='/api/admin/telemetry')return adminTelemetry().then(data=>{
      if(res.destroyed)return;
      if(!accountEnabled(sessionUser)||![...SESSIONS.values()].includes(activeSession)){
        res.writeHead(403,{...headers,'Content-Type':'application/json; charset=utf-8'});return res.end(JSON.stringify({error:'Administrator session ended.'}));
      }
      res.writeHead(200,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data));
    }).catch(()=>{res.writeHead(503,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify({error:'Runtime usage unavailable.'}));});
    const api = parsedUrl.pathname !== '/admin';
    res.writeHead(200, { ...headers, 'Content-Type': api ? 'application/json; charset=utf-8' : 'text/html; charset=utf-8' });
    return res.end(api ? JSON.stringify(parsedUrl.pathname.endsWith('/audit') ? {events:recentAudit()} : adminSummary()) : renderAdminDashboard());
  }
  const internetMode = normalizeInternetMode(activeSession && activeSession.internet);
  const environmentTarget = getEnvironmentTarget(internetMode, sessionUser);
  if (!environmentTarget) {
    res.writeHead(403);
    return res.end('Dedicated runtime is not provisioned.');
  }
  bindAuthenticatedProxyIdentity(req, sessionUser, internetMode);

  if (req.method === 'GET' && parsedUrl.pathname === '/api/auth/session') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    return res.end(JSON.stringify({ user: sessionUser, internet: internetMode, environment: environmentTarget.name }));
  }

  // Convenient Terminal Shortcuts (/terminal, /term)
  if (parsedUrl.pathname === '/terminal' || parsedUrl.pathname === '/term') {
    res.writeHead(302, { 'Location': '/proxy/terminal/' });
    return res.end();
  }

  // Dynamic App Gateway (Option 1 Subdomain or Option 2 Path Proxy); only reachable after login
  if (!auditEvent('runtime.http', sessionUser, internetMode)) { res.writeHead(503); return res.end('Audit storage unavailable.'); }
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const appTarget = parseAppTarget(incomingHost, req.url);
  if (appTarget && appTarget.port) {
    return forwardToLocalApp(appTarget.port, appTarget.targetPath, req, res, environmentTarget.host);
  }

  // If authenticated, proxy request to DSH internal port 3081
  const token = getDshToken();

  // Ensure upstream DSH authentication cookie is established via internal token exchange
  function forwardToDsh(dshCookie) {
    const proxyHeaders = { ...req.headers };
    // Preserve client Host header (dsh.example.com) to satisfy trustedHosts and Origin checks
    const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
    proxyHeaders['host'] = clientHost;
    proxyHeaders['x-dsh-user'] = sessionUser;
    proxyHeaders['x-dsh-internet-access'] = internetMode;
    // Request an uncompressed document so the authenticated UI can receive the
    // enterprise logout control without modifying the upstream DSH package.
    delete proxyHeaders['accept-encoding'];

    if (dshCookie) {
      const existingCookies = req.headers.cookie ? req.headers.cookie.split(';').map(c => c.trim()) : [];
      // Filter out any stale dsh-auth cookies and append current valid upstream cookie
      const filtered = existingCookies.filter(c => !c.startsWith('dsh-auth-'));
      filtered.push(dshCookie);
      proxyHeaders['cookie'] = filtered.join('; ');
    }

    const proxyReq = http.request({
      host: environmentTarget.host,
      port: environmentTarget.port,
      path: req.url,
      method: req.method,
      headers: proxyHeaders
    }, (proxyRes) => {
      // If upstream returns a redirect to / and we already passed a valid cookie, avoid client redirect storm
      const resHeaders = { ...proxyRes.headers };
      const isHtml = resHeaders['content-type'] && resHeaders['content-type'].includes('text/html');
      if (isHtml) {
        resHeaders['cache-control'] = 'no-cache, no-store, must-revalidate';
        resHeaders['pragma'] = 'no-cache';
        resHeaders['expires'] = '0';
        delete resHeaders['content-length'];
        delete resHeaders['content-encoding'];
        delete resHeaders['transfer-encoding'];
      }
      if (!isHtml) {
        res.writeHead(proxyRes.statusCode, resHeaders);
        return proxyRes.pipe(res);
      }

      const chunks = [];
      proxyRes.on('data', chunk => chunks.push(chunk));
      proxyRes.on('end', () => {
        const body = injectLogoutControl(Buffer.concat(chunks).toString('utf8'), ADMIN_USERS.has(sessionUser));
        resHeaders['content-length'] = Buffer.byteLength(body);
        res.writeHead(proxyRes.statusCode, resHeaders);
        res.end(body);
      });
    });

    proxyReq.on('error', (err) => {
      console.error('[AUTH-PROXY] Forward error:', err.message);
      res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Gateway Error: ไม่สามารถเชื่อมต่อบริการ DSH ภายในได้ กรุณารอสักครู่');
    });

    req.pipe(proxyReq);
  }

  const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
  getOrMintDshCookie(clientHost, environmentTarget, (err, dshCookie) => {
    forwardToDsh(dshCookie);
  });
});

// Handle WebSocket Upgrades
server.on('upgrade', (req, socket, head) => {
  let authenticated = false;
  let activeSession = null;
  const cookieHeader = req.headers.cookie;
  if (cookieHeader) {
    const cookies = cookieHeader.split(';').map(c => c.trim());
    for (const c of cookies) {
      if (c.startsWith(`${COOKIE_NAME}=`)) {
        const sid = c.substring(`${COOKIE_NAME}=`.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          break;
        }
      }
      if (!authenticated && COOKIE_NAME !== 'dsh_auth' && c.startsWith('dsh_auth=')) {
        const sid = c.substring('dsh_auth='.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          break;
        }
      }
    }
  }

  if (authenticated && (!accountEnabled(activeSession.user) || (activeSession.internet === 'on' && !internetAllowed(activeSession.user)))) authenticated=false;
  if (!authenticated) {
    socket.destroy();
    return;
  }

  const userSockets=USER_SOCKETS.get(activeSession.user)||new Set();
  USER_SOCKETS.set(activeSession.user,userSockets);userSockets.add(socket);
  socket.once('close',()=>{userSockets.delete(socket);if(!userSockets.size && USER_SOCKETS.get(activeSession.user)===userSockets)USER_SOCKETS.delete(activeSession.user);});

  const internetMode = normalizeInternetMode(activeSession && activeSession.internet);
  const environmentTarget = getEnvironmentTarget(internetMode, activeSession.user);
  if (!environmentTarget) return socket.destroy();
  bindAuthenticatedProxyIdentity(req, activeSession.user, internetMode);

  // Dynamic App Gateway for WebSockets (e.g. Streamlit, Vite HMR, Next.js); only reachable after login
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const appTarget = parseAppTarget(incomingHost, req.url);
  if (appTarget && appTarget.port) {
    if (!auditEvent(appTarget.port === 7681 ? 'terminal.open' : 'application.websocket', activeSession.user, internetMode)) return socket.destroy();
    return forwardWebSocketToLocalApp(appTarget.port, appTarget.targetPath, req, socket, head, environmentTarget.host);
  }

  const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
  getOrMintDshCookie(clientHost, environmentTarget, (err, dshCookie) => {
    // Reconstruct HTTP upgrade request buffer to guarantee dsh-auth cookie is included
    const rawHeaders = req.rawHeaders;
    let hasDshAuthInCookie = false;
    let cookieIdx = -1;
    for (let i = 0; i < rawHeaders.length; i += 2) {
      if (rawHeaders[i].toLowerCase() === 'cookie') {
        cookieIdx = i;
        if (rawHeaders[i + 1].includes('dsh-auth-')) {
          hasDshAuthInCookie = true;
        }
      }
    }

    let upgradeReqText = `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n`;
    for (let i = 0; i < rawHeaders.length; i += 2) {
      const headerKey = rawHeaders[i];
      let headerVal = rawHeaders[i + 1];
      if (headerKey.toLowerCase() === 'host') {
        headerVal = clientHost;
      }
      if (headerKey.toLowerCase() === 'cookie' && dshCookie && !hasDshAuthInCookie) {
        headerVal = headerVal ? `${headerVal}; ${dshCookie}` : dshCookie;
      }
      upgradeReqText += `${headerKey}: ${headerVal}\r\n`;
    }
    if (cookieIdx === -1 && dshCookie) {
      upgradeReqText += `Cookie: ${dshCookie}\r\n`;
    }
    upgradeReqText += `\r\n`;

    const net = require('net');
    const targetSocket = net.connect(environmentTarget.port, environmentTarget.host, () => {
      targetSocket.write(upgradeReqText);
      if (head && head.length > 0) {
        targetSocket.write(head);
      }
      socket.pipe(targetSocket);
      targetSocket.pipe(socket);
    });

    targetSocket.on('error', () => {
      socket.destroy();
    });
  });
});

server.listen(PROXY_PORT, '0.0.0.0', () => {
  console.log(`[AUTH-PROXY] Enterprise DSH Auth Gate running on port ${PROXY_PORT}; secure=${ENVIRONMENT_TARGETS.off.host}:${ENVIRONMENT_TARGETS.off.port}; internet=${ENVIRONMENT_TARGETS.on.host}:${ENVIRONMENT_TARGETS.on.port}`);
});
