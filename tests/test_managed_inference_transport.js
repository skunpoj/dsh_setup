const assert=require('node:assert/strict');
const {createManagedDispatcher}=require('../scripts/managed_inference_transport.cjs');
const seen=[];const handler={};
const base={dispatch:(opts,h)=>{seen.push([opts,h]);return true},close:(...a)=>a,destroy:(...a)=>a};
const dispatcher=createManagedDispatcher(base,'http://litellm.llm.svc.cluster.local:4000');
const managed={origin:new URL('http://litellm.llm.svc.cluster.local:4000'),headersTimeout:300000,bodyTimeout:300000,signal:{},path:'/v1/chat/completions'};
assert.equal(dispatcher.dispatch(managed,handler),true);
assert.equal(seen[0][0].headersTimeout,3600000);assert.equal(seen[0][0].bodyTimeout,3600000);
assert.equal(seen[0][0].signal,managed.signal);assert.equal(seen[0][1],handler);
assert.equal(managed.headersTimeout,300000);
for(const origin of ['https://github.com','http://litellm.llm.svc.cluster.local:4001','http://unrelated.internal:4000']){
 const options={origin,headersTimeout:500};dispatcher.dispatch(options,handler);assert.equal(seen.at(-1)[0],options);
}
assert.deepEqual(dispatcher.close('close'),['close']);assert.deepEqual(dispatcher.destroy('reason'),['reason']);
assert.throws(()=>createManagedDispatcher(base,'http://user:pass@host:4000'));
assert.throws(()=>createManagedDispatcher(base,'http://host/path'));
console.log(JSON.stringify({passed:true,managedOriginOnly:true,callerAbortSignalPreserved:true,otherOriginsUnchanged:true}));
