const assert=require('assert');const {migrate}=require('../scripts/upgrade_runtime_profile.cjs');
const original=[{id:'custom',config:{value:'preserve'}},{id:'llm-pi-ai',config:{providers:{'litellm-cluster':{models:[{id:'deepseek-v4.1-flash',maxTokens:8192}]}}}}];
const seed=[{id:'agent-default-model',config:{provider:'litellm-cluster',model:'deepseek-v4.1-flash'}},{id:'session-title-llm',config:{provider:'litellm-cluster',model:'deepseek-v4.1-flash'}},{id:'llm-deepseek',disabled:true},{id:'llm-deepseek-account',disabled:true}];
const before=JSON.stringify(original),result=migrate(original,seed);assert.equal(JSON.stringify(original),before);assert.deepEqual(result.slice(0,2),original);
assert.deepEqual(migrate(result,seed),result);assert(result.find(x=>x.id==='llm-deepseek').disabled);
const changed=migrate([...original,{id:'agent-default-model',disabled:true,config:{provider:'deepseek-official',model:'deepseek-flash',other:'keep'}}],seed);
assert.deepEqual(changed.find(x=>x.id==='agent-default-model'),{id:'agent-default-model',disabled:false,config:{provider:'litellm-cluster',model:'deepseek-v4.1-flash',other:'keep'}});
assert.throws(()=>migrate([...original,original[0]],seed),/unique/);assert.throws(()=>migrate(original,[]),/missing/);assert.throws(()=>migrate([],seed),/canonical/);
// Regression (2026-10-30): DSH insert patches use an empty id and may repeat.
// Two of them crashed every workspace start; they must be kept unchanged.
const inserts=[{id:'',insert:{after:'system-prompt',entry:{id:'a'}}},{id:'',insert:{after:'system-prompt',entry:{id:'b'}}}];
const withInserts=migrate([...original,...inserts],seed);
assert.deepEqual(withInserts.filter(x=>x.id===''),inserts,'Empty-id insert entries are kept in order and unchanged');
assert.deepEqual(migrate(withInserts,seed),withInserts,'Idempotent with insert entries');
assert.throws(()=>migrate([...original,{insert:{}}],seed),/strings/,'A missing id is still refused');
const {configure}=require('../scripts/configure_managed_signin.cjs');
assert.doesNotThrow(()=>configure(withInserts,'litellm-cluster'),'Managed sign-in policy accepts repeated insert entries');
assert.throws(()=>configure([...withInserts,withInserts[0]],'litellm-cluster'),/unique/,'Duplicate named ids are still refused');
console.log('Managed profile migration preserves unrelated settings, is idempotent, keeps empty-id insert entries and refuses ambiguous profiles');
