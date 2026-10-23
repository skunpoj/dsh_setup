const assert=require('assert');
const {configure}=require('../scripts/configure_workspace_policy');
const original=[{id:'llm-pi-ai',config:{models:['keep']}},{id:'workspace-controller',config:{documentsLookupTimeoutMs:321}}];
const result=configure(structuredClone(original));
assert.deepEqual(result[0],original[0]);
assert.equal(result[1].config.documentsDirectory,'/workspace');
assert.equal(result[1].config.documentsLookupTimeoutMs,321);
assert.deepEqual(configure(structuredClone(result)),result);
assert.equal(configure([])[0].name,'@deepseek-ai/dsh-api-workspace-controller');
assert.throws(()=>configure({}),/array/);
console.log('Workspace override is bounded, idempotent and preserves unrelated profile settings');

// Include managed-provider UI regressions in the existing runtime-policy test entry point.
require('./test_managed_signin.cjs');
