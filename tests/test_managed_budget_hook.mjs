import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import transport from '../scripts/managed_inference_transport.cjs';
const sdk = process.argv[2] || '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js';
// Default Docker execution uses the actual preload; an explicit SDK path registers
// the identical hook against an isolated public dependency installation.
if (process.argv[2]) transport.registerManagedBudget('http://litellm.llm.svc.cluster.local:4000',sdk);
const {clampMaxTokensToContext,buildBaseOptions} = await import(pathToFileURL(sdk).href);
const context={messages:[{role:'user',content:'x'.repeat(5600000)}]};
const model={provider:'litellm-cluster',api:'openai-completions',id:'deepseek-v4.1-flash',baseUrl:'http://litellm.llm.svc.cluster.local:4000/v1',contextWindow:1048576,maxTokens:8192};
assert.equal(clampMaxTokensToContext(model,context,8192),8192);
assert.equal(clampMaxTokensToContext(model,context,1),1);
for(const change of [{baseUrl:'https://unrelated.example/v1'},{provider:'other'},{api:'anthropic-messages'},{id:'other'},{contextWindow:131072}]) assert.equal(clampMaxTokensToContext({...model,...change},context,8192),1);
const signal=new AbortController().signal,onPayload=()=>{},onResponse=()=>{},onProviderStreamEvent=()=>{};
const options=buildBaseOptions(model,context,{maxTokens:1,signal,onPayload,onResponse,onProviderStreamEvent,samplingParams:{topP:0.8},timeoutMs:4567});
assert.equal(options.signal,signal);assert.equal(options.onPayload,onPayload);assert.equal(options.onResponse,onResponse);assert.equal(options.onProviderStreamEvent,onProviderStreamEvent);assert.equal(options.timeoutMs,4567);assert.equal(options.samplingParams.topP,0.8);assert.equal(options.maxTokens,1);
console.log(JSON.stringify({actualInstalledLoaderHookPassed:true,managedBudget:8192,explicitSmallCap:1,unrelatedGuardPreserved:true,samplingCallbacksCancellationPreserved:true}));
