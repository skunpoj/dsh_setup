'use strict';
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const {DEFAULT_POLICY,MAX_ACCOUNTS,validatePolicy,readJSON,atomicJSON,projection,Manager}=require('../scripts/capacity_policy');
assert.equal(DEFAULT_POLICY.warmSpareSlots,2);
assert.equal(validatePolicy(DEFAULT_POLICY,9).maxAccounts,MAX_ACCOUNTS,'Accounts are effectively unlimited by default');
const LIMITED={...DEFAULT_POLICY,maxAccounts:16};
for(const value of [{...DEFAULT_POLICY,maxAccounts:8},{...DEFAULT_POLICY,warmSpareSlots:9},{...DEFAULT_POLICY,maxAccounts:MAX_ACCOUNTS+1},{...DEFAULT_POLICY,enabled:'yes'},{...DEFAULT_POLICY,command:'kubectl'}])assert.throws(()=>validatePolicy(value,9));
const users={alice:{runtimeSlot:'private-1',password:'do-not-project'},bob:{runtimeSlot:'private-2',disabled:true}};
const p=projection(users);assert.equal(p.registeredAccounts,2);assert.deepEqual(p.assignedSlots,['private-1','private-2']);assert(!JSON.stringify(p).includes('password'));
const root=fs.mkdtempSync(path.join(os.tmpdir(),'capacity-policy-'));
try{
 const file=path.join(root,'policy.json');atomicJSON(file,DEFAULT_POLICY);assert.deepEqual(readJSON(file),DEFAULT_POLICY);
 const capacity=path.join(root,'capacity');fs.mkdirSync(path.join(capacity,'policy'),{recursive:true});
 const policyFile=path.join(capacity,'policy','policy.json');atomicJSON(policyFile,LIMITED);
 const manager=new Manager(capacity,{slots:{}}),originalPolicy=fs.readFileSync(policyFile);
 for(const count of [15,16,17]){
  const retained=Object.fromEntries(Array.from({length:count},(_,i)=>['user'+i,{disabled:i===16}]));
  assert.equal(manager.policy(retained).maxAccounts,16,'Valid reads survive a full or over-limit retained account store');
  assert.equal(manager.summary(retained).policy.maxAccounts,16);
  if(count>16)assert.throws(()=>manager.save(LIMITED,retained),'Admin writes retain the existing-account floor');
  assert.deepEqual(fs.readFileSync(policyFile),originalPolicy,'Reading or refusing policy changes must not alter the limit');
 }
 atomicJSON(policyFile,{...LIMITED,maxAccounts:0});assert.throws(()=>manager.policy({}),'Malformed persisted policies still fail closed');
 atomicJSON(policyFile,LIMITED);fs.mkdirSync(path.join(capacity,'inventory'),{recursive:true});
 const retained={alice:{},bob:{}},snapshot={observedAt:new Date().toISOString(),available:true,capacity:{version:1,mainRegistered:2,additionalDeploymentsComplete:true,additionalAccounts:2,mainPlanningCeiling:18,resources:['cpu','memoryGiB','pods','storageGiB'].map(resource=>({resource,available:10,reserve:2,pairBudget:1,afterReserve:8,additionalPairs:8}))}};
 // An account reserves no compute, so raising the limit needs no capacity report.
 assert.equal(manager.save({...LIMITED,maxAccounts:17},retained).maxAccounts,17,'Absent capacity no longer blocks an increase');
 atomicJSON(path.join(capacity,'inventory','status.json'),snapshot);
 assert.equal(manager.summary(retained).controller.capacity.totalRegistered,4);
 assert.equal(manager.save({...LIMITED,maxAccounts:19},retained).maxAccounts,19,'A compute ceiling no longer caps accounts');
 snapshot.observedAt=new Date(Date.now()-120000).toISOString();atomicJSON(path.join(capacity,'inventory','status.json'),snapshot);
 assert.equal(manager.save({...LIMITED,maxAccounts:18},retained).maxAccounts,18,'Stale capacity no longer blocks an increase');
 assert.equal(manager.save(LIMITED,retained).maxAccounts,16,'A stale sample cannot block a preserving decrease');
 atomicJSON(file,{...DEFAULT_POLICY,enabled:false});assert.equal(readJSON(file).enabled,false);
 fs.writeFileSync(file,'x'.repeat(33));assert.throws(()=>readJSON(file,32));
 assert.throws(()=>readJSON(root));
 if(process.platform!=='win32'){
  const symlink=path.join(root,'link');fs.symlinkSync(file,symlink);assert.throws(()=>readJSON(symlink));
  require('child_process').execFileSync('mkfifo',[path.join(root,'fifo')]);const start=Date.now();assert.throws(()=>readJSON(path.join(root,'fifo')));assert(Date.now()-start<1000);
 }
}finally{fs.rmSync(root,{recursive:true,force:true});}
console.log('Capacity policy: bounded settings, private projection and safe persisted reads passed');
