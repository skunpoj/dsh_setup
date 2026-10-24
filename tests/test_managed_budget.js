const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {patchManagedBudget} = require('../scripts/managed_inference_transport.cjs');
const sdk = process.argv[2] || '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js';
const source = fs.readFileSync(sdk, 'utf8');
const patched = patchManagedBudget(source, 'http://litellm.llm.svc.cluster.local:4000');
// Evaluate the complete reviewed module body, including intervening sampling exports.
// Only imports/exports are removed; estimator and thinking-level dependency are deterministic stubs.
function evaluate(text) {
  const sandbox = {estimateContextTokens: () => ({tokens: 1400000}), clampThinkingLevel: (_model, level) => level};
  vm.createContext(sandbox);
  vm.runInContext(text.replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '') + '\nglobalThis.sdk = {clampMaxTokensToContext, buildBaseOptions, resolveSamplingParams, adjustMaxTokensForThinking};', sandbox);
  return sandbox.sdk;
}
const api = evaluate(patched), original = evaluate(source);
const model = {provider:'litellm-cluster',api:'openai-completions',id:'deepseek-v4.1-flash',baseUrl:'http://litellm.llm.svc.cluster.local:4000/v1',contextWindow:1048576,maxTokens:8192};
for (const cap of [1,40,8192,16000]) assert.equal(api.clampMaxTokensToContext(model,{},cap),Math.min(cap,8192));
assert.equal(api.clampMaxTokensToContext({...model,maxTokens:4096},{},8192),4096);
assert.equal(api.clampMaxTokensToContext({...model,id:'deepseek-flash'},{},8192),8192);
assert.equal(api.clampMaxTokensToContext({...model,baseUrl:model.baseUrl+'/'},{},8192),8192);
for(const change of [{provider:'other'},{baseUrl:'https://external.example/v1'},{baseUrl:model.baseUrl+'?x=1'},{baseUrl:model.baseUrl+'/other'},{baseUrl:undefined},{id:'unrelated'},{contextWindow:131072},{contextWindow:0},{api:'anthropic-messages'}]) {
  assert.equal(api.clampMaxTokensToContext({...model,...change},{},8192),original.clampMaxTokensToContext({...model,...change},{},8192));
}
const signal = new AbortController().signal;
const options = {reasoning:'high',samplingParams:{topP:0.8},maxTokens:1,signal,onPayload:()=>{},onResponse:()=>{},onProviderStreamEvent:()=>{},timeoutMs:1234,maxRetries:2};
const sampled = {...model,samplingParams:{temperature:0.2,topP:0.1},samplingParamsByThinkingLevel:{high:{temperature:0.7}}};
const built = api.buildBaseOptions(sampled,{},options,'dummy');
assert.equal(built.maxTokens,1);
assert.deepEqual(JSON.parse(JSON.stringify(built.samplingParams)),{temperature:0.7,topP:0.8});
for(const key of ['signal','onPayload','onResponse','onProviderStreamEvent','timeoutMs','maxRetries']) assert.equal(built[key],options[key]);
assert.equal(api.buildBaseOptions(model,{},undefined).maxTokens,8192);
assert.deepEqual(JSON.parse(JSON.stringify(api.adjustMaxTokensForThinking(1,8192,'high'))),JSON.parse(JSON.stringify(original.adjustMaxTokensForThinking(1,8192,'high'))));
assert.throws(()=>patchManagedBudget(source+'\n','http://litellm.llm.svc.cluster.local:4000'),/source changed/);
assert.throws(()=>patchManagedBudget(source.replace('onPayload:', 'onPayloadChanged:'),'http://litellm.llm.svc.cluster.local:4000'),/source changed/);
console.log(JSON.stringify({passed:true,managedExactBudget:true,explicitSmallLimitsPreserved:true,otherRoutesUnchanged:true,sourceDriftRefused:true,samplingAndCallbacksPreserved:true}));
