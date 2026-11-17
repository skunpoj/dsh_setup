'use strict';
// Runs outside execution workers. Secret values terminate here, never in tool responses.
const fs=require('node:fs'),http=require('node:http'),https=require('node:https'),crypto=require('node:crypto'),dns=require('node:dns'),net=require('node:net');
const validName=x=>typeof x==='string'&&/^[a-zA-Z0-9_.-]{1,64}$/.test(x)&&!['__proto__','constructor','prototype'].includes(x);
function fail(status=403){const e=Error('Credential operation unavailable or denied');e.status=status;throw e;}
function equal(a,b){if(typeof a!=='string'||typeof b!=='string')return false;const x=Buffer.from(a),y=Buffer.from(b);return x.length===y.length&&crypto.timingSafeEqual(x,y);}
function readBody(req,limit=16384){return new Promise((resolve,reject)=>{const chunks=[];let n=0;req.on('data',b=>{n+=b.length;if(n>limit){reject(Object.assign(Error('Request too large'),{status:413}));req.resume();}else chunks.push(b);});req.on('end',()=>{try{resolve(JSON.parse(Buffer.concat(chunks).toString()));}catch{reject(Object.assign(Error('Invalid request'),{status:400}));}});req.on('error',reject);});}
function json(res,status,value){res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(JSON.stringify(value));}
function httpJson(url,{method='GET',body,headers={},ca,lookup,limit=32768,timeoutMs=15000}={}){
  return new Promise((resolve,reject)=>{const data=body===undefined?undefined:Buffer.from(JSON.stringify(body));
    const r=https.request(url,{method,ca,lookup,agent:false,headers:{...headers,...(data?{'Content-Type':'application/json','Content-Length':data.length}:{})}},s=>{
      const parts=[];let n=0;s.on('data',b=>{n+=b.length;if(n>limit)s.destroy(Error('Bounded response exceeded'));else parts.push(b);});s.on('error',reject);
      s.on('end',()=>{let result;try{result=JSON.parse(Buffer.concat(parts).toString());}catch{result=null;}resolve({status:s.statusCode,data:result});});});
    // Socket inactivity timeouts do not bound DNS/connect stalls. Use a wall-clock deadline.
    const deadline=setTimeout(()=>r.destroy(Error('Bounded request timeout')),timeoutMs);r.once('close',()=>clearTimeout(deadline));
    r.setTimeout(timeoutMs,()=>r.destroy(Error('Bounded request timeout')));r.on('error',()=>reject(Object.assign(Error('Service unavailable'),{status:503})));r.end(data);
  });
}
class Vault {
  constructor({url,tokenFile,caFile,mount}){this.url=url;this.tokenFile=tokenFile;this.ca=fs.readFileSync(caFile);this.mount=mount;if(!/^dsh-(off|on)$/.test(mount))throw Error('Invalid vault mount');}
  async call(path,method,body){const result=await httpJson(new URL('/v1/'+path,this.url),{method,body,ca:this.ca,limit:524288,headers:{'X-Vault-Token':fs.readFileSync(this.tokenFile,'utf8').trim()}});return result;}
  async read(owner){const p=crypto.createHash('sha256').update(owner).digest('hex');const r=await this.call(this.mount+'/data/'+p);if(r.status===404)return {items:{},version:0};if(r.status!==200)fail(503);return {...r.data.data.data,version:r.data.data.metadata.version};}
  async write(owner,record){const p=crypto.createHash('sha256').update(owner).digest('hex');const r=await this.call(this.mount+'/data/'+p,'POST',{options:{cas:record.version},data:{items:record.items}});if(r.status!==200)fail(503);}
  async renew(){const r=await this.call('auth/token/renew-self','POST',{});if(r.status!==200)fail(503);}
}
function publicRecord(id,c){return {id,profile:c.profile,workspace:c.workspace,operations:c.operations,scopes:c.scopes||{},expiresAt:c.expiresAt,disabled:!!c.disabled,updatedAt:c.updatedAt,lastUsedAt:c.lastUsedAt||null};}
function envelopeAAD(owner,environment,input){return Buffer.from(JSON.stringify([owner,environment,input.id,input.profile,input.workspace,input.expiresAt,[...(input.operations||[])].sort(),Object.keys(input.scopes||{}).sort().map(k=>[k,input.scopes[k]])]));}
function decryptEnvelope(key,owner,environment,input){
 try{const e=input.secretEnvelope;if(!e||typeof e!=='object')fail(400);const wrapped=Buffer.from(e.key,'base64'),iv=Buffer.from(e.iv,'base64'),body=Buffer.from(e.body,'base64');if(iv.length!==12||body.length<17||body.length>8192||wrapped.length>512)fail(400);
 const aes=crypto.privateDecrypt({key,oaepHash:'sha256',padding:crypto.constants.RSA_PKCS1_OAEP_PADDING},wrapped);if(aes.length!==32)fail(400);
 const d=crypto.createDecipheriv('aes-256-gcm',aes,iv);d.setAAD(envelopeAAD(owner,environment,input));d.setAuthTag(body.subarray(-16));return Buffer.concat([d.update(body.subarray(0,-16)),d.final()]).toString('utf8');}catch{fail(400);}
}
function destinationAllowed(address,profile){
  if(!net.isIPv4(address))return false;
  if(profile.allowedAddresses?.length)return profile.allowedAddresses.includes(address);
  if(profile.network!=='public')return false;
  const blocked=new net.BlockList();for(const [ip,prefix] of [['0.0.0.0',8],['10.0.0.0',8],['100.64.0.0',10],['127.0.0.0',8],['169.254.0.0',16],['172.16.0.0',12],['192.168.0.0',16],['192.0.0.0',24],['192.0.2.0',24],['198.18.0.0',15],['198.51.100.0',24],['203.0.113.0',24],['224.0.0.0',3]])blocked.addSubnet(ip,prefix,'ipv4');return !blocked.check(address,'ipv4');
}
// ---- SMP EDA session profile (auth 'eda-session') ---------------------------------------------------------------------------------
// The EDA has a form login and a session cookie over plain http INSIDE the cluster, which the https-only connector cannot do. The broker logs in itself,
// calls one fixed path and returns a bounded result: the agent only ever names an alias and a question. A pinned private address, no redirects, no DNS.
const EDA_USER=/^[A-Za-z0-9_.@-]{1,64}$/,EDA_COOKIE='smp_eda_session_token';
function splitEdaSecret(secret){const i=typeof secret==='string'?secret.indexOf(':'):-1;if(i<1)return null;const user=secret.slice(0,i),password=secret.slice(i+1);
 return EDA_USER.test(user)&&password.length>=8&&password.length<=4096&&!/[\r\n\0]/.test(password)?{user,password}:null;}
function privateAddress(address){if(!net.isIPv4(address))return false;const allowed=new net.BlockList();for(const [ip,prefix] of [['10.0.0.0',8],['100.64.0.0',10],['172.16.0.0',12],['192.168.0.0',16]])allowed.addSubnet(ip,prefix,'ipv4');return allowed.check(address,'ipv4');}
// ---- Per-profile owner allow-list ------------------------------------------------------------------------------------------------
// 'allowedOwners' lists the account ids (credentialSubject, u-<32 hex>) that may see, save, approve and use a profile. An EDA profile WITHOUT a list is closed to
// everyone (deny all until an administrator names accounts); any other profile stays open unless it carries a list, and an empty list means nobody.
function ownerAllowed(profile,owner){if(Array.isArray(profile.allowedOwners))return profile.allowedOwners.includes(owner);return profile.auth!=='eda-session';}
function validateOwnerLists(profiles){for(const [id,p] of Object.entries(profiles)){if(p.allowedOwners===undefined)continue;
  if(!Array.isArray(p.allowedOwners)||p.allowedOwners.length>200||p.allowedOwners.some(x=>!validName(x)))throw Error('Invalid allowedOwners for profile '+id);}}
function httpPlain({address,port,hostHeader,method,path,headers={},body,timeoutMs=60000,limit=1048576}){
 return new Promise((resolve,reject)=>{const data=body===undefined?null:Buffer.from(body);
  const r=http.request({host:address,port,path,method,agent:false,headers:{Host:hostHeader,'User-Agent':'DSH-Credential-Broker/1',...headers,...(data?{'Content-Length':data.length}:{})}},s=>{
   const chunks=[];let n=0;s.on('data',b=>{n+=b.length;if(n>limit){s.destroy();reject(new Error('Response too large'));return;}chunks.push(b);});
   s.on('end',()=>resolve({status:s.statusCode,headers:s.headers,body:Buffer.concat(chunks)}));s.on('error',reject);});   // redirects are never followed
  const deadline=setTimeout(()=>r.destroy(new Error('Timeout')),timeoutMs);r.once('close',()=>clearTimeout(deadline));   // wall clock: a server that drips bytes cannot stretch it
  r.setTimeout(timeoutMs,()=>r.destroy(new Error('Timeout')));r.on('error',reject);r.end(data);});
}
class Broker {
  constructor({vault,environment,profiles,audit,dispatch,now=Date.now,encryptionKey,addressCheck=privateAddress}){validateOwnerLists(profiles||{});this.addressCheck=addressCheck;this.vault=vault;this.environment=environment;this.profiles=profiles;this.encryptionKey=encryptionKey;this.audit=audit;this.dispatch=dispatch||this.connect.bind(this);this.now=now;this.pending=new Map();this.locks=new Map();this.queued=new Map();this.inflight=0;this.usage=new Map();}
  async lock(owner,fn){if((this.queued.get(owner)||0)>=4||this.inflight>=64)fail(429);this.queued.set(owner,(this.queued.get(owner)||0)+1);this.inflight++;const previous=this.locks.get(owner)||Promise.resolve();let release;const next=new Promise(r=>release=r);this.locks.set(owner,next);await previous;try{return await fn();}finally{release();this.inflight--;const count=this.queued.get(owner)-1;if(count)this.queued.set(owner,count);else this.queued.delete(owner);if(this.locks.get(owner)===next)this.locks.delete(owner);}}
  log(owner,action,id,outcome){if(this.audit({time:new Date(this.now()).toISOString(),owner,environment:this.environment,action,credentialRef:id?crypto.createHash('sha256').update(id).digest('hex').slice(0,16):null,outcome})!==true)fail(503);}
  profile(id,owner){const p=Object.hasOwn(this.profiles,id)&&this.profiles[id];if(!p||!p.environments.includes(this.environment))fail();
    if(owner!==undefined&&!ownerAllowed(p,owner)){this.log(owner,'profile-denied',null,'owner-not-allowed');fail();}return p;}   // the same generic denial as an unknown profile
  record(data,id,workspace){const c=Object.hasOwn(data.items,id)&&data.items[id];if(!c||c.disabled||c.expiresAt<=this.now()||c.workspace!==workspace)fail();return c;}
  prune(){for(const [id,p] of this.pending)if(p.expiresAt<=this.now())this.pending.delete(id);}
  async handle(owner,action,input={}){
    if(!validName(owner)||!['off','on'].includes(this.environment))fail();this.prune();
    for(const [key,value]of this.usage)if(value.start+60000<=this.now())this.usage.delete(key);
    const usage=this.usage.get(owner)||{start:this.now(),all:0,execute:0};usage.all++;if(action==='execute')usage.execute++;this.usage.set(owner,usage);if(usage.all>120||usage.execute>20)fail(429);
    return this.lock(owner,async()=>{
      if(action==='encryption-key'){if(!this.encryptionKey)fail(503);return {owner,environment:this.environment,publicKey:crypto.createPublicKey(this.encryptionKey).export({type:'spki',format:'pem'})};}
      if(action==='profiles')return Object.entries(this.profiles).filter(([,p])=>p.environments.includes(this.environment)&&ownerAllowed(p,owner)).map(([id,p])=>({id,label:p.label,scopeParameters:p.scopeParameters||{},operations:Object.entries(p.operations).map(([id,o])=>({id,requiresApproval:o.method!=='GET'||!!o.requiresApproval,parameters:Object.keys(o.parameters||{})}))}));
      const data=await this.vault.read(owner);
      if(action==='list'){this.log(owner,'list',null,'allowed');return {credentials:Object.entries(data.items).map(([id,c])=>publicRecord(id,c)),pending:[...this.pending].filter(([,p])=>p.owner===owner).map(([id,p])=>({id,credentialId:p.id,operation:p.operation,workspace:p.workspace,parameters:p.parameters,state:p.state,expiresAt:p.expiresAt}))};}
      if(!validName(input.id))fail(400);
      if(action==='save'){
        // Production requires browser encryption; gateway/ingress never receive the raw provider key.
        if(this.encryptionKey){if(Object.hasOwn(input,'secret'))fail(400);input={...input,secret:decryptEnvelope(this.encryptionKey,owner,this.environment,input)};}
        const p=this.profile(input.profile,owner);if(!validName(input.workspace)||typeof input.secret!=='string'||input.secret.length<8||input.secret.length>4096||/[\r\n\0]/.test(input.secret)||!Number.isFinite(input.expiresAt)||input.expiresAt<=this.now()||input.expiresAt>this.now()+90*86400000)fail(400);
        if(!Array.isArray(input.operations)||!input.operations.length||input.operations.some(op=>!Object.hasOwn(p.operations,op)))fail(400);
        if(p.auth==='eda-session'&&!splitEdaSecret(input.secret))fail(400);   // the EDA login is saved as username:password
        const scopes=input.scopes||{};if(!scopes||typeof scopes!=='object'||Array.isArray(scopes)||Object.keys(scopes).some(k=>!Object.hasOwn(p.scopeParameters||{},k)))fail(400);
        for(const [key,rule]of Object.entries(p.scopeParameters||{}))if(typeof scopes[key]!=='string'||scopes[key].length>128||!(new RegExp('^(?:'+rule+')$')).test(scopes[key]))fail(400);
        if(!Object.hasOwn(data.items,input.id)&&Object.keys(data.items).length>=32)fail(429);
        this.log(owner,'save',input.id,'requested');data.items[input.id]={profile:input.profile,workspace:input.workspace,operations:[...new Set(input.operations)],scopes,expiresAt:input.expiresAt,secret:input.secret,disabled:false,updatedAt:this.now()};
        await this.vault.write(owner,data);for(const [key,x]of this.pending)if(x.owner===owner&&x.id===input.id)this.pending.delete(key);return publicRecord(input.id,data.items[input.id]);
      }
      if(['disable','delete'].includes(action)){
        if(!data.items[input.id])fail(404);this.log(owner,action,input.id,'requested');if(action==='delete')delete data.items[input.id];else data.items[input.id].disabled=true;
        await this.vault.write(owner,data);for(const [key,x]of this.pending)if(x.owner===owner&&x.id===input.id)this.pending.delete(key);return {updated:true,providerRevocation:'Not performed; revoke the provider token separately.'};
      }
      if(action==='approve'){
        const p=this.pending.get(input.id);if(!p||p.owner!==owner||p.state!=='pending')fail();this.profile(this.record(data,p.id,p.workspace).profile,owner);
        this.log(owner,'approve',p.id,'approved');p.state='approved';return {approved:true};
      }
      if(action==='result'){
        const p=this.pending.get(input.id);if(!p||p.owner!==owner)fail();return {state:p.state,...(p.state==='complete'?{result:p.result}:{})};
      }
      if(action!=='execute')fail(400);
      const c=this.record(data,input.id,input.workspace),profile=this.profile(c.profile,owner),op=profile.operations[input.operation];
      if(!op||!c.operations.includes(input.operation))fail();
      const params=input.parameters||{};if(!params||typeof params!=='object'||Array.isArray(params)||Object.keys(params).some(k=>!Object.hasOwn(op.parameters||{},k)))fail(400);
      for(const [key,rule]of Object.entries(op.parameters||{}))if(typeof params[key]!=='string'||params[key].length>512||!(new RegExp('^(?:'+rule+')$')).test(params[key]))fail(400);
      for(const [key,value]of Object.entries(c.scopes||{}))if(Object.hasOwn(op.parameters||{},key)&&params[key]!==value)fail();
      const canonical=JSON.stringify([input.id,input.workspace,input.operation,Object.keys(params).sort().map(k=>[k,params[k]])]);const digest=crypto.createHash('sha256').update(canonical).digest('hex');
      let approval=null;   // held by reference: the pending map is pruned by every request and a slow upstream call can outlive the original two minutes
      if(op.method!=='GET'||op.requiresApproval||profile.auth==='eda-session'){   // an EDA use ALWAYS waits for the person, whatever the profile file says
        const prior=input.approvalId&&this.pending.get(input.approvalId);
        if(!prior){if(input.approvalId)fail();if([...this.pending.values()].filter(p=>p.owner===owner).length>=16)fail(429);const id=crypto.randomBytes(16).toString('hex');this.pending.set(id,{owner,id:input.id,workspace:input.workspace,operation:input.operation,parameters:params,digest,state:'pending',expiresAt:this.now()+120000});this.log(owner,'request-approval',input.id,'pending');return {approvalRequired:true,approvalId:id};}
        if(prior.owner!==owner||prior.digest!==digest||prior.state!=='approved')fail();prior.state='dispatched';approval=prior;approval.expiresAt=this.now()+300000; // consumed before any network await; the answer stays fetchable with 'result' for five minutes
      }
      this.log(owner,'execute',input.id,'requested');
      try{const result=await this.dispatch(profile,op,params,c.secret);c.lastUsedAt=this.now();await this.vault.write(owner,data);this.log(owner,'execute',input.id,'complete');if(approval){approval.state='complete';approval.result=result;}return {result};}
      catch{if(approval)approval.state='uncertain';this.log(owner,'execute',input.id,'uncertain');fail(502);}
    });
  }
  async connectEdaSession(profile,op,params,secret){
    const login=splitEdaSecret(secret);
    if(!login||profile.cleartextInCluster!==true||profile.network!==undefined&&profile.network!=='cluster'||typeof profile.address!=='string'||!profile.allowedAddresses?.includes(profile.address)||!this.addressCheck(profile.address)
      ||!Number.isInteger(profile.port)||profile.port<1||profile.port>65535||!/^[a-z0-9][a-z0-9.-]{2,252}$/.test(profile.hostHeader||'')||!['GET','POST'].includes(op.method)||!/^\/api\/[a-z0-9\/_-]{1,64}$/.test(op.path||''))fail();
    // ONE wall-clock budget for login plus the call (at most 60 s): the gateway waits 75 s for the whole answer, so three separate 60 s timeouts could never finish.
    const total=Math.min(Math.max(Number(profile.timeoutMs)||60000,1000),60000),started=Date.now();
    const call=(method,path,headers,body)=>{const left=total-(Date.now()-started);if(left<=0)fail(502);return httpPlain({address:profile.address,port:profile.port,hostHeader:profile.hostHeader,method,path,headers,body,timeoutMs:left});};
    if((await call('GET','/login',{})).status!==200)fail(502);
    const signed=await call('POST','/login',{'Content-Type':'application/x-www-form-urlencoded'},new URLSearchParams({username:login.user,password:login.password}).toString());
    if(signed.status!==303)fail(502);
    let cookie=null;for(const line of [].concat(signed.headers['set-cookie']||[])){const m=/^smp_eda_session_token=([^;\s]+)/.exec(line);if(m)cookie=m[1];}
    if(!cookie)fail(502);
    const headers={Cookie:EDA_COOKIE+'='+cookie,Accept:'application/json'};
    const body=op.method==='GET'?undefined:JSON.stringify(Object.fromEntries((op.bodyParameters||[]).map(k=>[k,params[k]])));
    const r=await call(op.method,op.path,op.method==='GET'?headers:{...headers,'Content-Type':'application/json'},body);
    if(r.status!==200)fail(502);
    let data;try{data=JSON.parse(r.body.toString('utf8'));}catch{fail(502);}
    if(!data||typeof data!=='object'||Array.isArray(data)||!Array.isArray(op.responseFields))fail(502);
    const result={};for(const name of op.responseFields)if(Object.hasOwn(data,name))result[name]=data[name];
    if(typeof result.sql==='string'&&result.sql.length>(op.maxSqlChars||600))result.sql=result.sql.slice(0,op.maxSqlChars||600)+' ...';
    const limit=Math.min(op.maxResultBytes||49152,49152),sizeOf=v=>Buffer.byteLength(JSON.stringify(v));
    if(Array.isArray(result.rows)){const maxRows=op.maxRows||500;if(result.rows.length>maxRows){result.rows=result.rows.slice(0,maxRows);result.rowsTruncated=true;}
      while(result.rows.length&&sizeOf(result)>limit){result.rows=result.rows.slice(0,Math.floor(result.rows.length/2));result.rowsTruncated=true;}}
    // Redact inside every string (keys too) BEFORE serialising: JSON escaping would otherwise hide a password that contains a quote, backslash or non-ASCII character.
    const secrets=[login.password,encodeURIComponent(login.password),Buffer.from(login.password).toString('base64'),secret,cookie];
    const scrub=v=>{if(typeof v==='string'){let o=v;for(const x of secrets)o=o.split(x).join('[REDACTED]');return o;}
      if(Array.isArray(v))return v.map(scrub);if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[scrub(k),scrub(x)]));return v;};
    const output=JSON.stringify(scrub(result));
    // Fail closed if any secret is still present, raw or JSON-escaped (for example a numeric password echoed as a number).
    for(const x of secrets)for(const form of [x,JSON.stringify(x).slice(1,-1)])if(output.includes(form))fail(502);
    if(Buffer.byteLength(output)>limit)fail(502);return JSON.parse(output);
  }
  async connect(profile,op,params,secret){
    if(profile.auth==='eda-session')return this.connectEdaSession(profile,op,params,secret);
    const base=new URL(profile.baseUrl);if(base.protocol!=='https:'||base.username||base.password||base.hash||base.search||!['GET','POST','PUT','DELETE'].includes(op.method))fail();
    const literal=base.hostname.replace(/^\[|\]$/g,'');if(net.isIP(literal)&&!destinationAllowed(literal,profile))fail();
    let route=op.path.replace(/\{([a-zA-Z0-9_]+)\}/g,(_,k)=>encodeURIComponent(params[k]));if(!route.startsWith('/')||route.startsWith('//')||route.includes('..'))fail();
    const url=new URL(route,base);if(url.origin!==base.origin)fail();
    const lookup=(host,options,done)=>{dns.resolve4(host,(error,addresses)=>{const ip=addresses?.find(x=>destinationAllowed(x,profile));if(error||!ip)return done(Error('Destination denied'));done(null,options?.all?[{address:ip,family:4}]:ip,4);});};
    const headers={'User-Agent':'DSH-Credential-Broker/1','Accept':'application/json',Authorization:profile.auth==='basic-pat'?'Basic '+Buffer.from(':'+secret).toString('base64'):'Bearer '+secret};
    const ca=profile.caFile?fs.readFileSync(profile.caFile):undefined;
    const r=await httpJson(url,{method:op.method,headers,ca,lookup,...(op.method==='GET'?{}:{body:Object.fromEntries((op.bodyParameters||[]).map(k=>[k,params[k]]))})});
    if(r.status<200||r.status>=300||!r.data||!Array.isArray(op.responseFields))fail(502);
    const result={};for(const name of op.responseFields)if(Object.hasOwn(r.data,name))result[name]=r.data[name];
    let output=JSON.stringify(result);for(const value of [secret,encodeURIComponent(secret),Buffer.from(secret).toString('base64'),Buffer.from(':'+secret).toString('base64')])output=output.split(value).join('[REDACTED]');
    output=output.replace(/(?:Bearer\s+|Basic\s+)[a-zA-Z0-9+/=._-]{8,}/gi,'[REDACTED]').replace(/(?:gh[pousr]_|github_pat_|sk-)[a-zA-Z0-9_-]{12,}/g,'[REDACTED]');
    if(Buffer.byteLength(output)>8192)fail(502);return JSON.parse(output);
  }
}
function start(){
 const config=JSON.parse(fs.readFileSync(process.env.DSH_CREDENTIAL_BROKER_CONFIG,'utf8'));
 const vault=new Vault(config.vault);const auditFile=config.auditFile;
 const broker=new Broker({vault,environment:config.environment,profiles:config.profiles,encryptionKey:fs.readFileSync(config.encryptionKeyFile),audit:event=>{try{if(fs.existsSync(auditFile)&&fs.statSync(auditFile).size>=2*1024*1024){for(let i=4;i>=1;i--){const old=i===1?auditFile:auditFile+'.'+(i-1);if(fs.existsSync(old))fs.renameSync(old,auditFile+'.'+i);}}const fd=fs.openSync(auditFile,'a',0o600);try{fs.writeSync(fd,JSON.stringify(event)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}return true;}catch{return false;}}});
 const server=https.createServer({key:fs.readFileSync(config.tls.keyFile),cert:fs.readFileSync(config.tls.certFile)},async(req,res)=>{
  if(req.url==='/health'&&req.method==='GET')return json(res,200,{service:'credential-broker',environment:config.environment});
  if(req.url!=='/v1/rpc'||req.method!=='POST'||!equal(req.headers.authorization,'Bearer '+fs.readFileSync(config.gatewayKeyFile,'utf8').trim()))return json(res,403,{error:'Denied'});
  try{const body=await readBody(req);return json(res,200,{data:await broker.handle(body.owner,body.action,body.input)});}catch(e){return json(res,e.status||503,{error:'Credential operation unavailable or denied'});}
 });server.listen(config.port||8443,'0.0.0.0');
 setInterval(()=>vault.renew().catch(()=>{}),3600000).unref();
}
if(require.main===module)start();
module.exports={Broker,Vault,destinationAllowed,httpJson,readBody,json,equal,envelopeAAD,decryptEnvelope,splitEdaSecret,privateAddress,httpPlain,ownerAllowed,validateOwnerLists};
