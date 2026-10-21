import assert from 'node:assert/strict';
import {clampMaxTokensToContext} from '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js';
const context={messages:[{role:'user',content:'x'.repeat(5600000)}]};
const model={provider:'litellm-cluster',api:'openai-completions',id:'deepseek-v4.1-flash',baseUrl:'http://litellm:4000/v1',contextWindow:1048576,maxTokens:8192};
assert.equal(clampMaxTokensToContext(model,context,8192),8192);
assert.equal(clampMaxTokensToContext(model,context,1),1);
assert.equal(clampMaxTokensToContext({...model,baseUrl:'https://unrelated.example/v1'},context,8192),1);
console.log(JSON.stringify({actualInstalledLoaderHookPassed:true,managedBudget:8192,explicitSmallCap:1,unrelatedGuardPreserved:true}));
