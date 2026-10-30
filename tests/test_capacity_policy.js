'use strict';
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const capacityPolicy=require('../scripts/capacity_policy');
const {DEFAULT_POLICY,validatePolicy,readJSON,atomicJSON,projection,Manager}=capacityPolicy;
assert.equal(DEFAULT_POLICY.warmSpareSlots,2);
assert.equal('MAX_ACCOUNTS' in capacityPolicy,false,'There is no account limit to export');
assert.deepEqual(Object.keys(validatePolicy(DEFAULT_POLICY)).sort(),['enabled','version','warmSpareSlots']);
for(const value of [{...DEFAULT_POLICY,warmSpareSlots:9},{...DEFAULT_POLICY,warmSpareSlots:-1},{...DEFAULT_POLICY,enabled:'yes'},{...DEFAULT_POLICY,command:'kubectl'},
  {...DEFAULT_POLICY,maxAccounts:32}])assert.throws(()=>validatePolicy(value),'Writes accept only the limit-free schema');
// A policy stored before the limit was removed is still readable; its limit is ignored.
assert.deepEqual(validatePolicy({...DEFAULT_POLICY,maxAccounts:32},{legacy:true}),DEFAULT_POLICY);
assert.throws(()=>validatePolicy({...DEFAULT_POLICY,maxAccounts:32,command:'x'},{legacy:true}),'Legacy reads stay strict otherwise');
const users={alice:{runtimeSlot:'private-1',password:'do-not-project'},bob:{runtimeSlot:'private-2',disabled:true}};
const p=projection(users);assert.equal(p.registeredAccounts,2);assert.deepEqual(p.assignedSlots,['private-1','private-2']);assert(!JSON.stringify(p).includes('password'));
const root=fs.mkdtempSync(path.join(os.tmpdir(),'capacity-policy-'));
try{
 const file=path.join(root,'policy.json');atomicJSON(file,DEFAULT_POLICY);assert.deepEqual(readJSON(file),DEFAULT_POLICY);
 const capacity=path.join(root,'capacity');fs.mkdirSync(path.join(capacity,'policy'),{recursive:true});
 const policyFile=path.join(capacity,'policy','policy.json');atomicJSON(policyFile,{...DEFAULT_POLICY,maxAccounts:32});
 const manager=new Manager(capacity,{slots:{}}),originalPolicy=fs.readFileSync(policyFile);
 // Any number of accounts, beyond any former limit, reads and saves normally.
 for(const count of [7,32,33,500]){
  const retained=Object.fromEntries(Array.from({length:count},(_,i)=>['user'+i,{}]));
  assert.deepEqual(manager.policy(retained),DEFAULT_POLICY,'A legacy limit in the stored policy is ignored');
  assert.deepEqual(fs.readFileSync(policyFile),originalPolicy,'Reading never rewrites the stored policy');
 }
 const many=Object.fromEntries(Array.from({length:500},(_,i)=>['user'+i,{}]));
 assert.deepEqual(manager.save({...DEFAULT_POLICY,warmSpareSlots:1},many),{...DEFAULT_POLICY,warmSpareSlots:1});
 assert.deepEqual(readJSON(policyFile),{...DEFAULT_POLICY,warmSpareSlots:1},'Saving drops the legacy limit');
 atomicJSON(policyFile,{...DEFAULT_POLICY,warmSpareSlots:'2'});assert.throws(()=>manager.policy({}),'Malformed persisted policies still fail closed');
 atomicJSON(policyFile,DEFAULT_POLICY);fs.mkdirSync(path.join(capacity,'inventory'),{recursive:true});
 const retained={alice:{},bob:{}},snapshot={observedAt:new Date().toISOString(),available:true,capacity:{version:1,mainRegistered:2,additionalDeploymentsComplete:true,additionalAccounts:2,mainPlanningCeiling:18,resources:['cpu','memoryGiB','pods','storageGiB'].map(resource=>({resource,available:10,reserve:2,pairBudget:1,afterReserve:8,additionalPairs:8}))}};
 atomicJSON(path.join(capacity,'inventory','status.json'),snapshot);
 assert.equal(manager.summary(retained).controller.capacity.totalRegistered,4);
 assert.equal(manager.summary(retained).policy.warmSpareSlots,2);
 atomicJSON(file,{...DEFAULT_POLICY,enabled:false});assert.equal(readJSON(file).enabled,false);
 fs.writeFileSync(file,'x'.repeat(33));assert.throws(()=>readJSON(file,32));
 assert.throws(()=>readJSON(root));
 if(process.platform!=='win32'){
  const symlink=path.join(root,'link');fs.symlinkSync(file,symlink);assert.throws(()=>readJSON(symlink));
  require('child_process').execFileSync('mkfifo',[path.join(root,'fifo')]);const start=Date.now();assert.throws(()=>readJSON(path.join(root,'fifo')));assert(Date.now()-start<1000);
 }
}finally{fs.rmSync(root,{recursive:true,force:true});}
console.log('Capacity policy: no account limit, legacy policy read, bounded spares and safe persisted reads passed');
