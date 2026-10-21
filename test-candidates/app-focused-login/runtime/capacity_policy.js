'use strict';
// Gateway owns policy and assignment projections. Only the operator provisioner
// owns inventory and launch tokens. Neither file contains password records.
const fs = require('fs');
const path = require('path');
const MAX_ACCOUNTS = 32;
const DEFAULT_POLICY = Object.freeze({version:1, enabled:true, warmSpareSlots:2, maxAccounts:16});
function validatePolicy(value, registered=0) {
  if (!value || typeof value!=='object' || Array.isArray(value) ||
      Object.keys(value).sort().join(',')!=='enabled,maxAccounts,version,warmSpareSlots' ||
      value.version!==1 || typeof value.enabled!=='boolean' ||
      !Number.isInteger(value.maxAccounts) || value.maxAccounts<Math.max(1,registered) || value.maxAccounts>MAX_ACCOUNTS ||
      !Number.isInteger(value.warmSpareSlots) || value.warmSpareSlots<0 || value.warmSpareSlots>8 ||
      value.warmSpareSlots>value.maxAccounts) throw Error('Invalid capacity policy; preserve existing accounts and use 0–8 spares, maximum 32 accounts.');
  return {...value};
}
function readJSON(file, limit=262144) {
  let fd;
  try {
    fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
    const stat=fs.fstatSync(fd);
    if(!stat.isFile()||stat.size>limit)throw Error('Invalid capacity file');
    const b=Buffer.alloc(limit+1);let n=0,r;
    while(n<=limit && (r=fs.readSync(fd,b,n,b.length-n,null))>0)n+=r;
    if(n>limit)throw Error('Capacity file too large');
    return JSON.parse(b.subarray(0,n).toString('utf8'));
  } finally {if(fd!==undefined)fs.closeSync(fd);}
}
function atomicJSON(file,value) {
  const tmp=path.join(path.dirname(file),'.'+path.basename(file)+'.'+process.pid+'.'+require('crypto').randomBytes(6).toString('hex'));
  let fd;
  try {fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(value));fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,file);}
  finally {if(fd!==undefined)fs.closeSync(fd);try{fs.unlinkSync(tmp);}catch(e){if(e.code!=='ENOENT')throw e;}}
}
function projection(users) {
  return {version:1, observedAt:new Date().toISOString(), registeredAccounts:Object.keys(users).length,
    assignedSlots:[...new Set(Object.values(users).map(u=>u.runtimeSlot).filter(Boolean))].sort()};
}
class Manager {
  constructor(root,initialPool,namespace='llm') {
    if(!path.isAbsolute(root)||!initialPool||!/^[a-z0-9-]{1,63}$/.test(namespace))throw Error('Invalid capacity installation');
    this.root=root;this.initialPool=initialPool;this.namespace=namespace;
  }
  // Existing (including disabled) accounts can outnumber an unchanged limit.
  // Reads must still succeed so admission can report zero; only policy writes
  // enforce the registered-account floor, without deleting or recycling users.
  policy(users) {return validatePolicy(readJSON(path.join(this.root,'policy','policy.json')));}
  pool() {
    const value=readJSON(path.join(this.root,'inventory','pool.json'));
    if(!value||!value.slots||Array.isArray(value.slots)||Object.keys(value.slots).length>32)throw Error('Invalid provisioned inventory');
    for(const [slot,targets]of Object.entries(this.initialPool.slots)){
      if(!require('util').isDeepStrictEqual(value.slots[slot],targets))throw Error('Existing private route changed');
    }
    for(const [slot,targets]of Object.entries(value.slots)) {
      if(Object.hasOwn(this.initialPool.slots,slot))continue;
      if(!/^cap-[a-f0-9]{16}-01$/.test(slot)||Object.keys(targets).sort().join(',')!=='internet,secure')throw Error('Invalid new slot');
      const identity=require('crypto').createHash('sha256').update(slot).digest('hex').slice(0,16);
      for(const env of ['secure','internet']){
        const t=targets[env];
        if(t.host!==`dsh-u-${identity}-${env}.${this.namespace}.svc.cluster.local`||t.port!==3081||
           t.tokenFile!==`/runtime-tokens/capacity/${identity}/${env}/token`)throw Error('Unapproved new runtime destination');
      }
    }
    return value;
  }
  project(users) {atomicJSON(path.join(this.root,'policy','assignments.json'),projection(users));}
  admission(users) {
    try {
      const snapshot=readJSON(path.join(this.root,'inventory','status.json'),65536);
      return require('./signup_admission').signupAdmission(snapshot,Object.keys(users).length);
    } catch { return {allowed:false,reason:'capacity-unavailable'}; }
  }
  save(value,users) {
    const p=validatePolicy(value,Object.keys(users).length),old=this.policy(users);
    if(p.maxAccounts>old.maxAccounts){
      const report=this.summary(users).controller?.capacity;
      if(!report || report.mainRegistered!==Object.keys(users).length || !Number.isSafeInteger(report.mainPlanningCeiling) || p.maxAccounts>report.mainPlanningCeiling)
        throw Error('An increase requires a fresh infrastructure calculation covering all configured DSH deployments. Keep the present limit or refresh capacity.');
    }
    atomicJSON(path.join(this.root,'policy','policy.json'),p);this.project(users);return p;
  }
  summary(users) {
    const policy=this.policy(users);let controller=null;
    try{const s=readJSON(path.join(this.root,'inventory','status.json'),65536);const age=Date.now()-Date.parse(s.observedAt);
      if(Number.isFinite(age)&&age>=-5000&&age<60000){
        controller={observedAt:s.observedAt,available:s.available===true,action:s.action,reason:s.reason,stage:s.stage,readySpares:s.readySpares,desiredSpares:s.desiredSpares};
        const c=s.capacity;
        if(s.available===true && c?.version===1 && c.mainRegistered===Object.keys(users).length &&
           c.additionalDeploymentsComplete===true && Number.isSafeInteger(c.mainPlanningCeiling)&&c.mainPlanningCeiling>=c.mainRegistered&&c.mainPlanningCeiling<=32&&
           Number.isSafeInteger(c.additionalAccounts)&&c.additionalAccounts>=0&&c.additionalAccounts<=8&&
           Array.isArray(c.resources)&&c.resources.length===4 && c.resources.every(r=>['cpu','memoryGiB','pods','storageGiB'].includes(r.resource)&&['available','reserve','pairBudget','afterReserve','additionalPairs'].every(k=>Number.isFinite(r[k])&&r[k]>=0))){
          controller.capacity={mainRegistered:c.mainRegistered,additionalAccounts:c.additionalAccounts,totalRegistered:c.mainRegistered+c.additionalAccounts,
            readyPairs:c.readyPairs,additionalPairsPossible:c.additionalPairsPossible,mainPlanningCeiling:c.mainPlanningCeiling,totalPlanningCeiling:c.mainPlanningCeiling+c.additionalAccounts,
            limitingResources:Array.isArray(c.limitingResources)?c.limitingResources.filter(x=>['cpu','memoryGiB','pods','storageGiB','inventory'].includes(x)):[],
            centralStorageFreeGiB:Number.isFinite(c.centralStorageFreeGiB)?c.centralStorageFreeGiB:null,
            observedUsage:c.observedUsage&&['cpu','memoryGiB','reservedCPU','reservedMemoryGiB'].every(k=>Number.isFinite(c.observedUsage[k])&&c.observedUsage[k]>=0)?Object.fromEntries(['timestamp','cpu','memoryGiB','reservedCPU','reservedMemoryGiB'].map(k=>[k,c.observedUsage[k]])):null,
            additionalDeployments:Array.isArray(c.additionalDeployments)?c.additionalDeployments.slice(0,8).map(x=>({label:String(x.label).slice(0,40),accounts:x.accounts,readyWorkers:x.readyWorkers,desiredWorkers:x.desiredWorkers})):[],
            resources:c.resources.map(r=>Object.fromEntries(['resource','available','reserve','pairBudget','afterReserve','additionalPairs'].map(k=>[k,r[k]])))};
        }
      }
    }catch{}
    return {policy,controller,controllerFresh:controller!==null};
  }
}
module.exports={DEFAULT_POLICY,MAX_ACCOUNTS,validatePolicy,readJSON,atomicJSON,projection,Manager};
