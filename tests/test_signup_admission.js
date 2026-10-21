'use strict';
const assert=require('assert/strict');
const {signupAdmission}=require('../scripts/signup_admission');
const now=Date.now(),fresh=()=>({observedAt:new Date(now).toISOString(),available:true,capacity:{version:1,mainRegistered:12,
 additionalDeploymentsComplete:true,additionalAccounts:2,additionalDeployments:[{label:'DSH2',accounts:1},{label:'DSH3',accounts:1}],
 observedUsage:{timestamp:new Date(now).toISOString(),cpu:10,memoryGiB:100,reservedCPU:15,reservedMemoryGiB:200},
 resources:['cpu','memoryGiB','pods','storageGiB'].map(resource=>({resource,available:10,reserve:2,pairBudget:1}))}});
assert(signupAdmission(fresh(),12,now).allowed);
for(const resource of ['cpu','memoryGiB','pods','storageGiB']){
 const s=fresh();s.capacity.resources.find(x=>x.resource===resource).available=2.5;
 assert.deepEqual(signupAdmission(s,12,now),{allowed:false,reason:'resource-pressure',resources:[resource]});
 s.capacity.resources.find(x=>x.resource===resource).available=3;
 assert(signupAdmission(s,12,now).allowed,'Recovery requires no policy or account change');
}
for(const mutate of [s=>s.available=false,s=>s.observedAt=new Date(now-60000).toISOString(),
 s=>s.capacity.observedUsage.timestamp=new Date(now-90000).toISOString(),
 s=>s.capacity.additionalDeploymentsComplete=false,s=>s.capacity.additionalDeployments.pop(),
 s=>s.capacity.resources[0].available=NaN,s=>s.capacity.resources[0].pairBudget=0,
 s=>s.capacity.resources[0].resource='memoryGiB',s=>s.capacity.mainRegistered=11]){
 const s=fresh();mutate(s);assert(!signupAdmission(s,12,now).allowed);
}
console.log(JSON.stringify({passed:true,allFourResourcePressureGates:true,automaticRecovery:true,additionalInstancesRequired:true,staleMissingAndMalformedFailClosed:true}));
