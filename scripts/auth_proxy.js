const http = require('http');
const url = require('url');
const fs = require('fs');
const crypto = require('crypto');
const path = require('path');
const { createCourseServer, routeFor } = require('./course_files');
const serveCourse = createCourseServer();
const USER_CREDENTIALS = process.env.DSH_USER_CREDENTIAL_GATEWAY_CONFIG ? require('./credential_gateway').createGateway(process.env.DSH_USER_CREDENTIAL_GATEWAY_CONFIG) : null;
const { hashPassword, verifyPassword, migrateUsers, writeAtomicUsers } = require('./password_store');
const { SessionStore, TTL_MS: SESSION_TTL_MS } = require('./session_store');
const JUPYTER_DEMAND_MODULE = require('./jupyter_on_demand');
const JUPYTER_DEMAND = process.env.DSH_JUPYTER_ON_DEMAND === 'false' ? null : JUPYTER_DEMAND_MODULE.createController();
const {Directory, DirectoryError, normalizeUsername} = require('./ldap_auth');
const LDAP_DIRECTORY = process.env.DSH_LDAP_CONFIG_FILE ? new Directory(process.env.DSH_LDAP_CONFIG_FILE) : null;
const PACKAGE_PORTAL = process.env.DSH_PACKAGES_ROOT ? new (require('./package_portal').PackagePortal)(process.env.DSH_PACKAGES_ROOT) : null;
function projectPackageAccess(){if(PACKAGE_PORTAL)PACKAGE_PORTAL.project(loadUsers(),privateTargetsFor,accountEnabled,internetAllowed);}
setInterval(()=>{try{projectPackageAccess();}catch{}},5000).unref();

const PROXY_PORT = Number(process.env.PORT || 3080);
const MANUAL_DIR = process.env.DSH_MANUAL_DIR || '/opt/dsh/manual';
function serveManual(req, res, pathname) {
  const headers = {'Cache-Control':'no-cache', 'X-Content-Type-Options':'nosniff',
    'Content-Security-Policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"};
  if (!['GET','HEAD'].includes(req.method)) { res.writeHead(405,{...headers,Allow:'GET, HEAD'});return res.end(); }
  if (pathname === '/manual' || pathname === '/manual/') { res.writeHead(302,{...headers,Location:'/manual/DSH_USER_MANUAL.html'});return res.end(); }
  try {
    const name=decodeURIComponent(pathname.slice('/manual/'.length));
    if (!/^[a-zA-Z0-9_./-]+\.(html|md|json|png|svg)$/.test(name) || name.split('/').some(x=>!x || x==='.' || x==='..')) throw Error('Unknown manual');
    const manifest=JSON.parse(fs.readFileSync(path.join(MANUAL_DIR,'manifest.json'),'utf8'));
    if (!Object.hasOwn(manifest.files,name)) { res.writeHead(404,headers);return res.end('Manual page not found.'); }
    const entry=manifest.files[name], root=fs.realpathSync(MANUAL_DIR), file=fs.realpathSync(path.join(root,name));
    if (!file.startsWith(root+path.sep) || entry.bytes>8*1024*1024) throw Error('Invalid manual file');
    const body=fs.readFileSync(file);
    if(body.length!==entry.bytes || crypto.createHash('sha256').update(body).digest('hex')!==entry.sha256)throw Error('Manual integrity mismatch');
    const types={html:'text/html; charset=utf-8',md:'text/plain; charset=utf-8',json:'application/json; charset=utf-8',png:'image/png',svg:'image/svg+xml'};
    res.writeHead(200,{...headers,'Content-Type':types[name.split('.').pop()],'Content-Length':body.length});return res.end(req.method==='HEAD'?undefined:body);
  } catch { res.writeHead(404,headers);return res.end('Manual page unavailable.'); }
}
// Kubernetes may inject DSH_PORT=tcp://<service-ip>:3080 for the Service named
// "dsh". Accept only an explicitly numeric port and otherwise use the internal
// DSH web port, avoiding an invalid 127.0.0.1:NaN proxy target.
const requestedDshPort = process.env.DSH_TARGET_PORT || process.env.DSH_PORT || '';
const DSH_TARGET_PORT = /^\d+$/.test(requestedDshPort) ? Number(requestedDshPort) : 3081;
const DSH_TARGET_HOST = process.env.DSH_HOST || '127.0.0.1';
const USER_ROOT = process.env.WORKSPACE_ROOT || '/workspace/users';
const USER_STORE_PATH = process.env.DSH_USER_STORE_PATH || `${USER_ROOT}/.user_auth.json`;
const USER_SETTINGS_PATH = process.env.DSH_USER_SETTINGS_PATH || `${USER_ROOT}/.user_settings.json`;
const APP_LINKS_PATH = process.env.DSH_APP_LINKS_PATH || path.join(path.dirname(USER_STORE_PATH), 'app-links.json');
const APP_POLICY_PATH = process.env.DSH_APP_POLICY_PATH || path.join(path.dirname(USER_STORE_PATH), 'app-policy.json');
const DEFAULT_APP_LIMIT = 8;
const SITE_APP_LIMIT = 4096; // Registry safety bound, not a user approval tier.
const APP_CONNECTIONS = new Map();
const EXTERNAL_PROXY = require('./external_upstream');
const LOCAL_SHARED_PROXY = require('./local_shared_proxy');
const {sharedTarget,privateLocalPort,isSharedPolicy,appVisitorAllowed}=require('./app_signin');
const EXTERNAL_LOOKUP=process.env.DSH_EXTERNAL_DNS_SERVERS?require('./external_dns').createLookup(process.env.DSH_EXTERNAL_DNS_SERVERS):undefined;
function externalPolicies() {
  const file=process.env.DSH_EXTERNAL_TARGETS_FILE;
  if(!file)return {};
  const raw=fs.readFileSync(file);if(raw.length>131072)throw Error('External policy too large');
  const data=JSON.parse(raw);if(!data||Array.isArray(data)||typeof data!=='object')throw Error('Invalid external policies');
  return data;
}
function externalAppTarget(alias,user,mode) {
  try {return EXTERNAL_PROXY.resolveTarget(appLinks()[alias],user,mode,externalPolicies());}catch{return null;}
}
function customAppAvailable(alias,user,mode) {return Boolean(customAppPort(alias,user,mode)||externalAppTarget(alias,user,mode));}
// Shared apps use the owner's saved target, never a visitor's runtime.
// Legacy mappings and management applications remain owner-only.
function sharedExternalApp(alias,visitor) {
  const app=gatedAliasRecoveryContext(alias);
  if(!app||!isSharedPolicy(app.visitorPolicy)||!accountEnabled(visitor)||!appVisitorAllowed(app,visitor,loadUsers()[visitor]))return null;
  let selection;try{selection=sharedTarget(appLinks()[alias]);}catch{return null;}
  if(selection.type==='port'){
    const runtime=getEnvironmentTarget(app.internet,app.owner),port=customAppPort(alias,app.owner,app.internet);
    if(!runtime||port!==selection.port||!validAppPort(port))return null;
    const stamp=app.stamp+':'+crypto.createHash('sha256').update(JSON.stringify(runtime)).digest('hex');
    return {app:{...app,stamp},port,runtime};
  }
  const target=externalAppTarget(alias,app.owner,app.internet);
  return target?{app,target}:null;
}
function sharedAppStillAuthorized(alias,active,stamp) {
  const current=sharedExternalApp(alias,active.user);
  return Boolean(current&&current.app.stamp===stamp&&
    active.accountStamp===sessionAccountStamp(active.user)&&
    (active.internet!=='on'||internetAllowed(active.user))&&
    Date.now()<active.created+SESSION_TTL_MS&&[...SESSIONS.values()].includes(active));
}
function monitorSharedApp(alias,active,stamp,connection) {
  const timer=setInterval(()=>{try{if(!sharedAppStillAuthorized(alias,active,stamp))connection.destroy();}catch{connection.destroy();}},2000);
  timer.unref();connection.once('close',()=>clearInterval(timer));
}
function externalProxyOptions(req,target,authorize) {
  const host=String(req.headers['x-forwarded-host']||req.headers.host||'').toLowerCase();
  if(!appHostName(host))throw Error('External mappings require an application hostname');
  return {target,publicOrigin:'https://'+host,protectedCookies:[COOKIE_NAME,'dsh_auth'],lookup:EXTERNAL_LOOKUP,authorize};
}
function localSharedOptions(req,shared,active) {
  const alias=appHostName(req.headers['x-forwarded-host']||req.headers.host);
  if(!alias||!shared.port||!shared.runtime)throw Error('Shared local application unavailable');
  return {host:shared.runtime.host,port:shared.port,publicOrigin:'https://'+alias+'.'+APP_DOMAIN,
    protectedCookies:[COOKIE_NAME,'dsh_auth'],authorize:()=>sharedAppStillAuthorized(alias,active,shared.app.stamp)};
}

// Explicit public aliases only. Owner configuration remains behind normal auth+CSRF.
function publicApp(alias) {
 const e=appLinks()[alias];if(!e||e.enabled===false||e.accessMode!=='public'||!['off','on'].includes(e.publicEnvironment)||!accountEnabled(e.owner))return null;
 const mode=e.publicEnvironment;if(mode==='on'&&!internetAllowed(e.owner))return null;
 const inventory=appHostnameState(alias);if(process.env.DSH_APP_INVENTORY_FILE&&(!inventory.ready||!inventory.available))return null;
 const external=externalAppTarget(alias,e.owner,mode),port=customAppPort(alias,e.owner,mode);
 if(!external&&(!port||[7681,8888].includes(port)))return null;
 return {entry:e,mode,external,port};
}
function publicAppHeaders(req) {
 req.headers=EXTERNAL_PROXY.cleanHeaders(req.headers,[COOKIE_NAME,'dsh_auth']);
 req.rawHeaders=Object.entries(req.headers).flatMap(([k,v])=>[k,String(v)]);
}
function handlePublicAlias(req,res,socket,head) {
 const alias=appHostName(req.headers['x-forwarded-host']||req.headers.host);if(!alias)return false;
 const a=publicApp(alias);if(!a)return false;
 if(req.headers.origin&&req.headers.origin!=='https://'+alias+'.'+APP_DOMAIN){if(socket)rejectUpgrade(socket,403,'ORIGIN_DENIED');else{res.writeHead(403);res.end('Cross-origin application request refused');}return true;}
 if(!auditEvent('application.public.'+(socket?'websocket':'http'),a.entry.owner,a.mode,undefined,{name:alias,outcome:'requested'})){if(socket)rejectUpgrade(socket,503,'AUDIT_UNAVAILABLE');else{res.writeHead(503);res.end('Audit unavailable');}return true;}
 const connection=socket||res;trackAppConnection(alias,connection);
 const stamp=JSON.stringify(a.entry);const timer=setInterval(()=>{try{const current=publicApp(alias);if(!current||JSON.stringify(current.entry)!==stamp)connection.destroy();}catch{connection.destroy();}},2000);timer.unref();connection.once('close',()=>clearInterval(timer));
 if(a.external){const options=externalProxyOptions(req,a.external);const promise=socket?EXTERNAL_PROXY.proxyWebSocket(req,socket,head,options):EXTERNAL_PROXY.proxyHTTP(req,res,options);promise.catch(()=>{if(socket)socket.destroy();else if(!res.headersSent){res.writeHead(502);res.end('Application unavailable');}else res.destroy();});return true;}
 const runtime=getEnvironmentTarget(a.mode,a.entry.owner);if(!runtime){if(socket)rejectUpgrade(socket,503,'ENVIRONMENT_UNAVAILABLE');else{res.writeHead(503);res.end('Application runtime unavailable');}return true;}
 // A visited application keeps its owner's workspace active; a stopped one waits.
 if(SESSION_DEMAND){SESSION_DEMAND.touch(runtime);if(RUNTIME_WAITING.includes(SESSION_DEMAND.state(runtime).state)){if(socket)rejectUpgrade(socket,503,'RUNTIME_STARTING');else{res.writeHead(503,{'Retry-After':'10','Cache-Control':'no-store'});res.end('This application\'s workspace is starting. Please retry shortly.');}return true;}}
 publicAppHeaders(req);
 if(socket){req.headers.connection='Upgrade';req.headers.upgrade='websocket';req.rawHeaders.push('Connection','Upgrade','Upgrade','websocket');}
 if(socket)forwardWebSocketToLocalApp(a.port,req.url,req,socket,head,runtime.host);else forwardToLocalApp(a.port,req.url,req,res,runtime.host);
 return true;
}

// A browser arriving with an unrelated platform session can explicitly sign in
// for this registered app. Never grant access or silently change its environment.
function gatedAliasRecoveryContext(alias) {
  if(!APP_SIGNIN)return null;
  try {
    const app=APP_SIGNIN.mapping(alias);
    if(!accountEnabled(app.owner)||(app.internet==='on'&&!internetAllowed(app.owner))||!customAppAvailable(alias,app.owner,app.internet))return null;
    const inventory=appHostnameState(alias);
    if(process.env.DSH_APP_INVENTORY_FILE&&(!inventory.ready||!inventory.available))return null;
    return app;
  } catch {return null;}
}
function offerGatedAliasSignIn(req,res,alias) {
  if(!gatedAliasRecoveryContext(alias))return false;
  const login='https://'+process.env.DSH_TRUSTED_HOST+'/login?app='+encodeURIComponent(alias);
  if(/^\/api(?:\/|$)/.test(url.parse(req.url).pathname||'')){
    res.writeHead(403,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
    res.end(JSON.stringify({error:'APP_ACCESS_REQUIRED',message:'Sign in with an account authorized for this application.',loginUrl:login}));return true;
  }
  if(req.method!=='GET'||!String(req.headers.accept||'').toLowerCase().includes('text/html')||(req.headers['sec-fetch-mode']&&req.headers['sec-fetch-mode']!=='navigate')||(req.headers['sec-fetch-dest']&&req.headers['sec-fetch-dest']!=='document'))return false;
  res.writeHead(303,{Location:login,'Cache-Control':'no-store'});
    res.end();return true;
}

function handleExternalAlias(req,res) {
  const alias=appHostName(req.headers['x-forwarded-host']||req.headers.host);
  if(!alias)return false;
  const entry=appLinks()[alias];
  if(!isSharedPolicy(entry?.visitorPolicy)&&!Object.values(entry?.targets||{}).some(t=>t?.type==='external'))return false;
  let active=null;
  for(const value of (req.headers.cookie||'').split(';').map(x=>x.trim())){
    for(const name of [COOKIE_NAME,'dsh_auth'])if(value.startsWith(name+'=')){
      const sid=value.slice(name.length+1);if(SESSIONS.has(sid)){active=SESSIONS.get(sid);break;}
    }
    if(active)break;
  }
  const login='https://'+process.env.DSH_TRUSTED_HOST+'/login'+(APP_SIGNIN?'?app='+encodeURIComponent(alias):'');
  if(!active||!accountEnabled(active.user)||(active.internet==='on'&&!internetAllowed(active.user))){
    if(/^\/api(?:\/|$)/.test(url.parse(req.url).pathname||'')){res.writeHead(401,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify({error:'AUTHENTICATION_REQUIRED',loginUrl:login}));}
    else{res.writeHead(303,{Location:login,'Cache-Control':'no-store'});res.end();}
    return true;
  }
  const shared=sharedExternalApp(alias,active.user);
  if(isSharedPolicy(entry.visitorPolicy)&&!shared){res.writeHead(404);res.end('Shared application unavailable.');return true;}
  const mode=shared?shared.app.internet:normalizeInternetMode(active.internet);
  // The same alias may use an external target in one environment and a local
  // port in the other. Let the normal owned local route handle the latter.
  if(!shared&&entry.targets?.[mode]?.type!=='external'&&customAppPort(alias,active.user,mode))return false;
  const target=shared?shared.target:externalAppTarget(alias,active.user,mode),inventory=appHostnameState(alias);
  if((!target&&!shared?.port)||(process.env.DSH_APP_INVENTORY_FILE&&(!inventory.ready||!inventory.available))){if(!target&&offerGatedAliasSignIn(req,res,alias))return true;res.writeHead(404);res.end('Application unavailable for this account and environment.');return true;}
  if(!auditEvent(shared?.port?'application.local.http':'application.external.http',active.user,mode,undefined,{name:alias,owner:shared?.app.owner||entry.owner,outcome:'requested'})){res.writeHead(503);res.end('Audit storage unavailable.');return true;}
  trackAppConnection(alias,res);
  const connections=SESSION_SOCKETS.get(active)||new Set();SESSION_SOCKETS.set(active,connections);connections.add(res);
  if(shared)monitorSharedApp(alias,active,shared.app.stamp,res);
  const timer=setTimeout(()=>res.destroy(),Math.max(1,active.created+SESSION_TTL_MS-Date.now()));timer.unref();
  res.once('close',()=>{clearTimeout(timer);connections.delete(res);});
  if(shared?.port){
    try{LOCAL_SHARED_PROXY.proxyHTTP(req,res,localSharedOptions(req,shared,active));}
    catch(error){res.writeHead(error.status||403);res.end('Shared application request refused');}
    return true;
  }
  EXTERNAL_PROXY.proxyHTTP(req,res,externalProxyOptions(req,target,shared?()=>sharedAppStillAuthorized(alias,active,shared.app.stamp):undefined)).catch(error=>{if(!res.headersSent){res.writeHead(error.status||502);res.end('External application unavailable.');}else res.destroy();});
  return true;
}
const APP_DOMAIN = (process.env.DSH_APP_DOMAIN || '').toLowerCase();
const APP_SIGNIN = process.env.DSH_APP_LOGIN_ENABLED === 'true' ? new (require('./app_signin').AppSignIn)({domain:APP_DOMAIN, issuer:'https://'+process.env.DSH_TRUSTED_HOST, mappings:appLinks, allowedName:validAppName, testIssuer:process.env.DSH_TEST_ISSUER==='true', ldapEnabled:Boolean(LDAP_DIRECTORY)}) : null;
if(APP_DOMAIN && !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(APP_DOMAIN))throw Error('Invalid approved app domain');
function appHostnameState(name) {
  const file=process.env.DSH_APP_INVENTORY_FILE;
  if(!APP_DOMAIN)return {available:true,ready:false};
  if(!file)return {available:true,ready:false}; // Operator-managed exact-host setup.
  try {
    const data=JSON.parse(fs.readFileSync(file,'utf8')),at=Date.parse(data.observedAt);
    if(data.domain!==APP_DOMAIN||!Number.isFinite(at)||Date.now()-at>180000||at>Date.now()+30000||!Array.isArray(data.reservedNames)||data.wildcardConflict)throw Error('Stale inventory');
    if(data.allowedNames!==undefined&&(!Array.isArray(data.allowedNames)||data.allowedNames.some(n=>typeof n!=='string')))throw Error('Invalid allowed names');
    return {available:!data.reservedNames.includes(name)&&(!data.allowedNames||data.allowedNames.includes(name)),ready:data.wildcardReady===true};
  }catch{return {available:false,ready:false,error:'Hostname inventory is temporarily unavailable. Existing path URLs remain usable.'};}
}
function appHostName(host) {
  const value=String(host||'').toLowerCase().split(':')[0];
  if(value===(process.env.DSH_TRUSTED_HOST||'').toLowerCase().split(':')[0])return null;
  if(!APP_DOMAIN||!value.endsWith('.'+APP_DOMAIN))return null;
  const name=value.slice(0,-APP_DOMAIN.length-1);
  return validAppName(name)?name:null;
}
const APP_LINK_READ_STAMPS=new WeakMap();
function appLinks() {
  if (!fs.existsSync(APP_LINKS_PATH)) {const value={};APP_LINK_READ_STAMPS.set(value,null);return value;}
  const bytes=fs.readFileSync(APP_LINKS_PATH),value=JSON.parse(bytes);
  if (!value || typeof value!=='object' || Array.isArray(value)) throw Error('Invalid app links');
  APP_LINK_READ_STAMPS.set(value,crypto.createHash('sha256').update(bytes).digest('hex'));
  return value;
}
function saveAppLinks(value) {
  fs.mkdirSync(path.dirname(APP_LINKS_PATH),{recursive:true,mode:0o700});
  const tmp=APP_LINKS_PATH+'.tmp-'+crypto.randomBytes(8).toString('hex'),lock=APP_LINKS_PATH+'.lock';let fd,lockFd;
  try {
    lockFd=fs.openSync(lock,'wx',0o600);
    if(!APP_LINK_READ_STAMPS.has(value))throw Error('Untracked application registry update');
    const current=fs.existsSync(APP_LINKS_PATH)?crypto.createHash('sha256').update(fs.readFileSync(APP_LINKS_PATH)).digest('hex'):null;
    if(current!==APP_LINK_READ_STAMPS.get(value))throw Error('Application registry changed; refresh before saving');
    fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(value));fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,APP_LINKS_PATH);
    if(process.platform!=='win32'){const dir=fs.openSync(path.dirname(APP_LINKS_PATH),'r');try{fs.fsyncSync(dir);}finally{fs.closeSync(dir);}}
  }
  finally {
    if(fd!==undefined)fs.closeSync(fd);if(fs.existsSync(tmp))fs.unlinkSync(tmp);
    if(lockFd!==undefined){const owned=fs.fstatSync(lockFd);fs.closeSync(lockFd);const actual=fs.lstatSync(lock);if(actual.dev!==owned.dev||actual.ino!==owned.ino)throw Error('Registry lock ownership changed');fs.unlinkSync(lock);}
  }
}
function appPolicy() {
  if(!fs.existsSync(APP_POLICY_PATH))return {limits:{}};
  const p=JSON.parse(fs.readFileSync(APP_POLICY_PATH,'utf8'));
  if(!p || !p.limits || typeof p.limits!=='object' || Array.isArray(p.limits) || Object.entries(p.limits).some(([u,n])=>!(/^[a-z0-9_.-]{3,30}$/.test(u))||!Number.isInteger(n)||n<0||n>SITE_APP_LIMIT))throw Error('Invalid app policy');
  return p;
}
function appLimit(user,policy=appPolicy()) {return Object.hasOwn(policy.limits,user)?policy.limits[user]:DEFAULT_APP_LIMIT;}
function saveAppPolicy(value) {
  fs.mkdirSync(path.dirname(APP_POLICY_PATH),{recursive:true,mode:0o700});
  const tmp=APP_POLICY_PATH+'.tmp-'+crypto.randomBytes(8).toString('hex');let fd;
  try {fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(value));fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,APP_POLICY_PATH);}
  finally {if(fd!==undefined)fs.closeSync(fd);if(fs.existsSync(tmp))fs.unlinkSync(tmp);}
}
function trackAppConnection(name,connection) {
  if(!name)return;
  const set=APP_CONNECTIONS.get(name)||new Set();APP_CONNECTIONS.set(name,set);set.add(connection);
  connection.once('close',()=>{set.delete(connection);if(!set.size&&APP_CONNECTIONS.get(name)===set)APP_CONNECTIONS.delete(name);});
}
function closeAppConnections(name) {for(const connection of APP_CONNECTIONS.get(name)||[])connection.destroy();APP_CONNECTIONS.delete(name);}
function adminApps() {
  const all=appLinks(),users=loadUsers(),policy=appPolicy();
  return {serviceTargets:registeredServiceTargets().map(({id,label,owner})=>({id,label,owner})),managedServices:serviceInventory(),defaultLimit:DEFAULT_APP_LIMIT,siteLimit:SITE_APP_LIMIT,totalNames:Object.keys(all).length,
    accounts:Object.keys(users).sort().map(user=>({user,enabled:users[user].disabled!==true,internetAllowed:internetAllowed(user),limit:appLimit(user,policy),used:Object.values(all).filter(e=>e.owner===user).length})),
    apps:Object.entries(all).map(([name,e])=>{const state=appHostnameState(name);return {name,owner:e.owner,enabled:e.enabled!==false,ports:{...(validAppPort(e.ports?.off)?{off:e.ports.off}:{}),...(validAppPort(e.ports?.on)?{on:e.ports.on}:{})},hostname:APP_DOMAIN?name+'.'+APP_DOMAIN:null,hostnameReady:state.available&&state.ready,updatedAt:e.updatedAt||null,updatedBy:e.updatedBy||null};})};
}

const APP_SERVICES_ROOT = process.env.DSH_APP_SERVICES_ROOT || '';
function registeredServiceTargets(){
 const file=process.env.DSH_SERVICE_TARGETS_FILE;if(!file)return [];
 const raw=fs.readFileSync(file);if(raw.length>16384)throw Error('Service target registry too large');
 const rows=JSON.parse(raw);if(!Array.isArray(rows)||rows.length>8)throw Error('Invalid service target registry');
 const ids=new Set(),hosts=new Set();for(const t of rows){
  if(!t||['id','label','owner','host'].some(k=>typeof t[k]!=='string')||Object.keys(t).some(k=>!['id','label','owner','host','enabled'].includes(k))||!/^[-a-z0-9]{3,30}$/.test(t.id)||t.id==='main'||ids.has(t.id)||!/^[-a-zA-Z0-9 ]{1,40}$/.test(t.label)||!/[a-z0-9]/.test(t.label)||!/^[-a-z0-9_.]{3,30}$/.test(t.owner)||!/^[-a-z0-9.]{3,253}$/.test(t.host)||hosts.has(t.host)||typeof t.enabled!=='boolean')throw Error('Invalid service target');
  ids.add(t.id);hosts.add(t.host);
 }return rows;
}
function serviceTarget(user,mode,scope='main'){
 if(scope==='main'){const target=getEnvironmentTarget(mode,user);if(!target)throw Error('No private runtime');return target;}
 const target=registeredServiceTargets().find(t=>t.id===scope);
 if(!target||target.owner!==user||mode!=='on')throw Error('Choose the registered owner and Internet environment');
 return target;
}
function mainServiceAssignments(){return Object.keys(loadUsers()).flatMap(user=>['off','on'].map(mode=>({user,mode,target:'main'})));}
function serviceAssignments(){return [...mainServiceAssignments(),...registeredServiceTargets().map(t=>({user:t.owner,mode:'on',target:t.id,label:t.label}))];}
function serviceFolder(user,mode,scope='main') {
 if(!APP_SERVICES_ROOT)throw Error('Service supervision is not installed');
 const target=serviceTarget(user,mode,scope);
 return path.join(APP_SERVICES_ROOT,crypto.createHash('sha256').update(target.host+'|'+mode).digest('hex').slice(0,24));
}
function readServices(user,mode,scope='main') {
  const folder=serviceFolder(user,mode,scope);
  if(!fs.existsSync(path.join(folder,'ready')))throw Error('Supervisor not provisioned');
  const file=path.join(folder,'config.json');
  if(fs.statSync(file).size>16384)throw Error('Service control exceeds bound');
  const v=JSON.parse(fs.readFileSync(file,'utf8'));if(!v||typeof v.allowed!=='boolean'||!v.services||Array.isArray(v.services)||Object.keys(v.services).length>4)throw Error('Invalid service definitions');
  return v;
}
function writeServices(user,mode,value,scope='main') {
  const file=path.join(serviceFolder(user,mode,scope),'config.json'),tmp=file+'.'+crypto.randomBytes(8).toString('hex');
  let fd;try{fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(value));fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,file);}finally{if(fd!==undefined)fs.closeSync(fd);if(fs.existsSync(tmp))fs.unlinkSync(tmp);}
}
function servicesAllowed(user,mode,scope='main'){return scope==='main'?(accountEnabled(user)&&(mode==='off'||internetAllowed(user))):serviceTarget(user,mode,scope).enabled;}
function reconcileServices(){
 if(!APP_SERVICES_ROOT)return;const main=mainServiceAssignments(),recognized=new Set();
 // Registry problems must never prevent main-account revocation.
 for(const a of main){try{recognized.add(path.basename(serviceFolder(a.user,a.mode)));const d=readServices(a.user,a.mode),allowed=servicesAllowed(a.user,a.mode);if(d.allowed!==allowed){d.allowed=allowed;writeServices(a.user,a.mode,d);}}catch{}}
 try{for(const t of registeredServiceTargets()){const user=t.owner,mode='on';recognized.add(path.basename(serviceFolder(user,mode,t.id)));const d=readServices(user,mode,t.id),allowed=servicesAllowed(user,mode,t.id);if(d.allowed!==allowed){d.allowed=allowed;writeServices(user,mode,d,t.id);}}}catch{}
 // Removed/invalid registrations lose execution approval. Control directories are
 // gateway-owned; no app can create these policy files or their parent entries.
 for(const name of fs.readdirSync(APP_SERVICES_ROOT)){if(!/^[a-f0-9]{24}$/.test(name)||recognized.has(name))continue;try{const file=path.join(APP_SERVICES_ROOT,name,'config.json');if(fs.statSync(file).size>16384)continue;const d=JSON.parse(fs.readFileSync(file));if(d.allowed===true){d.allowed=false;const tmp=file+'.'+crypto.randomBytes(8).toString('hex');try{fs.writeFileSync(tmp,JSON.stringify(d),{flag:'wx',mode:0o600});fs.renameSync(tmp,file);}finally{if(fs.existsSync(tmp))fs.unlinkSync(tmp);}}}catch{}}
}
setInterval(()=>{try{reconcileServices();}catch{}},5000).unref();
// App status is untrusted. Open once without following links or blocking on pipes,
// then bound reads from that same regular-file descriptor to avoid stat/open races.
function readServiceStatus(file){
 let fd;try{
  fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  const st=fs.fstatSync(fd);if(!st.isFile()||st.size>65536)throw Error('Invalid status file');
  const body=Buffer.alloc(65537);let used=0,n;
  while(used<body.length&&(n=fs.readSync(fd,body,used,body.length-used,null))>0)used+=n;
  if(used>65536)throw Error('Status exceeds bound');
  return JSON.parse(body.subarray(0,used).toString('utf8'));
 }finally{if(fd!==undefined)fs.closeSync(fd);}
}
function observedServiceStatus(entry,status,fresh){
 const observed=fresh&&Array.isArray(status.services)?status.services.find(v=>v.name===entry.name):undefined;
 const phase=observed?(['running','disabled','access-disabled','backoff','start-failed','port-in-use'].includes(observed.phase)?observed.phase:'pending'):'unknown';
 // Zero-failure backoff follows an occupied-port check in the supervisor.
 // Failed launches/exits increment restarts; keep that recovery distinguishable.
 const waiting=entry.kind==='jupyter'&&entry.name==='jupyter'&&entry.port===8888&&entry.enabled===true&&observed?.generation===entry.generation&&(phase==='port-in-use'||(phase==='backoff'&&observed.restarts===0));
 const labels={running:'Running',disabled:'Stopped','access-disabled':'Environment access disabled',backoff:'Recovery retry pending','start-failed':'Startup failed','port-in-use':'Waiting for occupied port',pending:'Status pending',unknown:'Status unavailable'};
 return {phase,statusLabel:waiting?'Waiting for existing Jupyter':labels[phase]};
}
function serviceAccessState(user,mode,target){
 if(servicesAllowed(user,mode,target))return 'allowed';
 if(target==='main'&&!accountEnabled(user))return 'account-disabled';
 if(target==='main'&&mode==='on'&&!internetAllowed(user))return 'internet-approval-pending';
 return 'environment-disabled';
}
const legacyJupyterChecks=new WeakMap(), jupyterPortChecks=new Map();
function describeManagedService(entry,status,fresh,identity){
 const service={name:entry.name,kind:entry.kind,cwd:entry.cwd,argv:entry.argv,port:entry.port,enabled:entry.enabled,generation:entry.generation,...observedServiceStatus(entry,status,fresh)};
 const observed=fresh&&Array.isArray(status.services)?status.services.find(v=>v.name===entry.name):undefined;
 if(identity.allowed&&entry.enabled&&entry.kind==='jupyter'&&entry.name==='jupyter'&&entry.port===8888&&['backoff','port-in-use'].includes(service.phase)&&observed&&observed.generation===undefined&&observed.restarts===undefined)
  legacyJupyterChecks.set(service,{...identity,observedAt:status.observedAt,signature:crypto.createHash('sha256').update(JSON.stringify(entry)).digest('hex')});
 return service;
}
function listeningJupyterPort(host){
 const existing=jupyterPortChecks.get(host);if(existing&&Date.now()-existing.at<500)return existing.promise;
 if(jupyterPortChecks.size>=128)jupyterPortChecks.delete(jupyterPortChecks.keys().next().value);
 const promise=new Promise(resolve=>{let socket,done=false;const finish=v=>{if(done)return;done=true;clearTimeout(timer);if(socket)socket.destroy();resolve(v);};const timer=setTimeout(()=>finish(false),350);try{socket=require('net').connect({host,port:8888},()=>finish(true));socket.once('error',()=>finish(false));}catch{finish(false);}});
 jupyterPortChecks.set(host,{at:Date.now(),promise});return promise;
}
async function clarifyLegacyJupyterLabels(rows){
 const checks=[];for(const row of rows)for(const service of row.services){const evidence=legacyJupyterChecks.get(service);if(evidence)checks.push({row,service,evidence});}
 // At most eight concurrent short, data-free connections to configured internal
 // Jupyter ports. No user-supplied destination, kernel request, or command runs.
 for(let offset=0;offset<checks.length;offset+=8)await Promise.all(checks.slice(offset,offset+8).map(async({row,service,evidence})=>{
  try{
   const now=Date.now()/1000;if(!Number.isFinite(evidence.observedAt)||now-evidence.observedAt>=30||evidence.observedAt>now+2||!servicesAllowed(evidence.user,evidence.mode,evidence.target))return;
   const current=readServices(evidence.user,evidence.mode,evidence.target),entry=current.services[service.name],file=path.join(serviceFolder(evidence.user,evidence.mode,evidence.target),'config.json');
   if(!current.allowed||!entry||crypto.createHash('sha256').update(JSON.stringify(entry)).digest('hex')!==evidence.signature||fs.statSync(file).mtimeMs/1000>evidence.observedAt)return;
   const target=serviceTarget(evidence.user,evidence.mode,evidence.target);if(!await listeningJupyterPort(target.host))return;
   const after=readServices(evidence.user,evidence.mode,evidence.target);
   if(Date.now()/1000-evidence.observedAt>=30||!servicesAllowed(evidence.user,evidence.mode,evidence.target)||!after.allowed||!after.services[service.name]||crypto.createHash('sha256').update(JSON.stringify(after.services[service.name])).digest('hex')!==evidence.signature||fs.statSync(file).mtimeMs/1000>evidence.observedAt||serviceTarget(evidence.user,evidence.mode,evidence.target).host!==target.host)return;
   service.statusLabel='Waiting for existing Jupyter';
  }catch{}
 }));
 return rows;
}
function serviceInventory(){
  if(!APP_SERVICES_ROOT)return [];
  const rows=[];for(const {user,mode,target,label}of serviceAssignments()){
    try {const desired=readServices(user,mode,target);let status={};try{const f=path.join(serviceFolder(user,mode,target),'status','status.json');status=readServiceStatus(f);}catch{}
      const fresh=Number.isFinite(status.observedAt)&&Math.abs(Date.now()/1000-status.observedAt)<30;
      rows.push({user,mode,target,label,available:true,allowed:servicesAllowed(user,mode,target),accessState:serviceAccessState(user,mode,target),services:Object.values(desired.services).map(e=>describeManagedService(e,status,fresh,{user,mode,target,allowed:servicesAllowed(user,mode,target)}))});
    }catch{rows.push({user,mode,target,label,available:false,services:[]});}
  }return rows;
}
function serviceChange(owner,mode,f,scope='main'){
 serviceTarget(owner,mode,scope);
 const desired=readServices(owner,mode,scope),name=f.get('service'),action=f.get('action');
 if(!/^[a-z][a-z0-9-]{2,39}$/.test(name||''))throw Error('Use a valid service name');
 if(action==='service-save'){
  const kind=f.get('kind'),cwd=f.get('cwd')||'/workspace';let argv,port;
  if(!/^\/workspace(?:\/[^\x00\r\n]*)?$/.test(cwd)||cwd.split('/').includes('..')||cwd.length>256)throw Error('Working directory must be inside /workspace');
  if(kind==='jupyter'){if(name!=='jupyter')throw Error('Notebook service name is jupyter');argv=['jupyter','lab'];port=8888;}
  else if(kind==='command'){
   if(scope==='main'){const link=appLinks()[name];port=link?.ports?.[mode];if(link?.owner!==owner||!validAppPort(port))throw Error('Save an owned app URL in that environment first');}
   else {const raw=f.get('port');if(!/^[0-9]{4,5}$/.test(raw||''))throw Error('Choose an application port');port=Number(raw);if(!validAppPort(port)||[7681,8888].includes(port))throw Error('Choose a non-management application port');}
   argv=JSON.parse(f.get('argv')||'null');
   if(!Array.isArray(argv)||argv.length<2||argv.length>32||argv.some(v=>typeof v!=='string'||v.length>512||/[\x00\r\n]/.test(v))||JSON.stringify(argv).length>2048||!['python3','node','npm'].includes(argv[0]))throw Error('Use a python3/node workspace script, npm run script, or python3 -m http.server argv array');
   if(argv[0]==='npm'&&(argv[1]!=='run'||!/^[a-zA-Z0-9:_-]{1,64}$/.test(argv[2]||'')))throw Error('Only npm run SCRIPT is supported');
   if(argv[0]==='python3'&&argv[1]==='-m'&&argv[2]!=='http.server')throw Error('Only http.server is a supported built-in module');
   if(argv[0]==='node'&&argv[1].startsWith('-'))throw Error('Use a workspace script');
  }else throw Error('Choose Jupyter or command');
  if(!Object.hasOwn(desired.services,name)&&Object.keys(desired.services).length>=4)throw Error('Four managed services maximum per environment');
  desired.services[name]={name,kind,cwd,argv,port,enabled:desired.services[name]?.enabled===true,generation:(desired.services[name]?.generation||0)+1};
 }else{
  if(!Object.hasOwn(desired.services,name))throw Error('Managed service not found');
  if(action==='service-delete')delete desired.services[name];
  else if(action!=='service-start'||desired.services[name].enabled!==true){
   // Start is declarative: an enabled service is already supervised. Only an
   // explicit Restart (or a disabled-to-enabled transition) changes generation.
   desired.services[name].enabled=action!=='service-stop';desired.services[name].generation++;
  }
 }
 desired.allowed=servicesAllowed(owner,mode,scope);return desired;
}

function validAppName(name) {return typeof name==='string' && /^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(name) && !/^\d+$/.test(name) && !/^dsh(?:$|[-0-9])/.test(name) && !['terminal','jupyter','dashboard','streamlit','fastapi','web','api','ttyd','constructor','prototype'].includes(name);}
function validAppPort(port) {return Number.isInteger(port)&&port>=1024&&port<=65535&&![PROXY_PORT,DSH_TARGET_PORT,3080,3081,4000,4001].includes(port);}
function customAppPort(alias,user,mode) {
  const entry=appLinks()[alias];
  return entry && entry.enabled!==false && entry.owner===user && validAppPort(entry.ports?.[mode]) ? entry.ports[mode] : null;
}
function renderApplications() {return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>My applications</title><style>body{font:16px system-ui;max-width:900px;margin:40px auto;padding:20px;line-height:1.6;background:#0b1220;color:#eef}a{color:#8cf}input,button{font:inherit;padding:9px;margin:5px}li{margin:14px 0}fieldset label{display:inline-block;margin:5px 12px 5px 0}fieldset input{padding:0;margin:5px}button{cursor:pointer}</style><h1>My applications</h1><p><a href="/">DSH</a> · <a href="/terminal">Web Terminal</a> · <a href="/proxy/8888/lab">JupyterLab</a> · <a href="/manual/APP_URLS_AND_INGRESS.html">URL guide</a> · <a href="/packages">My Python environments</a></p><p>Choose a name for a local application port or an external HTTPS application. Choose whether visitors must sign into DSH or can open this application publicly. Application login remains separate. Public access exposes only the selected mapping, not DSH management. This does not start an application or enable Internet access.</p><p id="domainHint"></p><p id="quota"></p><form id="appForm"><label>Name <input id="appName" pattern="[a-z0-9-]{3,63}" maxlength="63" required></label><label>Target <select id="targetType"><option value="port">Local application port</option><option value="external">External HTTPS application</option></select></label><label>Visitor access <select id="accessMode"><option value="authenticated">Require DSH sign-in (default)</option><option value="public">Public access — no DSH sign-in</option></select></label><label>Authenticated visitors <select id="visitorPolicy"><option value="signed-in-users">All authenticated users (local and AD / LDAP)</option><option value="local-users">All local DSH users</option><option value="ldap-users">All AD / LDAP users</option><option value="selected-local-users">Selected local DSH users</option><option value="owner-only">Owner only — private application</option><option value="selected-users" hidden>Existing selected accounts (legacy)</option></select></label><p id="visitorPolicyHelp" role="status"></p><fieldset id="selectedUsersWrap" hidden><legend>Select local DSH users</legend><div id="localUserChoices"></div><p id="legacySelection"></p></fieldset><label>External URL <input id="targetUrl" type="url" placeholder="https://app.example.org/"></label><label>Port <input id="appPort" type="number" min="1024" max="65535" value="8888" required></label><button type="button" id="check" disabled>Check name</button><button id="saveApp" disabled>Save URL</button><button type="button" id="newApp">New application / cancel edit</button></form><p id="status" role="status"></p><ul id="links"></ul><script>const el=id=>document.getElementById(id);let token='',directory=[],entries=[],editing=false,wasRestricted=true;const status=el('status');
function selected(){return [...el('localUserChoices').querySelectorAll('input:checked')].map(x=>x.value)}
function drawChoices(values=[]){el('localUserChoices').replaceChildren();for(const user of directory){const label=document.createElement('label'),box=document.createElement('input');box.type='checkbox';box.value=user;box.checked=values.includes(user);label.append(box,document.createTextNode(user));el('localUserChoices').append(label)}el('legacySelection').textContent=values.filter(u=>!directory.includes(u)).length?'Existing non-local or unavailable recipients are preserved for this legacy audience. Choose a new audience explicitly to replace it.':'';}
function syncVisitorPolicy(){const v=el('visitorPolicy'),management=el('targetType').value==='port'&&[3080,3081,4000,4001,7681,8888].includes(Number(el('appPort').value)),restricted=management||el('accessMode').value==='public';if(restricted)v.value='owner-only';else if(wasRestricted&&!editing)v.value='signed-in-users';v.disabled=restricted;wasRestricted=restricted;el('selectedUsersWrap').hidden=!['selected-local-users','selected-users'].includes(v.value);for(const box of el('localUserChoices').querySelectorAll('input[type=checkbox]'))box.disabled=v.value==='selected-users';el('visitorPolicyHelp').textContent=management?'JupyterLab, terminals and management ports are owner-only.':restricted?'Authenticated audience does not apply to public links.':'Only this application is shared; your workspace, terminal and other applications remain private.';}
for(const id of ['visitorPolicy','targetType','accessMode'])el(id).onchange=syncVisitorPolicy;el('appPort').oninput=syncVisitorPolicy;
function edit(e){editing=true;el('appName').value=e.name;el('appName').readOnly=true;el('targetType').value=e.type;el('appPort').value=e.port||8888;el('targetUrl').value=e.targetUrl||'';el('accessMode').value=e.accessMode;el('visitorPolicy').value=e.visitorPolicy==='selected-users'&&(e.allowedUsers||[]).every(u=>directory.includes(u))?'selected-local-users':e.visitorPolicy;drawChoices(e.allowedUsers||[]);syncVisitorPolicy();status.textContent='Editing '+e.name+'. Changes apply only after Save URL.';}
el('newApp').onclick=()=>{editing=false;el('appName').readOnly=false;el('appName').value='';el('targetType').value='port';el('appPort').value=8501;el('targetUrl').value='';el('accessMode').value='authenticated';el('visitorPolicy').value='signed-in-users';drawChoices();syncVisitorPolicy();status.textContent='New ordinary applications default to all authenticated users.';};
async function load(){const r=await fetch('/api/app-links');if(!r.ok)throw Error('Sign in again to manage applications.');const d=await r.json();token=d.csrfToken;directory=d.localUsers||[];entries=d.links;el('quota').textContent=d.used+' / '+d.limit+' application names used across both environments.';el('check').disabled=false;el('saveApp').disabled=false;el('domainHint').textContent=d.hostnameDomain?'Choose a name for https://NAME.'+d.hostnameDomain+'/':'';if(!el('appName').value)el('appName').value=d.defaultName;drawChoices(selected());const list=el('links');list.replaceChildren();for(const e of entries){const li=document.createElement('li'),a=document.createElement('a'),editButton=document.createElement('button'),remove=document.createElement('button');a.href=e.url;a.textContent=e.name+' ['+e.accessMode+' / '+e.visitorPolicy+'] → '+(e.type==='external'?e.targetUrl:'port '+e.port)+(e.enabled?'':' (disabled by administrator)');editButton.textContent='Edit sharing / URL';editButton.onclick=()=>edit(e);remove.textContent='Remove URL';remove.onclick=()=>save('delete',e.name,e.port);li.append(a,editButton,remove);if(e.hostnameUrl){const host=document.createElement('a');host.href=e.hostnameUrl;host.textContent=' · '+e.hostname;li.append(host);}else if(e.hostname){li.append(document.createTextNode(' · hostname awaiting setup'));}list.append(li)}}
async function save(action,name,port){if(!token)throw Error('Wait for application settings to load.');const policy=el('visitorPolicy').value,prior=entries.find(e=>e.name===name);const allowed=policy==='selected-users'?(prior?.allowedUsers||[]):selected();const r=await fetch('/api/app-links',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','X-DSH-App-CSRF':token},body:new URLSearchParams({action,name,port,type:el('targetType').value,targetUrl:el('targetUrl').value,accessMode:el('accessMode').value,visitorPolicy:policy,allowedUsers:JSON.stringify(allowed)})});const d=await r.json();status.textContent=d.message||d.error;await load();}
el('appForm').onsubmit=e=>{e.preventDefault();save('save',el('appName').value,el('appPort').value).catch(e=>status.textContent=e.message)};el('check').onclick=async()=>{const r=await fetch('/api/app-links?name='+encodeURIComponent(el('appName').value)),d=await r.json();status.textContent=d.available?'Name available in the application registry.':(d.error||'Name reserved.');};syncVisitorPolicy();load().catch(e=>status.textContent=e.message);</script></html>`;}
const COOKIE_NAME = process.env.DSH_COOKIE_NAME || 'dsh_auth';
const COOKIE_TRANSPORT = process.env.DSH_COOKIE_SECURE === 'false' ? '' : '; Secure';
const ADMIN_USERS = new Set((process.env.DSH_ADMIN_USERS || 'admin').split(',').map(x => x.trim()).filter(Boolean));
const ADMIN_SUMMARY_FILE = process.env.DSH_ADMIN_SUMMARY_FILE || '/admin-status/summary.json';
const AUDIT_DIR = process.env.DSH_AUDIT_DIR || `${USER_ROOT}/audit`;
let auditFailures = 0;
function auditEvent(event, actor, mode, subject, appDetails) {
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
      ...(subject && /^[a-z0-9_.-]{3,30}$/.test(subject) ? {subject} : {}),
      ...(event.startsWith('application.') && appDetails ? {application:projectAppAudit(appDetails)} : {}),
      ...(event==='capacity.policy'&&appDetails?{capacity:{enabled:appDetails.enabled===true,maxAccounts:appDetails.maxAccounts,warmSpareSlots:appDetails.warmSpareSlots,outcome:appDetails.outcome}}:{}) }) + '\n', { mode: 0o600 });
    return true;
  } catch { auditFailures++; console.error('[AUDIT] Could not persist security event'); return false; }
}
function projectAppAudit(d) {
  const result={};
  for(const k of ['owner','name','target'])if(typeof d[k]==='string'&&/^[a-z0-9_.-]{3,63}$/.test(d[k]))result[k]=d[k];
  if(['off','on'].includes(d.mode))result.mode=d.mode;
  if(['requested','applied'].includes(d.outcome))result.outcome=d.outcome;
  for(const k of ['previousPort','port','previousLimit','limit'])if(Number.isInteger(d[k])&&d[k]>=0&&d[k]<=65535)result[k]=d[k];
  return result;
}
function recentAudit() {
  const events = new Set(['login.success','login.denied','logout','runtime.http','admin.denied','terminal.open','application.websocket','application.save','application.delete','application.limit','application.disable','application.enable','application.edit','application.lifecycle','account.create','account.enable','account.disable','account.revoke','account.allow-internet','account.deny-internet','capacity.policy','package.request','credential.identity','credential.save','credential.disable','credential.delete','credential.approve','credential.execute','credential.result','credential.tool.list','credential.tool.profiles','credential.tool.execute','credential.tool.result']);
  const rows=[];
  for(const file of [`${AUDIT_DIR}/events.jsonl`,`${AUDIT_DIR}/legacy/legacy-dsh2/events.jsonl`,`${AUDIT_DIR}/legacy/legacy-dsh3/events.jsonl`]) {
    try {
      if(fs.statSync(file).size > 8*1024*1024) continue;
      for(const line of fs.readFileSync(file,'utf8').split('\n')) {
        try {
          const r=JSON.parse(line);
          if(!events.has(r.event)||typeof r.time!=='string'||!Number.isFinite(Date.parse(r.time))||! /^[a-zA-Z0-9_.-]{1,30}$/.test(r.user)||!['secure','internet','legacy-dsh2/internet','legacy-dsh3/internet'].includes(r.environment)) continue;
          rows.push({time:r.time,event:r.event,user:r.user,environment:r.environment,
            ...(r.event.startsWith('application.')&&r.application?{application:projectAppAudit(r.application)}:{}),
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
    const targets=USER_TARGETS ? Object.entries(allUserTargets()).flatMap(([user,environments])=>
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
    capacity: signupCapacitySummary(),
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
<style>body{font:16px/1.6 system-ui;background:#f1f5f9;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:32px}a{color:#075985}header{display:flex;gap:24px;align-items:center;flex-wrap:wrap}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}section{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:20px;margin:18px 0;overflow-wrap:anywhere}h1,h2{line-height:1.2}strong{font-size:24px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #e2e8f0}.muted{color:#475569}.notice{border-left:5px solid #d97706}button{padding:8px 16px;cursor:pointer}#capacityForm{display:flex;gap:12px;flex-wrap:wrap;align-items:center}#capacityForm label{display:inline-flex;gap:6px;align-items:center}#capacityForm input[type=number]{width:70px}#capacityControls table{min-width:650px}</style>
<main><header><h1>DSH Admin overview</h1><a href="/">Back to DSH</a><a href="/logout">Logout</a><button id="refresh">Refresh</button><a href="#applications">Applications</a></header><p id="error" role="alert"></p><p id="time" class="muted"></p>
<div class="cards"><section>Registered accounts<br><strong id="accounts">—</strong></section><section>New-user slots<br><strong id="newUserSlots">—</strong><div id="slotDetail"></div></section><section>Main gateway browser sessions<br><strong id="sessions">—</strong><div id="sessionDetail"></div></section><section>User routing<br><strong id="routing">—</strong></section></div>
<section><h2>User management</h2><p>Manage access to existing private runtimes. Disabling an account preserves its files and history. Sign out closes browser and terminal connections; it does not cancel already-running tools.</p><p id="userMessage" role="status"></p><div style="overflow:auto"><table><thead><tr><th>Account</th><th>Role</th><th>Sign-in</th><th>Status</th><th>Environments</th><th>Sessions</th><th>Actions</th></tr></thead><tbody id="users"></tbody></table></div><form id="createUser"><h3>Create account</h3><label>Identity ${SIGNUP_POOL ? '<input id="newUser" pattern="[a-z0-9_.-]{3,30}" minlength="3" maxlength="30" required>' : '<select id="newUser" required></select>'}</label> <label>Initial password <input id="newPassword" type="password" minlength="12" maxlength="1024" autocomplete="new-password" required></label> <button id="createButton">Create account</button></form><p id="provisionHelp">${SIGNUP_POOL ? 'New accounts receive an exclusive private environment pair. Capacity: <span id="signupCapacity">—</span>. Internet requires a separate approval.' : 'New identities require operator-provisioned private environments.'} Administrator roles are managed by the operator.</p></section>
<section id="applications"><h2>Applications</h2><p>New users receive 8 names. Set one limit per user; both environments share it. A lower limit preserves existing names. Disabling or removing a mapping closes its named-URL connections, while files and running applications stay in place.</p><p id="appMessage" role="status"></p><p id="appTotals"></p><div style="overflow:auto"><table><thead><tr><th>User</th><th>Account</th><th>Internet approval</th><th>Names used</th><th>Name limit</th></tr></thead><tbody id="appQuotas"></tbody></table></div><p><label>Find owner or name <input id="appFilter" type="search"></label></p><div style="overflow:auto"><table><thead><tr><th>Owner / name</th><th>No Internet port</th><th>Internet port</th><th>Status / actions</th></tr></thead><tbody id="adminApps"></tbody></table></div><p class="muted">This manages URL mappings, not access to another user's app contents. Direct numeric port URLs remain available to the owner. Quotas count names, not processes or GPU requests.</p></section>
<section id="capacityControls"><h2>Account capacity and automatic provisioning</h2><p>Keep a small pool of ready private workspace pairs. Existing accounts, files and histories are retained when limits are reduced or replenishment is paused.</p><form id="capacityForm"><label>Maximum accounts <input id="capacityMax" type="number" min="1" max="32" required value="16"></label><label>Warm spare slots <input id="capacitySpares" type="number" min="0" max="8" required value="2"></label><label><input id="capacityEnabled" type="checkbox" checked> Automatic replenishment</label><button id="capacitySave" disabled>Save capacity settings</button></form><p id="capacityStatus" role="status">Loading provisioner status…</p><h3>Shared infrastructure capacity</h3><p><a href="/manual/SELF_SERVICE_SIGNUP.html#capacity-planning">Capacity calculation and administrator instructions</a></p><p id="capacityAssessment">Waiting for a current calculation.</p><div style="overflow:auto"><table><thead><tr><th>Resource</th><th>Available before reserve</th><th>Protected reserve</th><th>Budget per new account pair</th><th>Additional pairs</th></tr></thead><tbody id="capacityResources"></tbody></table></div><p id="capacityAdditional"></p><p class="muted">The infrastructure ceiling uses the larger of measured usage and reservations, plus qualified future worker templates. It includes other services and DSH2/DSH3 when configured. It is separate from GPU request concurrency, application-name limits and guaranteed simultaneous workload performance. Central file-share free space is shown separately; per-user growth and backups need storage quotas and monitoring. Existing users are never removed when capacity decreases.</p></section><section id="managedServices"><h2>Managed startup services</h2><p>Only explicitly approved services start automatically. URL enable/disable is separate. A service runs as its owner in the selected environment, never as admin. Maximum four per environment.</p><p>Choose an account, environment and existing app name, or use <b>jupyter</b> for the managed notebook. Supply a JSON argv array for a command, without passwords or tokens. Supported commands: python3/node workspace scripts, npm run SCRIPT, python3 -m http.server.</p><form id="serviceForm"><label>Runtime <select id="serviceTarget"><option value="main">Main DSH private runtime</option></select></label><label>Owner <input id="serviceOwner" required></label><label>Environment <select id="serviceMode"><option value="off">No Internet</option><option value="on">Internet</option></select></label><label>Service / app name <input id="serviceName" required></label><label>Kind <select id="serviceKind"><option value="jupyter">Jupyter</option><option value="command">Command</option></select></label><label>Directory <input id="serviceCwd" value="/workspace" required></label><label id="servicePortWrap" hidden>App port (owner-only runtime) <input id="servicePort" type="number" min="1024" max="65535"></label><label>Command argv JSON <input id="serviceArgv" placeholder='["python3","app.py"]'></label><button>Save definition (stopped until started)</button></form><div id="serviceRows"></div><p>Start leaves an already-enabled service unchanged. Stop prevents automatic restart. Restart replaces the supervised process. Files remain. Process status is supervisor-reported; unavailable is not healthy.</p></section><section><h2>DSH usage and activity</h2><p id="usageFreshness">Loading runtime summaries…</p><p id="usageHealth" role="status"></p><div class="cards"><div>Stored conversations<br><strong id="usageSessions">—</strong></div><div>Running DSH agents<br><strong id="usageAgents">—</strong></div><div>Queued DSH messages<br><strong id="usageQueued">—</strong></div><div>Recorded turns / LLM steps<br><strong id="usageTurns">—</strong></div><div>Accumulated input / output tokens<br><strong id="usageTokens">—</strong></div><div>All-history decode tokens/sec<br><strong id="usageDecode">—</strong></div><div>Recent conversation decode tokens/sec<br><strong id="usageRecentDecode">—</strong></div><div>Recent output tokens/sec<br><strong id="usageRate">—</strong></div></div><div style="overflow:auto"><table><thead><tr><th>Account</th><th>Environment</th><th>Agents</th><th>Conversations</th><th>Turns</th><th>LLM steps</th><th>Input tokens</th><th>Output tokens</th><th>Recorded decode tok/sec</th><th>Workspace / durable files GiB</th><th>Local state used / capacity GiB</th></tr></thead><tbody id="usageRows"></tbody></table></div><p class="muted">Stored totals include imported or copied histories. Decode speed uses recorded decode time; recent output rate uses changes between samples. This panel covers DSH application sessions, not independent terminal-client accounting. Conversation text, files and credentials are excluded.</p><p id="storageFreshness" class="muted"></p></section>

<section class="notice"><h2>Infrastructure observation</h2><p id="freshness"></p><p>Usage is sampled from runtime summaries. Account/browser-session counts and routing are current gateway values. The environment health, model limits and recorded performance below are an operator snapshot. Browser logins and conversations are separate counts.</p></section>
<section><h2>Execution environments</h2><div style="overflow:auto"><table><thead><tr><th>Environment</th><th>Recorded readiness</th><th>Storage</th><th>Recorded network behavior</th></tr></thead><tbody id="environments"></tbody></table></div></section>
<section><h2>Model limits</h2><p id="model"></p><p class="muted">A concurrency ceiling does not guarantee that many maximum-length requests fit.</p></section><section><h2>Recorded performance</h2><ul id="performance"></ul></section><section><h2>Central access audit</h2><p id="audit"></p><a href="/api/admin/audit">Read recent access events</a></section><section class="notice"><h2>Remaining controls</h2><ul id="gaps"></ul></section><p class="muted">Stored passwords, cookies and conversation contents are never displayed.</p></main>
<script>
const put=(id,value)=>document.getElementById(id).textContent=value;
let managementToken='';
async function userAction(action,user,password){try{const body=new URLSearchParams({action,user});if(password)body.set('password',password);const r=await fetch('/api/admin/users',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded','X-DSH-Admin-CSRF':managementToken},body});const d=await r.json();if(!r.ok)throw Error(d.error||'Account update failed.');put('userMessage',action+' completed for '+user+'.');await refreshUsers();await refresh();}catch(e){put('userMessage',e.message);}}
async function refreshUsers(){try{const r=await fetch('/api/admin/users',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw Error('User management unavailable.');const d=await r.json();managementToken=d.csrfToken;const root=document.getElementById('users');root.replaceChildren();for(const u of d.users){const tr=document.createElement('tr');for(const value of [u.user,u.role,u.authProvider,u.enabled?'Enabled':'Disabled',u.environments.join(', '),u.sessions]){const td=document.createElement('td');td.textContent=value;tr.append(td);}const td=document.createElement('td');if(u.role!=='Administrator'){for(const action of [u.enabled?'disable':'enable','revoke',u.internetAllowed?'deny-internet':'allow-internet']){const b=document.createElement('button');b.type='button';b.textContent=action==='revoke'?'Sign out':action==='disable'?'Disable':action==='allow-internet'?'Allow Internet':action==='deny-internet'?'Disable Internet':'Enable';b.addEventListener('click',()=>{if(confirm(action==='disable'?'Disable sign-in for account '+u.user+'? Saved files and histories will remain.':b.textContent+' '+u.user+'?'))userAction(action,u.user);});td.append(b);}}else td.textContent='Operator-managed';tr.append(td);root.append(tr);}const select=document.getElementById('newUser');if(select.tagName==='SELECT'){select.replaceChildren();for(const user of d.provisionedIdentities){const opt=document.createElement('option');opt.value=user;opt.textContent=user;select.append(opt);}}const capacity=document.getElementById('signupCapacity');if(capacity)capacity.textContent=d.signupWorkspacesAvailable+' new-user slots available';document.getElementById('createButton').disabled=select.tagName==='SELECT'?!d.provisionedIdentities.length:!(d.signupWorkspacesAvailable>0||d.provisionedIdentities.length);}catch(e){put('userMessage',e.message);}}
let appManagementToken='',appInventory=null;
async function appAction(fields){try{const r=await fetch('/api/admin/apps',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded','X-DSH-Admin-CSRF':appManagementToken},body:new URLSearchParams(fields)});const d=await r.json();if(!r.ok)throw Error(d.error||'Application change failed.');put('appMessage',d.message);await refreshApps();}catch(e){put('appMessage',e.message);}}
function appButton(label,fields){const b=document.createElement('button');b.type='button';b.textContent=label;b.disabled=!appManagementToken;b.onclick=()=>{if(fields.action==='service-start'||confirm(label+' for '+(fields.name||fields.user)+'?'))appAction(fields);};return b;}
function renderApps(){const root=document.getElementById('adminApps');root.replaceChildren();if(!appInventory)return;const filter=document.getElementById('appFilter').value.toLowerCase();for(const e of appInventory.apps){if(!(e.owner+' '+e.name).toLowerCase().includes(filter))continue;const tr=document.createElement('tr'),identity=document.createElement('td');identity.textContent=e.owner+' / '+e.name+(e.hostname?' · '+e.hostname:'');tr.append(identity);for(const mode of ['off','on']){const td=document.createElement('td'),input=document.createElement('input');input.type='number';input.min=1024;input.max=65535;input.value=e.ports[mode]||'';input.setAttribute('aria-label',e.name+' '+mode+' port');const b=document.createElement('button');b.textContent='Save port';b.type='button';b.onclick=()=>{if(confirm('Change '+e.name+' '+mode+' port?'))appAction({action:'edit',user:e.owner,name:e.name,environment:mode,port:input.value});};td.append(input,b);tr.append(td);}const td=document.createElement('td');td.append(document.createTextNode((e.enabled?'Enabled':'Disabled')+' · '+(e.hostnameReady?'Hostname ready':'Hostname not ready')+(e.updatedAt?' · Changed '+e.updatedAt+' by '+e.updatedBy:'')));td.append(appButton(e.enabled?'Disable URL':'Enable URL',{action:e.enabled?'disable':'enable',user:e.owner,name:e.name}),appButton('Remove URL',{action:'delete',user:e.owner,name:e.name}));tr.append(td);root.append(tr);}}
async function refreshApps(){try{const r=await fetch('/api/admin/apps',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw Error('Application inventory unavailable.');const d=await r.json();appManagementToken=d.csrfToken;appInventory=d;const selector=document.getElementById('serviceTarget'),selected=selector.value;selector.replaceChildren(new Option('Main DSH private runtime','main'));for(const t of d.serviceTargets||[])selector.append(new Option(t.label+' / '+t.owner,t.id));if([...selector.options].some(x=>x.value===selected))selector.value=selected;setServiceTarget();renderServices(d.managedServices||[]);put('appTotals',d.totalNames+' registered names · Default '+d.defaultLimit+' per user');const root=document.getElementById('appQuotas');root.replaceChildren();for(const u of d.accounts){const tr=document.createElement('tr');for(const value of [u.user,u.enabled?'Enabled':'Disabled',u.internetAllowed?'Approved':'Not approved',u.used]){const td=document.createElement('td');td.textContent=value;tr.append(td);}const td=document.createElement('td'),input=document.createElement('input');input.type='number';input.min=0;input.max=d.siteLimit;input.value=u.limit;input.setAttribute('aria-label',u.user+' name limit');const b=document.createElement('button');b.type='button';b.textContent='Save limit';b.onclick=()=>{if(confirm('Set '+u.user+' limit to '+input.value+'? Existing names stay in place.'))appAction({action:'limit',user:u.user,limit:input.value});};td.append(input,b);tr.append(td);root.append(tr);}renderApps();}catch(e){appManagementToken='';put('appMessage',e.message);document.querySelectorAll('#applications button').forEach(b=>b.disabled=true);}}
function serviceAccessLabel(row){if(!row.available)return 'Supervisor not provisioned';if(row.allowed)return 'Provisioned';return {'internet-approval-pending':'Internet approval pending','account-disabled':'Account disabled','environment-disabled':'Environment access disabled'}[row.accessState]||'Environment access disabled';}
function serviceDisplayLabel(row,service){if(service.phase==='access-disabled')return serviceAccessLabel(row);return service.statusLabel||'Status unavailable';}
function renderServices(rows){const root=document.getElementById('serviceRows');root.replaceChildren();for(const row of rows){const p=document.createElement('p');p.textContent=(row.label?row.label+' / ':'')+row.user+' / '+(row.mode==='off'?'No Internet':'Internet')+' — '+serviceAccessLabel(row);root.append(p);for(const service of row.services){const e=document.createElement('div');e.textContent=service.name+' : '+service.port+' · '+serviceDisplayLabel(row,service)+' · '+(service.enabled?'Autostart enabled':'Stopped');for(const action of ['service-start','service-stop','service-restart','service-delete'])e.append(appButton(action.replace('service-',''),{action,user:row.user,environment:row.mode,service:service.name,target:row.target||'main'}));root.append(e);}}}
function setServiceTarget(){const id=document.getElementById('serviceTarget').value,t=(appInventory?.serviceTargets||[]).find(t=>t.id===id),owner=document.getElementById('serviceOwner'),mode=document.getElementById('serviceMode');owner.readOnly=Boolean(t);mode.disabled=Boolean(t);document.getElementById('servicePortWrap').hidden=!t;if(t){owner.value=t.owner;mode.value='on';}}
document.getElementById('serviceTarget').addEventListener('change',setServiceTarget);
document.getElementById('serviceForm').addEventListener('submit',e=>{e.preventDefault();if(!appManagementToken)return put('appMessage','Wait for authenticated application settings.');if(confirm('Save this executable service definition for the selected owner?'))appAction({action:'service-save',target:document.getElementById('serviceTarget').value,port:document.getElementById('servicePort').value,user:document.getElementById('serviceOwner').value,environment:document.getElementById('serviceMode').value,service:document.getElementById('serviceName').value,kind:document.getElementById('serviceKind').value,cwd:document.getElementById('serviceCwd').value,argv:document.getElementById('serviceArgv').value});});
document.getElementById('appFilter').addEventListener('input',renderApps);document.getElementById('refresh').addEventListener('click',refreshApps);refreshApps();
document.getElementById('createUser').addEventListener('submit',e=>{e.preventDefault();const field=document.getElementById('newPassword');const password=field.value;field.value='';userAction('create',document.getElementById('newUser').value,password);});
function list(id,values){const root=document.getElementById(id);root.replaceChildren();for(const value of values){const li=document.createElement('li');li.textContent=value;root.append(li);}}
let capacityToken='';
const capacityTime=x=>Number.isFinite(Date.parse(x))?new Date(x).toLocaleString():'Unavailable';
const capacityLabels={cpu:'CPU cores',memoryGiB:'RAM (GiB)',pods:'Pod slots',storageGiB:'Local storage (GiB)',inventory:'Inventory'};
function showCapacity(c,observed){
 const body=document.getElementById('capacityResources');body.replaceChildren();
 if(!c){put('capacityAssessment','Current complete capacity calculation unavailable. Increasing the account limit is blocked until a fresh calculation is available. Existing accounts and the saved limit are retained.');put('capacityAdditional','');return;}
 put('capacityAssessment','Observed '+capacityTime(observed)+' · Main accounts '+c.mainRegistered+' · Additional DSH accounts '+c.additionalAccounts+' · Total '+c.totalRegistered+' · Infrastructure planning ceiling '+c.mainPlanningCeiling+' main / '+c.totalPlanningCeiling+' total · '+c.readyPairs+' ready pairs · Limiting resource: '+c.limitingResources.map(x=>capacityLabels[x]||x).join(', '));
 for(const r of c.resources){const tr=document.createElement('tr');for(const v of [capacityLabels[r.resource]||r.resource,r.available,r.reserve,r.pairBudget,r.additionalPairs]){const td=document.createElement('td');td.textContent=typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:2}):v;tr.append(td);}body.append(tr);}
 const usage=c.observedUsage;const usageText=usage?' · Measured CPU '+usage.cpu.toFixed(2)+' cores / reserved '+usage.reservedCPU.toFixed(2)+' · Measured RAM '+usage.memoryGiB.toFixed(1)+' GiB / reserved '+usage.reservedMemoryGiB.toFixed(1)+' · Usage sampled '+capacityTime(usage.timestamp):'';
 put('capacityAdditional',usageText+' · '+c.additionalDeployments.map(x=>x.label+': '+x.accounts+' account, '+x.readyWorkers+'/'+x.desiredWorkers+' workers ready').join(' · ')+(c.centralStorageFreeGiB===null?' · Central share free space unavailable':' · Central share free '+c.centralStorageFreeGiB.toLocaleString(undefined,{maximumFractionDigits:1})+' GiB'));
}
async function refreshCapacity(){try{const r=await fetch('/api/admin/capacity',{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'Capacity unavailable');capacityToken=d.csrfToken;const p=d.automaticProvisioning.policy;if(document.activeElement?.closest('#capacityForm')===null){document.getElementById('capacityMax').value=p.maxAccounts;document.getElementById('capacitySpares').value=p.warmSpareSlots;document.getElementById('capacityEnabled').checked=p.enabled;}document.getElementById('capacitySave').disabled=false;const c=d.automaticProvisioning.controller;showCapacity(c?.capacity,c?.observedAt);put('capacityStatus',(d.signupAdmission?(d.signupAdmission.allowed?'Signup admission: open. ':'Signup admission: paused ('+d.signupAdmission.reason+'). '):'')+(c?'Observed '+capacityTime(c.observedAt)+' · '+(c.available?'Provisioner: '+c.action+' / '+c.reason:'Provisioning paused; infrastructure review required'):'Provisioner status unavailable or older than one minute.'));}catch(e){put('capacityStatus',e.message);showCapacity(null);document.getElementById('capacitySave').disabled=true;}}
document.getElementById('capacityForm').addEventListener('submit',async event=>{event.preventDefault();const b=document.getElementById('capacitySave');b.disabled=true;try{const r=await fetch('/api/admin/capacity',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','X-DSH-Admin-CSRF':capacityToken},body:new URLSearchParams({maxAccounts:document.getElementById('capacityMax').value,warmSpareSlots:document.getElementById('capacitySpares').value,enabled:String(document.getElementById('capacityEnabled').checked)})});const d=await r.json();if(!r.ok)throw Error(d.error||'Capacity settings unavailable');put('capacityStatus','Capacity settings saved. Existing workspaces are retained.');await refresh();}catch(e){put('capacityStatus',e.message);}finally{b.disabled=false;}});
refreshCapacity();setInterval(()=>{if(!document.hidden)refreshCapacity();},15000);
async function refresh(){try{const r=await fetch('/api/admin/summary',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw Error('Admin access unavailable ('+r.status+').');const d=await r.json();put('error','');put('time','Gateway read at '+d.generatedAt);put('accounts',d.registeredAccounts);const c=d.capacity;if(c){put('newUserSlots',c.remainingSlots);put('slotDetail',c.assignedSlots+' / '+c.provisionedSlots+' prepared slots assigned · '+c.enabledAccounts+' enabled / '+c.disabledAccounts+' disabled accounts'+(c.registrationEnabled?'':' · registration disabled'));const label=document.getElementById('signupCapacity');if(label)label.textContent=c.remainingSlots+' new-user slots available';}put('sessions',d.activeBrowserSessions.secure+d.activeBrowserSessions.internet);put('sessionDetail','No Internet: '+d.activeBrowserSessions.secure+' · Internet: '+d.activeBrowserSessions.internet);put('routing',d.privateUserRouting?'Per user':'Shared pools');put('freshness',d.snapshot.observedAt?'Snapshot observed at '+d.snapshot.observedAt+'. Refresh does not rerun infrastructure tests.':'No snapshot available. Infrastructure status is unknown.');const root=document.getElementById('environments');root.replaceChildren();for(const e of d.snapshot.environments){const tr=document.createElement('tr');for(const text of [e.name,e.ready?'Ready at observation':'Not verified ready',e.storage,e.network]){const td=document.createElement('td');td.textContent=text;tr.append(td);}root.append(tr);}const m=d.snapshot.model;put('model',m?(m.checkpoint?'Checkpoint: '+m.checkpoint+(m.revision?' ('+m.revision.slice(0,12)+')':'')+' · ':'')+'Backend context: '+m.backendContext+' tokens · DSH/LiteLLM budget: '+m.userContext+' tokens · Running-request ceiling: '+m.concurrencyCeiling+(m.longConcurrencyCeiling?' · Requests above 128K input: '+m.longConcurrencyCeiling+' at a time':'')+(m.maxOutputTokens?' · Maximum output: '+m.maxOutputTokens+' tokens':'')+(m.observedAt?' · Model observed at '+m.observedAt:''):'No recorded limits.');list('performance',d.snapshot.performance);list('gaps',d.snapshot.gaps);}catch(e){put('error',e.message);put('newUserSlots','—');put('slotDetail','Current capacity unavailable');const label=document.getElementById('signupCapacity');if(label)label.textContent='Current capacity unavailable';}}
document.getElementById('refresh').addEventListener('click',refresh);refresh().then(async()=>{try{const r=await fetch('/api/admin/summary',{cache:'no-store'});const d=await r.json();put('audit','Recent main/legacy access events: '+d.audit.recentEvents+' · Write failures since gateway start: '+d.audit.failuresSinceStart+' · Legacy projection observed at: '+(d.audit.legacy?.observedAt||'not available'));}catch{put('audit','Audit status unavailable.');}});
document.getElementById('refresh').addEventListener('click',refreshUsers);refreshUsers();
const metricText=value=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:2}):'—';
const gib=value=>typeof value==='number'?metricText(value/1073741824):'—';
async function refreshUsage(){try{
 const response=await fetch('/api/admin/telemetry',{cache:'no-store',credentials:'same-origin'});
 if(!response.ok)throw Error('Runtime usage unavailable.');const data=await response.json(),t=data.totals;
 put('usageFreshness','Observed '+data.observedAt+' · '+data.availableRuntimes+'/'+data.configuredRuntimes+' private runtimes available · '+t.usageSessions+'/'+t.sessions+' stored sessions have usage records · refreshes every 15 seconds while visible.');
 put('usageHealth',data.availableRuntimes===data.configuredRuntimes?'All configured runtime summaries available.':(data.configuredRuntimes-data.availableRuntimes)+' runtime summaries unavailable; totals cover responding runtimes only.');put('usageSessions',metricText(t.sessions));put('usageAgents',metricText(t.runningAgents));put('usageQueued',metricText(t.queuedMessages));put('usageTurns',metricText(t.turns)+' / '+metricText(t.llmSteps));
 put('usageTokens',metricText(t.inputTokens)+' / '+metricText(t.outputTokens));put('usageDecode',metricText(t.recordedDecodeTokensPerSecond));put('usageRate',metricText(t.outputTokensPerSecond));put('usageRecentDecode',metricText(t.recentDecodeTokensPerSecond));
 const root=document.getElementById('usageRows');root.replaceChildren();
 for(const row of data.runtimes){const storage=data.storage?.runtimes.find(x=>x.user===row.user&&x.environment===row.environment),tr=document.createElement('tr');
  const values=[row.user,row.environment==='secure'?'No Internet':'Internet',...['runningAgents','sessions','turns','llmSteps','inputTokens','outputTokens','recordedDecodeTokensPerSecond'].map(k=>row.available?metricText(row[k]):'Unavailable'),storage?gib(storage.workspaceFileBytes)+' / '+gib(storage.durableStateFileBytes)+(storage.workspaceScanComplete&&storage.durableStateScanComplete?'':' (partial)'):'—',storage?gib(storage.stateUsedBytes)+' / '+gib(storage.stateCapacityBytes):'—'];
  for(const value of values){const cell=document.createElement('td');cell.textContent=value;tr.append(cell);}root.append(tr);
 }
 put('storageFreshness',data.storage?'Storage observed '+data.storage.observedAt+(Date.now()-Date.parse(data.storage.observedAt)>300000?' (older than 5 minutes; refresh the storage collector)':'')+'. Workspace and durable-state bytes are separate file-size scans; partial scans are marked. Local state usage includes filesystem overhead.':'Storage capacity has not been collected.');
 }catch(error){put('usageFreshness',error.message);put('usageHealth','Current activity is unknown.');for(const id of ['usageSessions','usageAgents','usageQueued','usageTurns','usageTokens','usageDecode','usageRate','usageRecentDecode'])put(id,'—');document.getElementById('usageRows').replaceChildren();}}
document.getElementById('refresh').addEventListener('click',refreshUsage);refreshUsage();setInterval(()=>{if(!document.hidden){refresh();refreshUsage();}},15000);document.addEventListener('visibilitychange',()=>{if(!document.hidden){refresh();refreshUsage();}});
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
// Signup can assign only an operator-qualified, empty private runtime pair.
// The gateway has no Kubernetes management token and never falls back to a pool.
const LEGACY_OWNER = !USER_TARGETS ? (process.env.DSH_SINGLE_USER || process.env.AUTH_USER || '') : '';
const LEGACY_INTERNET_ONLY = !USER_TARGETS && Boolean(process.env.AUTH_USER);
const SIGNUP_POOL = process.env.DSH_SIGNUP_POOL_FILE
  ? JSON.parse(fs.readFileSync(process.env.DSH_SIGNUP_POOL_FILE, 'utf8')) : null;
const ALLOW_REGISTRATION = Boolean(USER_TARGETS && SIGNUP_POOL && !LEGACY_OWNER && process.env.DSH_ALLOW_REGISTRATION === 'true');
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
if (SIGNUP_POOL) {
  if (!USER_TARGETS || !SIGNUP_POOL.slots || Array.isArray(SIGNUP_POOL.slots) || Object.keys(SIGNUP_POOL.slots).length>32) throw Error('Invalid signup pool');
  const hosts=new Set(Object.values(USER_TARGETS).flatMap(v=>Object.values(v).map(t=>t.host)));
  const tokens=new Set(Object.values(USER_TARGETS).flatMap(v=>Object.values(v).map(t=>t.tokenFile)));
  for(const [slot,targets] of Object.entries(SIGNUP_POOL.slots)) {
    if(!/^[a-z0-9-]{3,40}$/.test(slot) || Object.keys(targets).sort().join(',')!=='internet,secure')throw Error('Invalid signup slot');
    for(const target of Object.values(targets)) {
      if(!target || !/^[a-zA-Z0-9.-]+$/.test(target.host) || target.port!==3081 ||
        !/^\/runtime-tokens\/[a-zA-Z0-9_./-]+$/.test(target.tokenFile) || target.tokenFile.split('/').includes('..') ||
        hosts.has(target.host) || tokens.has(target.tokenFile))throw Error('Signup runtime must be exclusive');
      hosts.add(target.host);tokens.add(target.tokenFile);
    }
  }
}
const CAPACITY_ROOT=process.env.DSH_CAPACITY_ROOT||'';
const CAPACITY=CAPACITY_ROOT?new (require('./capacity_policy').Manager)(CAPACITY_ROOT,SIGNUP_POOL,process.env.DSH_NAMESPACE||'llm'):null;
function activeSignupPool(){return CAPACITY?CAPACITY.pool():SIGNUP_POOL;}
setInterval(()=>{if(CAPACITY)try{CAPACITY.project(loadUsers());}catch{}},5000).unref();
// First come, first reserved: publish which private runtimes signed-in users are using.
// The controller starts them when resources allow and stops them when idle.
const SESSION_DEMAND=CAPACITY_ROOT&&USER_TARGETS?require('./session_demand').createSessionDemand({root:CAPACITY_ROOT}):null;
const SESSION_IDLE_MS=Math.max(300000,Math.min(86400000,(Number(process.env.DSH_SESSION_IDLE_MINUTES)||60)*60000));
const RUNTIME_WAITING=['stopped','stopping','starting','waiting'];
let sessionDemandSeeded=false;
setInterval(()=>{if(!SESSION_DEMAND)return;try{
  // First rollout: treat everyone already signed in as active for one idle period.
  if(!sessionDemandSeeded){sessionDemandSeeded=true;if(!SESSION_DEMAND.seeded())for(const s of SESSIONS.values())SESSION_DEMAND.touch(getEnvironmentTarget(normalizeInternetMode(s.internet),s.user));}
  SESSION_DEMAND.flush(SESSION_IDLE_MS);}catch{}},5000).unref();
function capacityStatusSnapshot(){
  if(!CAPACITY_ROOT)return null;
  try{const s=require('./capacity_policy').readJSON(path.join(CAPACITY_ROOT,'inventory','status.json'),65536);const age=Date.now()-Date.parse(s.observedAt);return s.available===true&&Number.isFinite(age)&&age>=-5000&&age<90000?s:null;}catch{return null;}
}
function sharedResourceStatus(){return require('./session_demand').publicStatus(SESSION_DEMAND?.snapshot(),capacityStatusSnapshot());}
// Cold start or queue: a self-refreshing page for browsers, 503 + Retry-After for API clients.
function sendRuntimeWait(req,res,runtime){
  const status=sharedResourceStatus();
  const message=runtime.state==='waiting'?`All shared resources are in use. You are number ${Number(runtime.position)||1} in the queue; your workspace starts as soon as resources free up.`
    :runtime.state==='starting'?'Your workspace is starting. This usually takes under a minute.'
    :'Your workspace was stopped after a period without activity. It is starting again now; your files are kept.';
  // JupyterHub-style spawn progress: queued, scheduling, preparing, image, containers, DSH, ready.
  const progress=runtime.progress||{stage:runtime.state==='waiting'?'queued':'scheduling',percent:runtime.state==='waiting'?5:10,detail:''};
  if(req.method!=='GET'||!String(req.headers.accept||'').includes('text/html')){
    res.writeHead(503,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Retry-After':'3'});
    return res.end(JSON.stringify({error:'RUNTIME_'+runtime.state.toUpperCase(),state:runtime.state,...(runtime.position?{position:runtime.position}:{}),progress,message}));
  }
  // Every value below is a constant or a controller-supplied number; escape anyway.
  const escapeHtml=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const n=v=>Number.isSafeInteger(v)?v:'–',pct=v=>Number.isFinite(v)?Math.round(v)+'%':'–';
  const w=status.workspaces||{};
  const steps=[['queued','Waiting for shared resources'],['scheduling','Placing your workspace on the node'],['preparing','Mounting your files and settings'],
    ['pulling-image','Loading the workspace image'],['starting-containers','Starting workspace processes'],['starting-dsh','Starting DSH'],['ready','Ready: opening your workspace']];
  const failed=progress.stage==='failed',current=steps.findIndex(([id])=>id===progress.stage);
  const percent=Math.max(0,Math.min(100,Number(progress.percent)||0));
  const list=steps.map(([id,label],i)=>{const done=!failed&&current>i,now=current===i;
    return `<li class="${done?'done':now?'now':''}"><span>${done?'✓':now?'●':'○'}</span>${escapeHtml(label)}${now&&progress.detail?` <em>${escapeHtml(progress.detail)}</em>`:''}</li>`;}).join('');
  // A meta-free Refresh header keeps the page script-free; when the workspace is
  // ready the next refresh is proxied straight into it (automatic redirect).
  res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Refresh':'3','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
    'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"});
  return res.end(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Starting your workspace</title>
<style>body{font-family:system-ui,sans-serif;margin:0;background:#f4f6f9;color:#1f2933}main{max-width:560px;margin:10vh auto;padding:28px;background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08)}h1{font-size:1.3rem;margin:0 0 12px}p{line-height:1.5}
.bar{height:14px;border-radius:7px;background:#e4e7eb;overflow:hidden;margin:16px 0 6px}.bar>div{height:100%;background:${failed?'#c53030':'#2f6fed'};transition:width .4s}.pct{font-weight:600;font-size:.9rem;color:#334e68}
ol{list-style:none;padding:0;margin:16px 0}li{padding:4px 0;color:#9aa5b1}li span{display:inline-block;width:1.4em}li.done{color:#2f855a}li.now{color:#1f2933;font-weight:600}li em{font-weight:400;color:#52606d;font-style:normal}
dl{display:grid;grid-template-columns:auto auto;gap:6px 16px;margin:18px 0}dt{color:#52606d}dd{margin:0;font-weight:600}small{color:#52606d}</style></head>
<body><main><h1>${runtime.state==='waiting'?'Waiting for shared resources':failed?'Your workspace could not start':'Starting your workspace'}</h1><p>${escapeHtml(failed?'Starting failed ('+(progress.detail||'unknown')+'). Please contact the administrator; your files are safe.':message)}</p>
<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}"><div style="width:${percent}%"></div></div><div class="pct">${percent}%</div>
<ol>${list}</ol>
<dl><dt>Workspaces running</dt><dd>${n(w.running)}</dd><dt>Starting / waiting</dt><dd>${n(w.starting)} / ${n(w.waiting)}</dd>
<dt>CPU reserved / used</dt><dd>${pct(status.cpu?.reservedPercent)} / ${pct(status.cpu?.usedPercent)}</dd><dt>Memory reserved / used</dt><dd>${pct(status.memory?.reservedPercent)} / ${pct(status.memory?.usedPercent)}</dd></dl>
<p><small>${escapeHtml(status.policy)} This page refreshes every 3 seconds and opens your workspace when it is ready. <a href="/logout">Sign out</a></small></p></main></body></html>`);
}
function privateTargetsFor(user, users=loadUsers()) {
  if(USER_TARGETS && Object.hasOwn(USER_TARGETS,user))return USER_TARGETS[user];
  const slot=Object.hasOwn(users,user)&&users[user].runtimeSlot;
  const pool=activeSignupPool();
  if(!slot || !pool || !Object.hasOwn(pool.slots,slot) ||
    Object.values(users).filter(u=>u.runtimeSlot===slot).length!==1)return null;
  return pool.slots[slot];
}
function allUserTargets() {
  const users=loadUsers(),result={...USER_TARGETS};
  for(const user of Object.keys(users)){const targets=privateTargetsFor(user,users);if(targets)result[user]=targets;}
  return result;
}
function freeSignupSlots(users=loadUsers()) {
  if(CAPACITY&&!CAPACITY.admission(users).allowed)return [];
  const used=new Set(Object.values(users).map(u=>u.runtimeSlot).filter(Boolean));
  const pool=activeSignupPool();const slots=pool?Object.keys(pool.slots).filter(slot=>!used.has(slot)):[];
  // Accounts are not capped: they hold storage only and sign-in admits compute.
  return slots;
}
function signupCapacitySummary(users=loadUsers()) {
  const pool=activeSignupPool();const provisioned=pool?Object.keys(pool.slots).length:0;
  const remaining=freeSignupSlots(users).length;
  return {observedAt:new Date().toISOString(),registrationEnabled:ALLOW_REGISTRATION,
    provisionedSlots:provisioned,assignedSlots:Object.values(users).filter(u=>u.runtimeSlot).length,remainingSlots:remaining,
    ...(CAPACITY?{automaticProvisioning:CAPACITY.summary(users),signupAdmission:CAPACITY.admission(users)}:{}),
    enabledAccounts:Object.values(users).filter(user=>user.disabled!==true).length,
    disabledAccounts:Object.values(users).filter(user=>user.disabled===true).length};
}
function newAccountRecord(users,user,password) {
  if(CAPACITY&&!CAPACITY.admission(users).allowed)return {status:503,error:'New signups are temporarily paused while storage is short or capacity is unavailable. Existing users can still sign in. Please retry after capacity recovers.'};
  if(ADMIN_USERS.has(user)||['__proto__','constructor','prototype'].includes(user)||Object.hasOwn(users,user))return {status:409,error:'Account is reserved or already exists.'};
  if(password.length<12||Buffer.byteLength(password)>1024||password!==password.trim())return {status:400,error:'Use a password of at least 12 characters without surrounding spaces.'};
  if(USER_TARGETS && Object.hasOwn(USER_TARGETS,user) && USER_TARGETS[user].secure && USER_TARGETS[user].internet)
    return {record:{...hashPassword(password),internetAllowed:false}};
  if(!SIGNUP_POOL)return {status:409,error:'Provision both private environments before creating this account.'};
  const slot=freeSignupSlots(users)[0];
  if(!slot)return {status:503,error:CAPACITY?'A private workspace is being prepared. Please retry shortly.':'No new-user slot is available. Please contact the administrator.'};
  return {record:{...hashPassword(password),internetAllowed:false,runtimeSlot:slot,createdAt:new Date().toISOString()}};
}
const authenticateIdentity = require('./identity_auth').createAuthenticator({directory:LDAP_DIRECTORY, loadUsers, saveUsers, verifyPassword, newAccountRecord, isAdmin:user=>ADMIN_USERS.has(user), audit:(event,user)=>auditEvent(event,user,'off')});
const registrationAttempts=new Map();
function admitRegistration(address) {
  const now=Date.now(),window=15*60*1000;
  for(const [key,value]of registrationAttempts)if(now-value.start>=window)registrationAttempts.delete(key);
  if(!registrationAttempts.has(address)){
    if(registrationAttempts.size>=256)return false;
    registrationAttempts.set(address,{start:now,count:0});
  }
  return ++registrationAttempts.get(address).count<=30;
}
function getEnvironmentTarget(mode, user) {
  if (USER_TARGETS) {
    const environment = normalizeInternetMode(mode) === 'on' ? 'internet' : 'secure';
    const targets = privateTargetsFor(user);
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

function sessionAccountStamp(user) {
  const account=loadUsers()[user];
  if(!account||account.disabled===true)return null;
  const stamp=account.authProvider==='ldap' ? ['ldap',account.ldapSubject,account.scheme,account.salt,account.hash] : [account.scheme,account.salt,account.hash];
  return crypto.createHash('sha256').update(JSON.stringify(stamp)).digest('hex');
}
const SESSIONS = new SessionStore(process.env.DSH_SESSION_STORE_PATH || path.join(path.dirname(USER_STORE_PATH),'.browser-sessions','sessions.json'), {
  verify:session=>session.accountStamp===sessionAccountStamp(session.user) && (session.internet!=='on'||internetAllowed(session.user))
});
const cachedDshAuthCookies = new Map();
const USER_SOCKETS = new Map();
const SESSION_SOCKETS = new WeakMap();
function accountEnabled(user) { const users=loadUsers(); return Object.hasOwn(users,user) && users[user].disabled !== true; }
function revokeUserSessions(user) {
  SESSIONS.removeUser(user);
  for (const socket of USER_SOCKETS.get(user) || []) socket.destroy();
  USER_SOCKETS.delete(user);
  for(const [name,entry]of Object.entries(appLinks()))if(entry.owner===user)closeAppConnections(name);
}
function internetAllowed(user) {
 const record=loadUsers()[user];
 return ADMIN_USERS.has(user) || record?.internetAllowed === true ||
   (LEGACY_INTERNET_ONLY && user===LEGACY_OWNER && accountEnabled(user) && record?.internetAllowed!==false);
}
function adminAccounts() {
  const users=loadUsers();
  return Object.keys(users).sort().map(user=>({user, enabled:users[user].disabled!==true,
    role:ADMIN_USERS.has(user)?'Administrator':'User', authProvider:users[user].authProvider==='ldap'?'AD / LDAP':'Local', internetAllowed:internetAllowed(user),
    environments:USER_TARGETS ? ['secure','internet'].filter(mode=>privateTargetsFor(user,users)?.[mode]) : ['instance'],
    sessions:[...SESSIONS.values()].filter(s=>s.user===user).length}));
}

// --- DYNAMIC APP GATEWAY HELPERS (OPTION 1 & OPTION 2) ---
function resolvePortAlias(alias, user, mode) {
  if (!alias) return null;
  const key = alias.toLowerCase();
  if (user) {const port=customAppPort(key,user,mode);if(port)return port;}
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
    'jupyter': 8888,
    'ttyd': 7681,
    'streamlit': 8501,
    'dashboard': 8501,
    'api': 8000,
    'fastapi': 8000,
    'web': 3000
  };
  return defaults[key] || null;
}

function parseAppTarget(inHost, reqUrl, user, mode) {
  const parsed = url.parse(reqUrl, true);
  let port = null;
  let targetPath = reqUrl;
  const customHost=appHostName(inHost);
  if(customHost)port=customAppPort(customHost,user,mode);

  // 1. Subdomain Check: e.g. dsh-8000.example.com, dsh2-8501, dsh-user2-8000...
  // dsh-user<N> is tried before dsh<N> so dsh-user2-8000 resolves to port 8000, not alias "user2-8000".
  const subMatch = inHost.match(/^(?:dsh-user[0-9]*|dsh[0-9]*)-([a-zA-Z0-9_-]+)\./i);
  if (subMatch && !customHost) {
    const raw = subMatch[1];
    if (/^\d+$/.test(raw)) {
      port = parseInt(raw, 10);
    } else {
      port = resolvePortAlias(raw, user, mode);
    }
    targetPath = reqUrl; // Root path preserved for SPA / assets
  }

  // 2. Path Check: e.g. /proxy/8000/ or /proxy/myapp/api
  if (!port && !customHost) {
    const pathMatch = parsed.pathname.match(/^\/proxy\/([a-zA-Z0-9_-]+)(\/.*)?$/);
    if (pathMatch) {
      const raw = pathMatch[1];
      if (/^\d+$/.test(raw)) {
        port = parseInt(raw, 10);
      } else {
        port = resolvePortAlias(raw, user, mode);
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

  res.once('close',()=>proxyReq.destroy());
  proxyReq.on('error', (err) => {
    if(res.destroyed)return;
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
    <p>Target service on port <code>${targetPort}</code> is currently not listening inside your selected private environment.</p>
    ${targetPort === 8888 ? '<p>Open <a href="/terminal" style="color:#38BDF8">Web Terminal</a>, run <code>jupyter lab</code>, then return to <a href="/proxy/8888/lab" style="color:#38BDF8">JupyterLab</a>. Keep the terminal process running.</p>' : ''}
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

  socket.once('close',()=>targetSocket.destroy());
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

function injectLogoutControl(html, isAdmin = false, sessionUser = '', internetMode = 'off') {
  if (typeof html !== 'string' || html.includes('id="dsh-enterprise-logout"')) return html;
  const control = `<a id="dsh-enterprise-logout" href="/logout" aria-label="Logout" title="Logout" style="position:fixed;right:18px;top:14px;z-index:2147483647;display:inline-flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid rgba(148,163,184,.42);border-radius:8px;background:rgba(15,23,42,.94);color:#f8fafc;font:600 13px/1.2 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.28);backdrop-filter:blur(8px)"><span aria-hidden="true">&#x21AA;</span><span>Logout</span></a>`;
  const credentialLink = USER_CREDENTIALS ? '<a id="dsh-user-credentials" href="/credentials" style="position:fixed;right:18px;top:58px;z-index:2147483647;background:#003366;color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font:600 13px system-ui">Credentials</a>' : '';
  const adminLink = isAdmin ? '<a id="dsh-admin-dashboard" href="/admin" style="position:fixed;right:220px;top:14px;z-index:2147483647;background:#0f172a;color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font:600 13px system-ui">Admin overview</a>' : '';
  // Keep unsent text in the existing DOM. Never save drafts to browser storage,
  // replay a failed POST, or silently switch an open tab to a different account.
  const identity = JSON.stringify({user:sessionUser,internet:internetMode}).replaceAll('<','\\u003c');
  const recovery = `<script id="dsh-session-recovery">(()=>{'use strict';const identity=${identity},originalFetch=window.fetch.bind(window);let panel=null,checking=false,waiting=false;
function show(){waiting=true;if(panel)return;panel=document.createElement('section');panel.id='dsh-session-ended';panel.setAttribute('role','alert');panel.style.cssText='position:fixed;top:78px;left:50%;transform:translateX(-50%);width:min(520px,calc(100vw - 32px));box-sizing:border-box;z-index:2147483647;padding:18px;border:1px solid #eab308;border-radius:12px;background:#172033;color:#fff;font:14px/1.5 system-ui;box-shadow:0 8px 30px #0008';panel.innerHTML='<strong>Your sign-in session ended.</strong><p>Keep this tab open: your unsent draft stays here. Sign in again in a new tab using the same account and environment, then return here.</p><a href="/login" target="_blank" rel="noopener" style="color:#93c5fd">Sign in again</a> <button type="button" id="dsh-session-check">I have signed in</button><p id="dsh-session-note"></p>';document.body.append(panel);panel.querySelector('button').onclick=check;}
async function check(){if(checking||!document.body)return;checking=true;try{const r=await originalFetch('/api/auth/session',{credentials:'same-origin',cache:'no-store'});if(r.status===401){show();return;}if(!r.ok||!(r.headers.get('content-type')||'').includes('application/json'))return;const s=await r.json();if(s.user!==identity.user||s.internet!==identity.internet){show();panel.querySelector('#dsh-session-note').textContent='Use the original account and environment to resume this tab.';return;}if(waiting){waiting=false;if(panel){panel.remove();panel=null;}window.dispatchEvent(new Event('dsh-session-restored'));}}catch{}finally{checking=false;}}
window.fetch=async function(input,init){const r=await originalFetch(input,init);try{const u=new URL(typeof input==='string'?input:input.url,location.href);if(u.origin===location.origin&&u.pathname.startsWith('/api/')&&r.status===401&&r.headers.get('x-dsh-auth-required')==='1')show();}catch{}return r;};
setInterval(check,15000);window.addEventListener('focus',check);document.addEventListener('visibilitychange',()=>{if(!document.hidden)check();});})();</script>`;
  html = /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, head => head+recovery) : recovery+html;
  const appsLink='<a id="dsh-my-applications" href="/applications" style="position:fixed;right:125px;top:14px;z-index:2147483647;background:#0f172a;color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font:600 13px system-ui">My apps</a>';
  if (/<\/body>/i.test(html)) return html.replace(/<\/body>/i, `${control}${appsLink}${adminLink}${credentialLink}</body>`);
  return html + control + appsLink + adminLink + credentialLink;
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

function renderAuthPage({ tab = 'login', errorMsg = '', successMsg = '', authProvider = LDAP_DIRECTORY ? 'ldap' : 'local' } = {}) {
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
    .manual-fab {
      position: fixed; right: max(24px, env(safe-area-inset-right)); bottom: max(24px, env(safe-area-inset-bottom));
      z-index: 20; display: inline-flex; align-items: center; gap: 9px;
      padding: 13px 19px; border: 1px solid #5B90C6; border-radius: 999px;
      background: #12365b; color: #EFF6FF; font-size: 14px; font-weight: 600;
      text-decoration: none; box-shadow: 0 8px 28px #0006;
    }
    .manual-fab:hover { background: #1e4c7c; }
    .manual-fab:focus-visible { outline: 3px solid #93C5FD; outline-offset: 4px; }
    @media (max-width: 600px) { body { padding-bottom: 100px; } .manual-fab { right: 16px; bottom: 16px; } }
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
<body>${process.env.DSH_TEST_ISSUER==='true'?'<aside>Isolated Test issuer: synthetic review accounts only. This is not normal DSH.</aside>':''}
  <div class="login-card">
    <div class="brand-header">
      <div class="brand-logo">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
      </div>
      <div class="org-title">Enterprise AI Platform</div>
      <h1 class="app-title">DeepSeek Harness (DSH)</h1>
      <p class="app-subtitle">Enterprise Agentic Coding &amp; Knowledge Gateway</p>
    </div>

    <section id="resourceStatus" class="resource-status" role="status" aria-live="polite" style="margin:0 0 16px;padding:12px 14px;border:1px solid #d9e2ec;border-radius:10px;background:#f8fafc;font-size:.88rem;line-height:1.45">
      <div style="font-weight:600;margin-bottom:8px">Shared resources now <span id="resourceUpdated" style="font-weight:400;color:#52606d;font-size:.8rem"></span></div>
      <style>.rs-row{display:grid;grid-template-columns:7.5em 1fr;gap:6px 10px;align-items:center;margin:5px 0}.rs-bar{position:relative;height:12px;border-radius:6px;background:#e4e7eb;overflow:hidden}.rs-bar .rs-res{position:absolute;inset:0 auto 0 0;background:#9fb3c8}.rs-bar .rs-use{position:absolute;inset:0 auto 0 0;background:#2f6fed}.rs-val{grid-column:2;font-size:.78rem;color:#52606d;margin-top:-3px}.rs-legend{font-size:.75rem;color:#52606d;margin-top:4px}.rs-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:-1px;margin:0 4px 0 8px}</style>
      <div id="resourceBars" aria-label="Shared resource utilisation"></div>
      <div id="resourceNumbers">Checking…</div>
      <div style="color:#52606d;margin-top:6px">Resources are shared and not reserved in advance. Your workspace starts when you sign in and resources allow (first come, first served), and stops after a period without activity. Your files are always kept.</div>
    </section>

    <div class="auth-tabs">
      <div id="tab-login" class="auth-tab ${tab === 'login' ? 'active' : ''}" onclick="switchTab('login')">เข้าสู่ระบบ</div>
      ${ALLOW_REGISTRATION ? `<div id="tab-register" class="auth-tab ${tab === 'register' ? 'active' : ''}" onclick="switchTab('register')">Create account</div>` : ''}
      <div id="tab-change" class="auth-tab ${tab === 'change' ? 'active' : ''}" onclick="switchTab('change')">เปลี่ยนรหัสผ่าน</div>
    </div>

    ${errorMsg ? `<div class="alert-badge alert-error">⚠️ ${errorMsg}</div>` : ''}
    ${successMsg ? `<div class="alert-badge alert-success">✅ ${successMsg}</div>` : ''}

    <!-- 1. Form: เข้าสู่ระบบ -->
    <div id="pane-login" class="tab-pane" style="display: ${tab === 'login' ? 'block' : 'none'};">
      <form method="POST" action="/login">
        ${LDAP_DIRECTORY ? `<div class="form-group"><label class="form-label" for="auth_provider">Sign in using</label><select id="auth_provider" name="auth_provider" class="form-control"><option value="ldap" ${authProvider==='ldap'?'selected':''}>AD / LDAP</option><option value="local" ${authProvider==='local'?'selected':''}>Local DSH account</option></select><p class="form-help">AD creates a private No Internet workspace on first sign-in. Internet access still requires administrator approval.</p></div>` : ''}
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
        <div class="form-group">
          <label class="form-label" for="login_application">Open after sign in</label>
          <select id="login_application" name="application" class="form-control">
            <option value="dsh">DSH workspace (Default)</option>
            <option value="applications" ${process.env.DSH_DEFAULT_APPLICATION==='applications'?'selected':''}>My applications</option>
            <option value="terminal">Web Terminal</option>
            <option value="jupyter">JupyterLab</option>
          </select>
          <div class="form-help">All choices use your private workspace in the selected environment. If Jupyter is stopped, start it from Web Terminal with jupyter lab.</div>
        </div>
        <button type="submit" class="btn-submit">เข้าสู่ระบบ (Sign In)</button>
      </form>
    </div>

    ${ALLOW_REGISTRATION ? `<!-- 2. Form: สร้างบัญชีผู้ใช้ใหม่ -->
    <div id="pane-register" class="tab-pane" style="display: ${tab === 'register' ? 'block' : 'none'};">
      <form method="POST" action="/register">
        <p class="env-note">Create your private No Internet workspace. Internet access requires administrator approval. There is no limit on accounts: your workspace starts when you sign in and shared resources allow. <span id="signupSlots" role="status" aria-live="polite">Checking registration…</span></p>
        <div class="form-group">
          <label class="form-label" for="reg_username">ชื่อผู้ใช้งานใหม่ (New Username)</label>
          <input type="text" id="reg_username" name="username" class="form-control" placeholder="ตัวอักษรภาษาอังกฤษหรือตัวเลข (เช่น johndoe)" pattern="[a-zA-Z0-9_\-\.]{3,30}" title="ยาว 3-30 ตัวอักษร ใช้ได้เฉพาะ a-z, 0-9, _, -" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg_password">รหัสผ่าน (Password)</label>
          <input type="password" id="reg_password" name="password" class="form-control" placeholder="At least 12 characters" minlength="12" maxlength="1024" autocomplete="new-password" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg_confirm">ยืนยันรหัสผ่าน (Confirm Password)</label>
          <input type="password" id="reg_confirm" name="confirm_password" class="form-control" placeholder="Confirm your password" minlength="12" maxlength="1024" autocomplete="new-password" required>
        </div>
        <button type="submit" class="btn-submit">Create account</button>
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

  </div>
  <a class="manual-fab" href="/manual/" target="_blank" rel="noopener"><span aria-hidden="true">?</span> User manual</a>
<script>
(()=>{const u=document.getElementById('login_username'),p=document.getElementById('login_password'),on=document.getElementById('internet-option');if(!u||!p||!on)return;let generation=0;
function reset(){generation++;on.disabled=document.getElementById('auth_provider')?.value!=='ldap';on.checked=false;const off=document.querySelector('input[name="internet"][value="off"]');if(off&&!off.disabled)off.checked=true;}
async function check(){reset();const provider=document.getElementById('auth_provider');if(provider&&provider.value==='ldap'){on.disabled=false;return;}const g=generation;if(!u.value||!p.value)return;try{const r=await fetch('/api/login-environments',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({username:u.value,password:p.value})});const d=await r.json();if(g===generation)on.disabled=!d.internetAllowed;}catch{}}
u.addEventListener('input',reset);p.addEventListener('input',reset);u.addEventListener('change',check);p.addEventListener('change',check);const provider=document.getElementById('auth_provider');if(provider){provider.addEventListener('change',check);if(provider.value==='ldap')on.disabled=false;}})();
(()=>{const label=document.getElementById('signupSlots');if(!label)return;let pending=false;
async function update(){if(pending||document.hidden)return;pending=true;const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
try{const response=await fetch('/api/signup-capacity',{cache:'no-store',credentials:'omit',signal:controller.signal});if(!response.ok)throw Error('unavailable');const data=await response.json();
if(!data.registrationEnabled){label.textContent='New account registration is unavailable.';return;}
if(!Number.isSafeInteger(data.remainingSlots)||data.remainingSlots<0)throw Error('invalid count');
label.textContent=data.signupAdmission&&!data.signupAdmission.allowed?'Registration is temporarily paused; it reopens automatically when storage recovers.'
  :data.remainingSlots>0?'Registration is open.'
  :data.signupAdmission?'A new private workspace is being prepared; registration reopens shortly.':'No new-user workspace is prepared. Please contact the administrator.';
}catch{label.textContent='Registration status unavailable. Please refresh or contact the administrator.';}finally{clearTimeout(timeout);pending=false;}}
update();setInterval(update,15000);window.addEventListener('focus',update);document.addEventListener('visibilitychange',update);})();
(()=>{const box=document.getElementById('resourceNumbers');if(!box)return;let pending=false;
const n=v=>Number.isSafeInteger(v)?String(v):'–',pct=v=>Number.isFinite(v)?Math.round(v)+'%':'–';
async function update(){if(pending||document.hidden)return;pending=true;const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
try{const r=await fetch('/api/status',{cache:'no-store',credentials:'omit',signal:controller.signal});if(!r.ok)throw Error('unavailable');const d=await r.json();
if(!d.available){box.textContent='Live workspace status is unavailable right now; you can still sign in.';return;}
const w=d.workspaces||{},free=Number.isSafeInteger(d.startsAvailableNow)?d.startsAvailableNow:null;
// Bars: light = reserved (held for running workspaces), dark = actually used. Built with DOM APIs only.
const bars=document.getElementById('resourceBars');
if(bars){bars.replaceChildren();
 const row=(label,reserved,used,caption)=>{const r=document.createElement('div');r.className='rs-row';
  const l=document.createElement('div');l.textContent=label;const b=document.createElement('div');b.className='rs-bar';b.setAttribute('role','meter');
  const clamp=v=>Math.max(0,Math.min(100,Number.isFinite(v)?v:0));
  if(Number.isFinite(reserved)){const x=document.createElement('div');x.className='rs-res';x.style.width=clamp(reserved)+'%';b.append(x);}
  if(Number.isFinite(used)){const x=document.createElement('div');x.className='rs-use';x.style.width=clamp(used)+'%';b.append(x);}
  b.setAttribute('aria-valuenow',String(Math.round(clamp(Number.isFinite(used)?used:reserved))));
  const c=document.createElement('div');c.className='rs-val';c.textContent=caption;r.append(l,b,c);bars.append(r);};
 const num=v=>Number.isFinite(v)?String(v):'–';
 if(d.cpu)row('CPU',d.cpu.reservedPercent,d.cpu.usedPercent,num(d.cpu.usedCores)+' used · '+num(d.cpu.reservedCores)+' reserved of '+num(d.cpu.totalCores)+' cores');
 if(d.memory)row('Memory',d.memory.reservedPercent,d.memory.usedPercent,num(d.memory.usedGiB)+' used · '+num(d.memory.reservedGiB)+' reserved of '+num(d.memory.totalGiB)+' GiB');
 if(d.gpu)row('GPU',d.gpu.allocatedPercent,undefined,num(d.gpu.allocated)+' of '+num(d.gpu.total)+' GPUs allocated (shared model server)');
 if(Number.isSafeInteger(w.capacity)&&w.capacity>0)row('Workspaces',100*((w.running||0)+(w.starting||0))/w.capacity,100*(w.running||0)/w.capacity,n(w.running)+' running · '+n(w.starting)+' starting · '+n(w.waiting)+' waiting · room for '+n(w.capacity)+' now');
 const legend=document.createElement('div');legend.className='rs-legend';const swatch=c=>{const i=document.createElement('i');i.style.background=c;return i;};
 legend.append(swatch('#2f6fed'),'used',swatch('#9fb3c8'),'reserved');bars.append(legend);
 const up=document.getElementById('resourceUpdated');if(up)up.textContent='· updated '+new Date().toLocaleTimeString();}
box.textContent=n(w.running)+' workspaces running · '+n(w.starting)+' starting · '+n(w.waiting)+' waiting · CPU '+pct(d.cpu?.reservedPercent)+' reserved ('+pct(d.cpu?.usedPercent)+' used) · Memory '+pct(d.memory?.reservedPercent)+' reserved ('+pct(d.memory?.usedPercent)+' used) · '+(free===null?'':free>0?free+' more workspaces can start now':'All resources in use: new sign-ins wait in a queue')+(Number.isSafeInteger(d.idleTimeoutMinutes)?' · idle workspaces stop after '+d.idleTimeoutMinutes+' min':'');
}catch{box.textContent='Live workspace status is unavailable right now; you can still sign in.';}finally{clearTimeout(timeout);pending=false;}}
update();setInterval(update,15000);window.addEventListener('focus',update);document.addEventListener('visibilitychange',update);})();
</script>
</body>
</html>`;
}

const server = http.createServer((req, res) => {
  try{if(handlePublicAlias(req,res))return;if(handleExternalAlias(req,res))return;}catch{res.writeHead(503);return res.end('External application policy unavailable.');}
  const parsedUrl = url.parse(req.url, true);
  if(APP_SIGNIN && req.method==='GET' && parsedUrl.pathname==='/login' && Object.hasOwn(parsedUrl.query,'app')) {
    // Native form POSTs need a same-origin Origin header for the strict CSRF check.
    // no-referrer makes browsers send Origin: null, even for this same-origin form.
    const headers={'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'same-origin','X-Frame-Options':'DENY', 'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"};
    try {
      if(req.headers.host!==process.env.DSH_TRUSTED_HOST)throw Error();
      const app=parsedUrl.query.app;
      // Public mappings have no DSH sign-in step. Reuse the live route policy;
      // never accept a caller-supplied destination or create a session.
      if(typeof app==='string' && appHostName(app+'.'+APP_DOMAIN)===app && publicApp(app)) {
        res.writeHead(303,{'Location':'https://'+app+'.'+APP_DOMAIN+'/', 'Cache-Control':'no-store'});
        return res.end();
      }
      const body=APP_SIGNIN.begin(app,res,'',parsedUrl.query.environment);
      headers['Content-Security-Policy']=res.getHeader('Content-Security-Policy');
      res.writeHead(200,headers);return res.end(body);
    }
    catch {res.writeHead(404,headers);return res.end('Application sign-in unavailable.');}
  }
  // Public, aggregate-only view of shared resources for the sign-in page.
  if(parsedUrl.pathname==='/api/status') {
    const headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
    if(req.method!=='GET'){res.writeHead(405,{...headers,Allow:'GET'});return res.end(JSON.stringify({error:'Method not allowed'}));}
    try{res.writeHead(200,headers);return res.end(JSON.stringify(sharedResourceStatus()));}
    catch{res.writeHead(503,headers);return res.end(JSON.stringify({error:'Resource status unavailable'}));}
  }
  if(parsedUrl.pathname==='/api/signup-capacity') {
    const headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
    if(req.method!=='GET'){res.writeHead(405,{...headers,Allow:'GET'});return res.end(JSON.stringify({error:'Method not allowed'}));}
    try{const data=signupCapacitySummary();res.writeHead(200,headers);return res.end(JSON.stringify({observedAt:data.observedAt,
      registrationEnabled:data.registrationEnabled,remainingSlots:data.registrationEnabled?data.remainingSlots:null,
      ...(data.signupAdmission?{signupAdmission:data.signupAdmission}:{})}));}
    catch{res.writeHead(503,headers);return res.end(JSON.stringify({error:'New-user capacity unavailable'}));}
  }
  // Platform pages always use the canonical host; app roots keep their owned port.
  if(appHostName(req.headers.host) && req.method==='GET' && ['/login','/applications','/terminal','/term'].includes(parsedUrl.pathname)) {
    const app=appHostName(req.headers.host);
    res.writeHead(302,{Location:'https://'+process.env.DSH_TRUSTED_HOST+(APP_SIGNIN?'/login?app='+encodeURIComponent(app):parsedUrl.pathname)});return res.end();
  }
  // Reauthentication must stay at the gateway even while its cookie is valid.
  // A workspace session can end independently; forwarding /login to that workspace
  // prevents the user from reaching this form. Keep existing sessions and drafts.
  if (req.method === 'GET' && parsedUrl.pathname === '/login') {
    const tab = ['login', 'register', 'change'].includes(parsedUrl.query.tab) ? parsedUrl.query.tab : 'login';
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    return res.end(renderAuthPage({ tab }));
  }
  const courseRoute = routeFor(parsedUrl.pathname, req.headers.host);
  if (!courseRoute && (parsedUrl.pathname === '/manual' || parsedUrl.pathname.startsWith('/manual/'))) return serveManual(req,res,parsedUrl.pathname);
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
      let username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const password = params.get('password') || '';
      const authProvider = params.get('auth_provider') || (LDAP_DIRECTORY ? 'ldap' : 'local');
      let appContext=null;
      if(params.has('app_login')) {
        try {if(!APP_SIGNIN)throw Error();appContext=APP_SIGNIN.consume(req,params,value=>authProvider==='ldap'&&LDAP_DIRECTORY?normalizeUsername(value,LDAP_DIRECTORY.config.domain):value.trim().toLowerCase());}
        catch {res.writeHead(403,{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store'});return res.end('Application sign-in expired or access denied. Reopen the application.');}
      }
      let loginPageFailureStatus=0;
      const loginPage=options=>{
        if(!appContext)return renderAuthPage({...options,authProvider});
        try {APP_SIGNIN.assertCurrent(appContext);}catch {loginPageFailureStatus=403;return 'Application access changed. Reopen the application.';}
        try {return APP_SIGNIN.begin(appContext.name,res,options.errorMsg||'',appContext.internet,authProvider);}
        catch {loginPageFailureStatus=503;return 'Application sign-in unavailable. Reopen the application and retry.';}
      };
      const internet = appContext ? appContext.sessionInternet : normalizeInternetMode(params.get('internet'));
      const launchPaths = {dsh:'/', terminal:'/terminal', jupyter:'/proxy/8888/lab', applications:'/applications'};
      const application = appContext ? 'dsh' : params.get('application') || process.env.DSH_DEFAULT_APPLICATION || 'dsh';
      if (!Object.hasOwn(launchPaths, application)) { res.writeHead(400); return res.end('Choose DSH, Web Terminal or JupyterLab.'); }

      let identity;
      try { identity = await authenticateIdentity(username, password, authProvider); }
      catch(error) {
        const known=error instanceof DirectoryError;
        if(!known||error.code!=='LDAP_LOCAL_ACCOUNT_CONFLICT')auditEvent('login.directory-denied',username,'off');
        const response=loginPage({tab:'login',authProvider,errorMsg:known?error.message:'AD sign-in is temporarily unavailable. Contact the administrator.'});
        res.writeHead(loginPageFailureStatus||(known?error.status:503),{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-DSH-Auth-Error':known?error.code:'LDAP_UNAVAILABLE'});return res.end(response);
      }
      if(identity)username=identity.user;
      USERS = loadUsers();
      if (identity && (!LEGACY_OWNER || username === LEGACY_OWNER) && USERS[username]?.disabled !== true && accountEnabled(username)) {
        if(appContext){try{APP_SIGNIN.assertCurrent(appContext);if(!appVisitorAllowed(appContext,username,USERS[username]))throw Error('Account cannot access this application');if(gatedAliasRecoveryContext(appContext.name)?.stamp!==appContext.stamp)throw Error('Application access changed');}catch{res.writeHead(403,{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store'});return res.end('Application access changed. Reopen the application.');}}
        if (internet === 'on' && !internetAllowed(username)) { res.writeHead(403); return res.end('Internet environment requires administrator approval.'); }
        if (!isSharedPolicy(appContext?.visitorPolicy) && !getEnvironmentTarget(internet, username)) {
          res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end('No dedicated runtime provisioned for this identity and environment.');
        }
        if (!isSharedPolicy(appContext?.visitorPolicy) && !setUserInternetMode(username, internet)) {
          const body=loginPage({ tab: 'login', errorMsg: 'ไม่สามารถบันทึกนโยบาย Internet access ได้ กรุณาลองใหม่อีกครั้ง' });
          res.writeHead(loginPageFailureStatus||500, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control':'no-store' });
          return res.end(body);
        }
        if (!auditEvent('login.success', username, internet)) { res.writeHead(503); return res.end('Audit storage unavailable.'); }
        const sessionId = crypto.randomBytes(24).toString('hex');
        try { SESSIONS.set(sessionId, { user: username, internet, created: Date.now(), accountStamp:sessionAccountStamp(username) }); }
        catch { res.writeHead(503,{'Content-Type':'text/plain; charset=utf-8'});return res.end('Sign-in storage unavailable. Please retry later.'); }

        if(appContext) {
          res.writeHead(303,{'Set-Cookie':`${COOKIE_NAME}=${sessionId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400${getCookieDomain()}${COOKIE_TRANSPORT}`,'Location':appContext.destination,'Cache-Control':'no-store'});
          return res.end();
        }

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
            'Location': (appHostName(req.headers.host) ? 'https://'+process.env.DSH_TRUSTED_HOST : '')+launchPaths[application]
          });
          return res.end();
        });
      } else {
        auditEvent('login.denied', username, 'off');
        console.log(`[AUTH-PROXY] Failed login attempt for user: ${username}`);
        const body=loginPage({ tab: 'login', errorMsg: 'ชื่อผู้ใช้งานหรือรหัสผ่านไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง' });
          res.writeHead(loginPageFailureStatus||401, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control':'no-store' });
          return res.end(body);
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
    if(req.headers.origin){try{if(new URL(req.headers.origin).host!==(process.env.DSH_TRUSTED_HOST||req.headers.host)){res.writeHead(403);return res.end('Cross-origin registration denied.');}}catch{res.writeHead(403);return res.end('Invalid origin.');}}
    if(!admitRegistration(req.socket.remoteAddress||'unknown')){res.writeHead(429,{'Retry-After':'900'});return res.end('Too many registration attempts. Please try again later.');}
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      const params = new URLSearchParams(body);
      const username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const password = params.get('password') || '';
      const confirmPassword = params.get('confirm_password') || '';

      if (!username || !/^[a-z0-9_\-\.]{3,30}$/.test(username)) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'ชื่อผู้ใช้งานต้องเป็นภาษาอังกฤษ/ตัวเลข ความยาว 3-30 ตัวอักษร' }));
      }

      if (!password || password.length < 12 || Buffer.byteLength(password) > 1024 || password!==password.trim()) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'Use a password of at least 12 characters without surrounding spaces.' }));
      }

      if (password !== confirmPassword) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน กรุณาตรวจสอบอีกครั้ง' }));
      }

      USERS = loadUsers();
      if (Object.hasOwn(USERS,username) || ADMIN_USERS.has(username) || Object.hasOwn(USER_TARGETS,username)) {
        res.writeHead(409, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: `ชื่อผู้ใช้งาน "${username}" มีอยู่ในระบบแล้ว กรุณาใช้ชื่ออื่นหรือเข้าสู่ระบบ` }));
      }

      const created=newAccountRecord(USERS,username,password);
      if(created.error){res.writeHead(created.status,{'Content-Type':'text/html; charset=utf-8'});return res.end(renderAuthPage({tab:'register',errorMsg:created.error}));}
      if(!auditEvent('account.create',username,'off',username)){res.writeHead(503);return res.end('Audit storage unavailable.');}
      USERS[username] = created.record;
      if (saveUsers(USERS)) {
        try {
          fs.mkdirSync(`${USER_ROOT}/${username}`, { recursive: true });
        } catch (e) {}
        console.log(`[AUTH-PROXY] Successfully registered new user: ${username}`);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', successMsg: `Account "${username}" created. Sign in to your private No Internet workspace. Internet requires admin approval.` }));
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
      if(USERS[username]?.authProvider==='ldap'){res.writeHead(403,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});return res.end(renderAuthPage({tab:'change',errorMsg:'AD passwords are managed by the corporate directory. Use the corporate password-change process.'}));}
      if ((LEGACY_OWNER && username !== LEGACY_OWNER) || USERS[username]?.disabled === true || !await verifyPassword(oldPassword, USERS[username])) {
        res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'ชื่อผู้ใช้งานหรือรหัสผ่านเดิมไม่ถูกต้อง' }));
      }

      USERS = loadUsers();
      if (USERS[username]?.disabled === true) { res.writeHead(403); return res.end('Account disabled.'); }
      USERS[username] = { ...USERS[username], ...hashPassword(newPassword) };
      if (saveUsers(USERS)) {
        console.log(`[AUTH-PROXY] Successfully changed password for user: ${username}`);
        try { revokeUserSessions(username); }
        catch(error) { console.error('[AUTH-PROXY] Session revocation failed:',error.code||error.name);res.writeHead(503);return res.end('Password saved; session revocation needs operator review.'); }
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
          try { SESSIONS.delete(sid); }
          catch { res.writeHead(503);return res.end('Sign-out storage unavailable. Please retry.'); }
          if(s){for(const socket of SESSION_SOCKETS.get(s)||[])socket.destroy();SESSION_SOCKETS.delete(s);}
          // Signing out releases the workspace at once unless another session uses it.
          if(s&&SESSION_DEMAND&&![...SESSIONS.values()].some(x=>x.user===s.user)){const t=privateTargetsFor(s.user);if(t)SESSION_DEMAND.release(Object.values(t));}
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
  if (!authenticated && APP_SIGNIN && !(courseRoute && courseRoute.hostAllowed) && appHostName(req.headers.host) && req.method==='GET' && !parsedUrl.pathname.startsWith('/api/')) {
    res.writeHead(303,{Location:'https://'+process.env.DSH_TRUSTED_HOST+'/login?app='+encodeURIComponent(appHostName(req.headers.host)), 'Cache-Control':'no-store'});return res.end();
  }
  if (!authenticated) {
    if (courseRoute) { res.writeHead(303, {'Location':'/login','Cache-Control':'no-store'}); return res.end(); }
    // API consumers must never receive an HTML sign-in page with HTTP 200.
    if (parsedUrl.pathname.startsWith('/api/') || /^\/proxy\/8888\/api(?:\/|$)/.test(parsedUrl.pathname)) {
      res.writeHead(401, {'Content-Type':'application/json; charset=utf-8',
        'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-DSH-Auth-Required':'1'});
      return res.end(JSON.stringify({error:'AUTHENTICATION_REQUIRED',message:'Your sign-in session ended. Sign in again.',loginUrl:'/login'}));
    }
    const tab = parsedUrl.query.tab || 'login';
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(renderAuthPage({ tab }));
  }

  if (courseRoute) return serveCourse(req, res, courseRoute);

  if(PACKAGE_PORTAL && (parsedUrl.pathname==='/packages'||parsedUrl.pathname==='/api/packages')){
    if(parsedUrl.pathname==='/packages'){res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Frame-Options':'DENY'});return res.end(require('./package_portal').page());}
    if(req.method!=='GET' && req.headers.origin!=='https://'+(process.env.DSH_TRUSTED_HOST||req.headers.host)){
      res.writeHead(403,{'Content-Type':'application/json'});return res.end(JSON.stringify({error:'Cross-origin package request denied.'}));
    }
    try{projectPackageAccess();return PACKAGE_PORTAL.handle(req,res,sessionUser,activeSession,()=>accountEnabled(sessionUser)&&internetAllowed(sessionUser),()=>auditEvent('package.request',sessionUser,activeSession.internet));}
    catch{res.writeHead(503,{'Content-Type':'application/json'});return res.end(JSON.stringify({error:'Package service unavailable.'}));}
  }

  // Reserve admin routes before any app forwarding or environment lookup.
  if (parsedUrl.pathname === '/admin' || parsedUrl.pathname.startsWith('/api/admin/')) {
    const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer' };
    if (!ADMIN_USERS.has(sessionUser)) { auditEvent('admin.denied', sessionUser, activeSession.internet); res.writeHead(403, headers); return res.end('Administrator access required.'); }
    if(parsedUrl.pathname==='/api/admin/apps') {
      const reply=(status,data)=>{res.writeHead(status,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data));};
      try {
        if(req.method==='GET'){activeSession.adminCsrf ||= crypto.randomBytes(32).toString('hex');const data=adminApps();return clarifyLegacyJupyterLabels(data.managedServices).then(()=>{if(!accountEnabled(sessionUser)||!ADMIN_USERS.has(sessionUser)||![...SESSIONS.values()].includes(activeSession))return reply(401,{error:'Administrator session ended.'});return reply(200,{...data,csrfToken:activeSession.adminCsrf});}).catch(()=>reply(503,{error:'Service inventory unavailable.'}));}
        if(req.method!=='POST')return reply(405,{error:'Use GET or POST.'});
        if(!activeSession.adminCsrf||req.headers['x-dsh-admin-csrf']!==activeSession.adminCsrf)return reply(403,{error:'Invalid management token.'});
        try {if(new URL(req.headers.origin).host!==(process.env.DSH_TRUSTED_HOST||req.headers.host))return reply(403,{error:'Same-origin management required.'});}catch{return reply(403,{error:'Same-origin management required.'});}
        if(!String(req.headers['content-type']||'').startsWith('application/x-www-form-urlencoded'))return reply(415,{error:'Form encoding required.'});
        let body='',large=false;req.on('data',chunk=>{if(large)return;body+=chunk;if(Buffer.byteLength(body)>4096){large=true;reply(413,{error:'Request too large.'});}});
        req.on('end',()=>{if(large)return;try {
          if(!accountEnabled(sessionUser)||!ADMIN_USERS.has(sessionUser)||![...SESSIONS.values()].includes(activeSession))return reply(403,{error:'Administrator session ended.'});
          const f=new URLSearchParams(body),action=f.get('action'),owner=f.get('user'),name=f.get('name'),all=appLinks(),users=loadUsers();
          const scope=f.get('target')||'main';
          if(!['limit','edit','enable','disable','delete','service-save','service-start','service-stop','service-restart','service-delete'].includes(action)||!owner||(!action.startsWith('service-')&&scope!=='main')||(scope==='main'&&!Object.hasOwn(users,owner)))return reply(400,{error:'Choose an existing account and action.'});
          if(action.startsWith('service-')){
            const mode=f.get('environment');if(!['off','on'].includes(mode))return reply(400,{error:'Select a valid environment'});
            let desired;try{desired=serviceChange(owner,mode,f,scope);}catch(e){return reply(400,{error:e instanceof SyntaxError?'Invalid command JSON':e.message});}
            const detail={owner,name:f.get('service'),mode,target:scope,outcome:'requested'};
            if(!auditEvent('application.lifecycle',sessionUser,activeSession.internet,owner,detail))return reply(503,{error:'Audit unavailable'});
            if(action==='service-start'&&JSON.stringify(desired)===JSON.stringify(readServices(owner,mode,scope))){
              const logged=auditEvent('application.lifecycle',sessionUser,activeSession.internet,owner,{...detail,outcome:'unchanged'});
              return reply(logged?200:503,{message:'Service is already enabled. Its process and settings were left unchanged.',updated:false});
            }
            writeServices(owner,mode,desired,scope);const logged=auditEvent('application.lifecycle',sessionUser,activeSession.internet,owner,{...detail,outcome:'applied'});
            return reply(logged?200:503,{message:'Service definition saved. Supervisor applies it within a few seconds.',updated:true});
          }
          const details={owner,name,outcome:'requested'};let policy;
          if(action==='limit') {
            const raw=f.get('limit');if(!/^(0|[1-9][0-9]{0,3})$/.test(raw||'')||Number(raw)>SITE_APP_LIMIT)return reply(400,{error:'Use a whole-number limit from 0 to '+SITE_APP_LIMIT+'.'});
            policy=appPolicy();details.previousLimit=appLimit(owner,policy);details.limit=Number(raw);policy.limits[owner]=details.limit;
          }else{
            if(!validAppName(name)||!Object.hasOwn(all,name)||all[name].owner!==owner)return reply(404,{error:'Application mapping not found for this owner.'});
            if(action==='edit') {
              if(isSharedPolicy(all[name].visitorPolicy))return reply(400,{error:"Edit a shared application's target from its owner's Applications page; administrators can disable or remove it here."});
              const mode=f.get('environment'),port=Number(f.get('port'));
              if(!['off','on'].includes(mode)||!validAppPort(port)||!getEnvironmentTarget(mode,owner))return reply(400,{error:'Choose a provisioned environment and valid application port.'});
              details.mode=mode;details.previousPort=all[name].ports?.[mode];details.port=port;all[name].ports={...all[name].ports,[mode]:port};
            }else if(action==='delete')delete all[name];else all[name].enabled=action==='enable';
            if(all[name]){all[name].updatedAt=new Date().toISOString();all[name].updatedBy=sessionUser;}
          }
          if(!auditEvent('application.'+action,sessionUser,activeSession.internet,owner,details))return reply(503,{error:'Audit storage unavailable.'});
          if(action==='limit')saveAppPolicy(policy);else {saveAppLinks(all);closeAppConnections(name);}
          const confirmed=auditEvent('application.'+action,sessionUser,activeSession.internet,owner,{...details,outcome:'applied'});
          return reply(confirmed?200:503,{updated:true,...(!confirmed?{error:'Change saved; audit confirmation unavailable.'}:{message:'Application '+action+' saved.'})});
        }catch{return reply(503,{error:'Application management storage unavailable.'});}});return;
      }catch{return reply(503,{error:'Application inventory unavailable.'});}
    }
    if (parsedUrl.pathname === '/api/admin/users') {
      const reply=(status,data)=>{res.writeHead(status,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(data));};
      if(req.method==='GET') {
        activeSession.adminCsrf ||= crypto.randomBytes(32).toString('hex');
        return reply(200,{users:adminAccounts(),csrfToken:activeSession.adminCsrf,
          registrationEnabled:ALLOW_REGISTRATION,signupWorkspacesAvailable:freeSignupSlots().length,
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
            const password=fields.get('password')||'';
            const created=newAccountRecord(users,user,password);
            if(created.error)return reply(created.status,{error:created.error});
            users[user]=created.record;
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
    if(parsedUrl.pathname==='/api/admin/capacity') {
      const reply=(code,value)=>{res.writeHead(code,{...headers,'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(value));};
      if(!CAPACITY)return reply(409,{error:'Automatic provisioning is not installed.'});
      if(req.method==='GET'){activeSession.adminCsrf ||= crypto.randomBytes(32).toString('hex');return reply(200,{...signupCapacitySummary(),csrfToken:activeSession.adminCsrf});}
      if(req.method!=='POST')return reply(405,{error:'Method not allowed.'});
      if(!activeSession.adminCsrf||req.headers['x-dsh-admin-csrf']!==activeSession.adminCsrf)return reply(403,{error:'Invalid management token.'});
      const origin=req.headers.origin;if(origin&&origin!=='https://'+process.env.DSH_TRUSTED_HOST&&origin!=='http://'+process.env.DSH_TRUSTED_HOST)return reply(403,{error:'Invalid origin.'});
      if(!String(req.headers['content-type']||'').startsWith('application/x-www-form-urlencoded'))return reply(415,{error:'Use a form request.'});
      let body='',tooLarge=false;req.on('data',chunk=>{if(tooLarge)return;body+=chunk;if(Buffer.byteLength(body)>2048){tooLarge=true;reply(413,{error:'Capacity form too large'});}});
      req.on('end',()=>{if(tooLarge||res.writableEnded)return;try{
        if(!accountEnabled(sessionUser)||![...SESSIONS.values()].includes(activeSession))return reply(403,{error:'Session expired.'});
        const f=new URLSearchParams(body);const integer=name=>{const x=f.get(name);if(!/^(?:0|[1-9][0-9]*)$/.test(x||''))throw Error('Use whole-number capacity limits');return Number(x);};
        if(!['true','false'].includes(f.get('enabled')))throw Error('Choose automatic provisioning on or off');
        const value={version:1,enabled:f.get('enabled')==='true',maxAccounts:integer('maxAccounts'),warmSpareSlots:integer('warmSpareSlots')};
        require('./capacity_policy').validatePolicy(value,Object.keys(loadUsers()).length);
        if(!auditEvent('capacity.policy',sessionUser,activeSession.internet,sessionUser,{...value,outcome:'requested'}))return reply(503,{error:'Audit unavailable.'});
        CAPACITY.save(value,loadUsers());
        const logged=auditEvent('capacity.policy',sessionUser,activeSession.internet,sessionUser,{...value,outcome:'applied'});
        return reply(logged?200:503,{...signupCapacitySummary(),updated:true});
      }catch(error){return reply(400,{error:error.message});}});return;
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
  if (USER_CREDENTIALS && ['/credentials','/api/user-credentials'].includes(parsedUrl.pathname)) {
    if (req.headers.host !== process.env.DSH_TRUSTED_HOST) { res.writeHead(403); return res.end('Use the main DSH site to manage credentials.'); }
    const authorized=()=>accountEnabled(sessionUser)&&(internetMode==='off'||internetAllowed(sessionUser))&&
      Date.now()<activeSession.created+SESSION_TTL_MS&&activeSession.accountStamp===sessionAccountStamp(sessionUser)&&[...SESSIONS.values()].includes(activeSession);
    let credentialOwner;try{credentialOwner=require('./credential_identity').subjectFor(sessionUser,{load:loadUsers,save:saveUsers,audit:()=>auditEvent('credential.identity',sessionUser,internetMode)});}catch{res.writeHead(503);return res.end('Credential identity unavailable.');}
    return USER_CREDENTIALS.handle(req,res,{owner:credentialOwner,environment:internetMode,session:activeSession,authorized,
      reauthenticate:async password=>{const result=await authenticateIdentity(sessionUser,password,loadUsers()[sessionUser]?.authProvider==='ldap'?'ldap':'local',{create:false});return result?.user===sessionUser;},
      audit:event=>auditEvent(event,sessionUser,internetMode)});
  }
  // Signing in reserves: a stopped workspace cold-starts when resources allow.
  if(SESSION_DEMAND){
    SESSION_DEMAND.touch(environmentTarget);
    const runtime=SESSION_DEMAND.state(environmentTarget);
    if(RUNTIME_WAITING.includes(runtime.state))return sendRuntimeWait(req,res,runtime);
  }


  // Only this authenticated user's selected Main runtime can receive a fixed start.
  const jupyterContext = USER_TARGETS && JUPYTER_DEMAND ? {
    user:sessionUser,mode:internetMode,target:environmentTarget,session:activeSession,
    trustedHost:process.env.DSH_TRUSTED_HOST,
    authorized:()=>accountEnabled(sessionUser)&&(internetMode==='off'||internetAllowed(sessionUser))&&
      JUPYTER_DEMAND_MODULE.sessionAuthorized(activeSession,SESSIONS,sessionAccountStamp(sessionUser),SESSION_TTL_MS)&&getEnvironmentTarget(internetMode,sessionUser)?.host===environmentTarget.host,
    allowed:()=>{try{const d=readServices(sessionUser,internetMode);return d.allowed&&!(d.services.jupyter&&d.services.jupyter.enabled===false);}catch{return false;}},
    managed:()=>{try{return readServices(sessionUser,internetMode).services.jupyter?.enabled===true;}catch{return false;}},
    audit:()=>auditEvent('jupyter.start',sessionUser,internetMode)
  } : null;
  if(parsedUrl.pathname==='/api/jupyter/start' && jupyterContext) {
    JUPYTER_DEMAND.start(req,res,jupyterContext).catch(()=>{if(!res.destroyed&&!res.headersSent){res.writeHead(503,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify({error:'JUPYTER_START_UNAVAILABLE'}));}});return;
  }

  if (parsedUrl.pathname === '/applications') {
    res.writeHead(200, {'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY'});
    return res.end(renderApplications());
  }
  if (parsedUrl.pathname === '/api/app-links') {
    const reply=(s,v)=>{res.writeHead(s,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(v));};
    try {
      if(req.method==='GET') {
        const all=appLinks();activeSession.appCsrf ||= crypto.randomBytes(32).toString('hex');
        const name=parsedUrl.query.name;
        if(name!==undefined) {if(!validAppName(name))return reply(400,{error:'Use 3–63 lowercase letters, digits and hyphens; built-in names are reserved.'});const host=appHostnameState(name);if(host.error)return reply(503,{error:host.error});return reply(200,{available:host.available&&(!Object.hasOwn(all,name)||all[name].owner===sessionUser),hostname:APP_DOMAIN?name+'.'+APP_DOMAIN:null});}
        return reply(200,{used:Object.values(all).filter(e=>e.owner===sessionUser).length,limit:appLimit(sessionUser),defaultName:sessionUser.replace(/[_.]/g,'-')+'-jupyter',csrfToken:activeSession.appCsrf,hostnameDomain:APP_DOMAIN||null,localUsers:Object.entries(loadUsers()).filter(([u,a])=>u!==sessionUser&&a.authProvider!=='ldap'&&a.disabled!==true).map(([u])=>u).sort(),links:Object.entries(all).filter(([name,e])=>e.owner===sessionUser&&(validAppPort(e.ports?.[internetMode])||externalAppTarget(name,sessionUser,internetMode))).map(([name,e])=>{const host=appHostnameState(name),external=externalAppTarget(name,sessionUser,internetMode);return {name,accessMode:e.accessMode||'authenticated',visitorPolicy:e.visitorPolicy||'owner-only',allowedUsers:['selected-users','selected-local-users'].includes(e.visitorPolicy)?e.allowedUsers:[],sharedEnvironment:e.sharedEnvironment||null,publicEnvironment:e.publicEnvironment||null,enabled:e.enabled!==false,type:external?'external':'port',targetUrl:external?external.url.href:null,port:e.ports?.[internetMode]||null,url:(external||isSharedPolicy(e.visitorPolicy))?'https://'+name+'.'+APP_DOMAIN+'/':'/proxy/'+name+'/'+(e.ports[internetMode]===8888?'lab':''),hostname:APP_DOMAIN?name+'.'+APP_DOMAIN:null,hostnameUrl:APP_DOMAIN&&host.available&&host.ready?'https://'+name+'.'+APP_DOMAIN+'/':null};})});
      }
      if(req.method!=='POST')return reply(405,{error:'Use GET or POST.'});
      if(!activeSession.appCsrf||req.headers['x-dsh-app-csrf']!==activeSession.appCsrf)return reply(403,{error:'Invalid application token.'});
      try {if(new URL(req.headers.origin).host!==(process.env.DSH_TRUSTED_HOST||req.headers.host))return reply(403,{error:'Cross-origin change denied.'});}catch{return reply(403,{error:'Same-origin request required.'});}
      if(!String(req.headers['content-type']||'').startsWith('application/x-www-form-urlencoded'))return reply(415,{error:'Form encoding required.'});
      let body='',large=false;req.on('data',b=>{if(large)return;body+=b;if(Buffer.byteLength(body)>16384){large=true;reply(413,{error:'Request too large.'});}});
      req.on('end',()=>{if(large)return;try {
        if(!accountEnabled(sessionUser)||![...SESSIONS.values()].includes(activeSession))return reply(403,{error:'Session ended.'});
        const f=new URLSearchParams(body),name=f.get('name'),port=Number(f.get('port')),type=f.get('type')||'port',action=f.get('action'),all=appLinks(),accessMode=f.get('accessMode')||all[f.get('name')]?.accessMode||'authenticated',visitorPolicy=f.get('visitorPolicy')||all[f.get('name')]?.visitorPolicy||(Object.hasOwn(all,f.get('name'))||type==='port'&&privateLocalPort(port)?'owner-only':'signed-in-users');
        if(!validAppName(name)||!['save','delete'].includes(action))return reply(400,{error:'Invalid application name or action.'});
        if(Object.hasOwn(all,name)&&all[name].owner!==sessionUser)return reply(409,{error:'Name reserved. Choose another name.'});
        if(action==='save') {
          if(!['authenticated','public'].includes(accessMode))return reply(400,{error:'Choose authenticated or public access.'});
          if(!['owner-only','signed-in-users','selected-users','local-users','ldap-users','selected-local-users'].includes(visitorPolicy))return reply(400,{error:'Choose owner-only or enabled DSH accounts.'});
          const shared=accessMode==='authenticated'&&isSharedPolicy(visitorPolicy);
          let allowedUsers=[];if(shared&&['selected-users','selected-local-users'].includes(visitorPolicy)){try{allowedUsers=JSON.parse(f.get('allowedUsers')||'[]');if(!Array.isArray(allowedUsers)||!allowedUsers.length||allowedUsers.length>128||allowedUsers.some(u=>typeof u!=='string'||!/^[a-z0-9_.-]{1,64}$/.test(u)||u===sessionUser||!accountEnabled(u)||(visitorPolicy==='selected-local-users'&&loadUsers()[u]?.authProvider==='ldap'))||new Set(allowedUsers).size!==allowedUsers.length)throw Error();allowedUsers.sort();}catch{return reply(400,{error:'Choose 1–128 distinct enabled accounts other than yourself.'});}}
          if(shared&&type==='port'&&(privateLocalPort(port)||!validAppPort(port)))return reply(400,{error:'JupyterLab, terminals and management ports remain owner-only.'});
          if(shared&&(Object.keys(all[name]?.ports||{}).some(mode=>mode!==internetMode)||(type==='port'&&Object.keys(all[name]?.targets||{}).length)||(type==='external'&&Object.keys(all[name]?.ports||{}).length)))return reply(400,{error:'Use a separate alias with one target environment for a shared application.'});
          if(accessMode==='public'&&type==='port'&&[7681,8888].includes(port))return reply(400,{error:'Terminal and notebook management ports cannot be published without DSH authentication.'});
          const host=appHostnameState(name);if(host.error)return reply(503,{error:host.error});if(!host.available)return reply(409,{error:'This name belongs to an existing site. Choose another name.'});
          if(shared&&(!APP_SIGNIN||!APP_DOMAIN||!host.ready))return reply(409,{error:'Authenticated sharing requires an approved application hostname and application sign-in.'});
          if(!['port','external'].includes(type))return reply(400,{error:'Choose a local port or external HTTPS URL.'});
          let approved;
          if(type==='external'){
            if(!APP_DOMAIN||!host.ready)return reply(409,{error:'An approved application hostname is required.'});
            try{approved=EXTERNAL_PROXY.resolveTarget({owner:sessionUser,targets:{[internetMode]:{type:'external',url:f.get('targetUrl')}}},sessionUser,internetMode,externalPolicies());}
            catch{return reply(400,{error:'Choose an approved HTTPS application URL.'});}
          }else if(!validAppPort(port))return reply(400,{error:'Choose an application port from 1024–65535; management ports are reserved.'});
          if(!Object.hasOwn(all,name)&&(Object.keys(all).length>=SITE_APP_LIMIT||Object.values(all).filter(e=>e.owner===sessionUser).length>=appLimit(sessionUser)))return reply(409,{error:'Application URL quota reached.'});
          all[name]={...all[name],owner:sessionUser,accessMode,publicEnvironment:accessMode==='public'?internetMode:null,updatedAt:new Date().toISOString(),updatedBy:sessionUser,ports:{...(all[name]?.ports||{})},targets:{...(all[name]?.targets||{})}};
          delete all[name].allowedUsers;
          if(shared){all[name].visitorPolicy=visitorPolicy;all[name].sharedEnvironment=internetMode;if(['selected-users','selected-local-users'].includes(visitorPolicy))all[name].allowedUsers=allowedUsers;}
          else{delete all[name].visitorPolicy;delete all[name].sharedEnvironment;}
          if(type==='external'){delete all[name].ports[internetMode];all[name].targets[internetMode]={type:'external',url:approved.url.href};}
          else{all[name].ports[internetMode]=port;delete all[name].targets[internetMode];}
        } else if(Object.hasOwn(all,name)) {if(all[name].ports)delete all[name].ports[internetMode];if(all[name].targets)delete all[name].targets[internetMode];if(all[name].sharedEnvironment===internetMode){delete all[name].visitorPolicy;delete all[name].sharedEnvironment;}if(!Object.keys(all[name].ports||{}).length&&!Object.keys(all[name].targets||{}).length)delete all[name];}
        if(!auditEvent('application.'+action,sessionUser,internetMode,undefined,{owner:sessionUser,name,mode:internetMode,outcome:'requested'}))return reply(503,{error:'Audit storage unavailable.'});
        saveAppLinks(all);closeAppConnections(name);if(!auditEvent('application.'+action,sessionUser,internetMode,undefined,{owner:sessionUser,name,mode:internetMode,outcome:'applied'}))return reply(503,{error:'Change saved; audit confirmation unavailable.'});return reply(200,{message:action==='save'?'Application URL saved.':'Application URL removed.'});
      }catch{return reply(503,{error:'Application URL storage unavailable.'});}});return;
    }catch{return reply(503,{error:'Application URL storage unavailable.'});}
  }

  if (req.method === 'GET' && parsedUrl.pathname === '/api/auth/session') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    return res.end(JSON.stringify({ user: sessionUser, internet: internetMode, environment: environmentTarget.name }));
  }

  // Convenient Terminal Shortcuts (/terminal, /term)
  if (parsedUrl.pathname === '/terminal' || parsedUrl.pathname === '/term') {
    res.writeHead(302, { 'Location': '/proxy/terminal/' });
    return res.end();
  }
  if (parsedUrl.pathname === '/jupyter') {
    res.writeHead(302, { 'Location': '/proxy/8888/lab' });
    return res.end();
  }

  // Dynamic App Gateway (Option 1 Subdomain or Option 2 Path Proxy); only reachable after login
  if (!auditEvent('runtime.http', sessionUser, internetMode)) { res.writeHead(503); return res.end('Audit storage unavailable.'); }
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const hostAlias=appHostName(incomingHost);
  const externalTarget=hostAlias&&externalAppTarget(hostAlias,sessionUser,internetMode);
  if(externalTarget&&(!process.env.DSH_APP_INVENTORY_FILE||(appHostnameState(hostAlias).ready&&appHostnameState(hostAlias).available))){
    trackAppConnection(hostAlias,res);
    return EXTERNAL_PROXY.proxyHTTP(req,res,externalProxyOptions(req,externalTarget)).catch(error=>{if(!res.headersSent){res.writeHead(error.status||502);res.end('External application unavailable.');}else res.destroy();});
  }
  if(hostAlias && (!customAppPort(hostAlias,sessionUser,internetMode) || (process.env.DSH_APP_INVENTORY_FILE && (!appHostnameState(hostAlias).ready||!appHostnameState(hostAlias).available)))) {if(offerGatedAliasSignIn(req,res,hostAlias))return;res.writeHead(404);return res.end('Application hostname unavailable for this account and environment.');}
  const appTarget = parseAppTarget(incomingHost, req.url, sessionUser, internetMode);
  if(hostAlias && appTarget.port===8888) {res.writeHead(302,{Location:'https://'+process.env.DSH_TRUSTED_HOST+'/proxy/8888'+(req.url==='/'?'/lab':req.url)});return res.end();}
  const namedPath=parsedUrl.pathname.match(/^\/proxy\/([a-z0-9][a-z0-9-]{2,62})(?:\/|$)/);
  if(namedPath && Object.hasOwn(appLinks(),namedPath[1]) && !customAppPort(namedPath[1],sessionUser,internetMode)) {res.writeHead(404);return res.end('Application URL unavailable for this account and environment.');}
  if(appTarget.port===8888 && namedPath && customAppPort(namedPath[1],sessionUser,internetMode)) {res.writeHead(302,{Location:'/proxy/8888'+appTarget.targetPath});return res.end();}
  if (appTarget && appTarget.port) {
    if(jupyterContext && appTarget.port===8888 && req.method==='GET' && /^\/(?:lab(?:[/?#]|$)|(?:[?#]|$))/.test(appTarget.targetPath)) {
      return JUPYTER_DEMAND.navigation(req,res,jupyterContext,'/proxy/8888'+appTarget.targetPath).then(handled=>{
        if(!handled&&!res.destroyed)forwardToLocalApp(8888,appTarget.targetPath,req,res,environmentTarget.host);
      }).catch(()=>{if(!res.destroyed&&!res.headersSent){res.writeHead(503,{'Content-Type':'text/plain','Cache-Control':'no-store'});res.end('Jupyter is unavailable. Reopen Jupyter to try again.');}});
    }
    trackAppConnection(hostAlias||namedPath?.[1],res);
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
        const body = injectLogoutControl(Buffer.concat(chunks).toString('utf8'), ADMIN_USERS.has(sessionUser), sessionUser, internetMode);
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
// An upgraded browser/app connection can reset at any time. Handle its socket
// error locally so one disconnected peer cannot terminate every user's gateway.
// Server/listener and application exceptions retain their normal error paths.
server.on('connection', socket => {
  socket.on('error', () => socket.destroy());
});

function rejectUpgrade(socket,status,code) {
  const body=JSON.stringify({error:code});
  const reason={401:'Unauthorized',403:'Forbidden',404:'Not Found',503:'Service Unavailable'}[status];
  socket.end(`HTTP/1.1 ${status} ${reason}\r\nConnection: close\r\nCache-Control: no-store\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(body)}\r\n${status===401?'X-DSH-Auth-Required: 1\r\n':''}\r\n${body}`);
}

server.on('upgrade', (req, socket, head) => {
  try{if(handlePublicAlias(req,null,socket,head))return;}catch{return rejectUpgrade(socket,503,'APP_POLICY_UNAVAILABLE');}
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
    rejectUpgrade(socket,401,'AUTHENTICATION_REQUIRED');
    return;
  }

  const sharedAlias=appHostName(req.headers['x-forwarded-host']||req.headers.host);
  const shared=sharedAlias&&sharedExternalApp(sharedAlias,activeSession.user);
  if(req.headers.origin){
    let allowed=false;
    try{
      const origin=new URL(req.headers.origin),host=origin.host.toLowerCase();
      const canonical=(process.env.DSH_TRUSTED_HOST||req.headers.host||'').toLowerCase();
      const incoming=(req.headers['x-forwarded-host']||req.headers.host||'').toLowerCase();
      const alias=appHostName(incoming);
      allowed=['http:','https:'].includes(origin.protocol) && !origin.username && !origin.password &&
        (host===canonical || (host===incoming && alias && (shared||customAppAvailable(alias,activeSession.user,normalizeInternetMode(activeSession.internet)))));
    }catch{}
    if(!allowed)return rejectUpgrade(socket,403,'ORIGIN_DENIED');
  }

  const expiryTimer=setTimeout(()=>socket.destroy(),Math.max(1,activeSession.created+SESSION_TTL_MS-Date.now()));
  expiryTimer.unref();
  socket.once('close',()=>clearTimeout(expiryTimer));

  const userSockets=USER_SOCKETS.get(activeSession.user)||new Set();
  USER_SOCKETS.set(activeSession.user,userSockets);userSockets.add(socket);
  socket.once('close',()=>{userSockets.delete(socket);if(!userSockets.size && USER_SOCKETS.get(activeSession.user)===userSockets)USER_SOCKETS.delete(activeSession.user);});
  const sessionSockets=SESSION_SOCKETS.get(activeSession)||new Set();
  SESSION_SOCKETS.set(activeSession,sessionSockets);sessionSockets.add(socket);
  socket.once('close',()=>sessionSockets.delete(socket));

  if(shared){
    if(!auditEvent('application.websocket',activeSession.user,shared.app.internet,undefined,{name:sharedAlias,outcome:'requested'}))return rejectUpgrade(socket,503,'AUDIT_UNAVAILABLE');
    trackAppConnection(sharedAlias,socket);
    monitorSharedApp(sharedAlias,activeSession,shared.app.stamp,socket);
    if(shared.port){
      try{return LOCAL_SHARED_PROXY.proxyWebSocket(req,socket,head,localSharedOptions(req,shared,activeSession));}
      catch{return rejectUpgrade(socket,403,'SHARED_APPLICATION_REFUSED');}
    }
    return EXTERNAL_PROXY.proxyWebSocket(req,socket,head,externalProxyOptions(req,shared.target,()=>sharedAppStillAuthorized(sharedAlias,activeSession,shared.app.stamp))).catch(()=>socket.destroy());
  }

  const internetMode = normalizeInternetMode(activeSession && activeSession.internet);
  const environmentTarget = getEnvironmentTarget(internetMode, activeSession.user);
  if (!environmentTarget) return rejectUpgrade(socket,403,'ENVIRONMENT_UNAVAILABLE');
  bindAuthenticatedProxyIdentity(req, activeSession.user, internetMode);
  if(SESSION_DEMAND){
    SESSION_DEMAND.touch(environmentTarget);
    if(RUNTIME_WAITING.includes(SESSION_DEMAND.state(environmentTarget).state))return rejectUpgrade(socket,503,'RUNTIME_STARTING');
    SESSION_DEMAND.watch(socket,environmentTarget);
  }

  // Dynamic App Gateway for WebSockets (e.g. Streamlit, Vite HMR, Next.js); only reachable after login
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const hostAlias=appHostName(incomingHost);
  const externalTarget=hostAlias&&externalAppTarget(hostAlias,activeSession.user,internetMode);
  if(hostAlias&&gatedAliasRecoveryContext(hostAlias)&&!customAppAvailable(hostAlias,activeSession.user,internetMode))return rejectUpgrade(socket,403,'APP_ACCESS_REQUIRED');
  if(externalTarget&&(!process.env.DSH_APP_INVENTORY_FILE||(appHostnameState(hostAlias).ready&&appHostnameState(hostAlias).available))){
    if(!auditEvent('application.websocket',activeSession.user,internetMode))return rejectUpgrade(socket,503,'AUDIT_UNAVAILABLE');
    trackAppConnection(hostAlias,socket);
    return EXTERNAL_PROXY.proxyWebSocket(req,socket,head,externalProxyOptions(req,externalTarget)).catch(()=>socket.destroy());
  }
  const aliasPath=url.parse(req.url).pathname.match(/^\/proxy\/([a-z0-9][a-z0-9-]{2,62})(?:\/|$)/);
  if((hostAlias && (!customAppPort(hostAlias,activeSession.user,internetMode)||(process.env.DSH_APP_INVENTORY_FILE&&(!appHostnameState(hostAlias).ready||!appHostnameState(hostAlias).available)))) || (aliasPath && Object.hasOwn(appLinks(),aliasPath[1]) && !customAppPort(aliasPath[1],activeSession.user,internetMode)))return rejectUpgrade(socket,404,'APP_NOT_FOUND');
  const appTarget = parseAppTarget(incomingHost, req.url, activeSession.user, internetMode);
  if (appTarget && appTarget.port) {
    if (!auditEvent(appTarget.port === 7681 ? 'terminal.open' : 'application.websocket', activeSession.user, internetMode)) return rejectUpgrade(socket,503,'AUDIT_UNAVAILABLE');
    trackAppConnection(hostAlias||aliasPath?.[1],socket);
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

    socket.once('close',()=>targetSocket.destroy());
    targetSocket.on('error', () => {
      socket.destroy();
    });
  });
});

if (USER_CREDENTIALS) USER_CREDENTIALS.startTools(authorization=>{
  const token=typeof authorization==='string'&&authorization.startsWith('Bearer ')?authorization.slice(7):'';
  if(token.length<16||token.length>4096)return null;
  const matches=[];
  for(const [owner,targets] of Object.entries(allUserTargets())) {
    if(!accountEnabled(owner))continue;
    for(const [name,target]of Object.entries(targets)) {
      const environment=name==='internet'?'on':'off';if(environment==='on'&&!internetAllowed(owner))continue;
      let expected;try{expected=getDshToken(target.tokenFile);}catch{continue;}
      if(require('./credential_broker').equal(token,expected))matches.push({owner,environment});
    }
  }
  if(matches.length!==1)return null;
  const identity=matches[0];identity.auditOwner=identity.owner;
  identity.owner=require('./credential_identity').subjectFor(identity.owner,{load:loadUsers,save:saveUsers,audit:()=>auditEvent('credential.identity',identity.auditOwner,identity.environment)});
  return identity;
},auditEvent);

server.listen(PROXY_PORT, process.env.DSH_LISTEN_HOST || '0.0.0.0', () => {
  console.log(`[AUTH-PROXY] Enterprise DSH Auth Gate running on port ${PROXY_PORT}; secure=${ENVIRONMENT_TARGETS.off.host}:${ENVIRONMENT_TARGETS.off.port}; internet=${ENVIRONMENT_TARGETS.on.host}:${ENVIRONMENT_TARGETS.on.port}`);
});
