const assert=require('assert');const {migrate}=require('../scripts/upgrade_runtime_profile.cjs');
const original=[{id:'custom',config:{value:'preserve'}},{id:'llm-pi-ai',config:{providers:{'litellm-cluster':{models:[{id:'deepseek-v4.1-flash',maxTokens:8192}]}}}}];
const seed=[{id:'agent-default-model',config:{provider:'litellm-cluster',model:'deepseek-v4.1-flash'}},{id:'session-title-llm',config:{provider:'litellm-cluster',model:'deepseek-v4.1-flash'}},{id:'llm-deepseek',disabled:true},{id:'llm-deepseek-account',disabled:true}];
const before=JSON.stringify(original),result=migrate(original,seed);assert.equal(JSON.stringify(original),before);assert.deepEqual(result.slice(0,2),original);
assert.deepEqual(migrate(result,seed),result);assert(result.find(x=>x.id==='llm-deepseek').disabled);
const changed=migrate([...original,{id:'agent-default-model',disabled:true,config:{provider:'deepseek-official',model:'deepseek-flash',other:'keep'}}],seed);
assert.deepEqual(changed.find(x=>x.id==='agent-default-model'),{id:'agent-default-model',disabled:false,config:{provider:'litellm-cluster',model:'deepseek-v4.1-flash',other:'keep'}});
assert.throws(()=>migrate([...original,original[0]],seed),/unique/);assert.throws(()=>migrate(original,[]),/missing/);assert.throws(()=>migrate([],seed),/canonical/);
console.log('Managed profile migration preserves unrelated settings, is idempotent and refuses ambiguous profiles');
