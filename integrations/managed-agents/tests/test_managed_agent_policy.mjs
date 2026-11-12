import assert from 'node:assert/strict';
import fs from 'node:fs';
import {authorizeRequest,lockSettings,lockProfile,MODEL,MANAGED_INPUT} from '../scripts/managed_agent_policy.mjs';
const rows=[];function test(name,fn){fn();rows.push({name,passed:true});}
test('namespace renderer retains canonical gateway',()=>{const source=fs.readFileSync(new URL('../scripts/render_managed_agent_profile.mjs',import.meta.url),'utf8');assert.ok(source.includes("p.base_url='http://litellm-gateway.'+n+'.svc.cluster.local:4000/v1'"));assert.ok(!source.includes("p.base_url='http://litellm.'+n"));});
for(const path of ['/v1/chat/completions','/v1/messages','/v1/messages/count_tokens'])test(path,()=>assert.equal(authorizeRequest('POST',path,{model:MODEL}).model,MODEL));
test('catalog',()=>assert.deepEqual(authorizeRequest('GET','/v1/models').models,[MODEL]));
for(const model of ['deepseek-flash','other','',null])test('bad model '+model,()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model}),/MODEL_LOCKED/));
for(const role of ['user','admin','proxy_admin'])test('role no bypass '+role,()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:'other',role}),/MODEL_LOCKED/));
for(const p of ['/key/generate','/model/new','/v1/chat/completions?model=other','//v1/chat/completions'])test('bad path '+p,()=>assert.throws(()=>authorizeRequest('POST',p,{model:MODEL}),/ROUTE_LOCKED/));
for(const k of ['api_base','api_key','base_url','custom_llm_provider','fallbacks','extra_headers'])test('bad override '+k,()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:MODEL,[k]:'x'}),/OVERRIDE_DENIED/));
test('nested override',()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:MODEL,extra_body:{api_base:'x'}}),/OVERRIDE_DENIED/));
test('settings catalog locked without mutating source',()=>{const x={keep:1,'llm-pi-ai':{providers:{other:{}}}},y=lockSettings(x,'http://litellm-gateway.llm.svc.cluster.local:4000/v1');assert.equal(y.keep,1);assert.deepEqual(Object.keys(y['llm-pi-ai'].providers),['litellm-cluster']);assert.equal(y['llm-pi-ai'].providers['litellm-cluster'].models.length,1);assert.ok(x['llm-pi-ai'].providers.other);});
test('profile preserves unrelated tool',()=>{const x=lockProfile([{id:'tool',config:{keep:true}}],'http://litellm-gateway.llm.svc.cluster.local:4000/v1');assert.equal(x.find(e=>e.id==='tool').config.keep,true);assert.equal(x.find(e=>e.id==='llm-deepseek-account').disabled,true);});
for(const u of ['https://example.com/v1','http://litellm.dsh.svc.cluster.local.evil:4000/v1','http://litellm-gateway.llm.svc.cluster.local:4000/v1?x=1'])test('bad endpoint '+u,()=>assert.throws(()=>lockSettings({},u),/GATEWAY_INVALID/));
test('preserve existing canonical capabilities except input, which is held to the text-only engine policy',()=>{const m={id:MODEL,input:['text','image'],contextWindow:1048576};const y=lockSettings({'llm-pi-ai':{providers:{'litellm-cluster':{models:[m]}}}},'http://litellm-gateway.llm.svc.cluster.local:4000/v1');assert.deepEqual(y['llm-pi-ai'].providers['litellm-cluster'].models[0],{id:MODEL,input:['text'],contextWindow:1048576});});
test('nested model override refused',()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:MODEL,extra_body:{model:'other'}}),/OVERRIDE_DENIED/));
test('title entry keeps the required length fields',()=>{const g='http://litellm-gateway.llm.svc.cluster.local:4000/v1';const fresh=lockProfile([],g).find(e=>e.id==='session-title-llm').config;assert.deepEqual(fresh,{targetWords:5,targetCjkCharacters:10,maxInputBytes:4096,maxOutputTokens:4096,timeoutMs:60000,provider:'litellm-cluster',model:MODEL});const kept=lockProfile([{id:'session-title-llm',config:{targetWords:9,provider:'x',model:'y'}}],g).find(e=>e.id==='session-title-llm').config;assert.equal(kept.targetWords,9);assert.equal(kept.provider,'litellm-cluster');assert.equal(kept.targetCjkCharacters,10);const agent=lockProfile([],g).find(e=>e.id==='agent-default-model').config;assert.deepEqual(agent,{provider:'litellm-cluster',model:MODEL});});
// Input policy (10 Nov 2026): the lock runs on every workspace start (install_single_model_startup.py). The live
// engine is text-only, so input is held to MANAGED_INPUT for every profile and settings file; the user's other
// model fields are kept across starts.
{
 const g='http://litellm-gateway.llm.svc.cluster.local:4000/v1';
 const modelOf=profile=>profile.find(e=>e.id==='llm-pi-ai').config.providers['litellm-cluster'].models;
 const legacy={id:MODEL,name:'DeepSeek-V4.1-Flash-1017 (managed alias)',maxTokens:8192,input:['text']};
 const withModel=m=>[{id:'llm-pi-ai',name:'@deepseek-ai/dsh-llm-pi-ai',config:{providers:{'litellm-cluster':{displayName:'x',api:'openai-completions',baseURL:'http://evil.example/v1',apiKeyEnv:'X',models:[m]}}}}];
 test('MANAGED_INPUT is text only while the engine is a text-only server',()=>assert.deepEqual([...MANAGED_INPUT],['text']));
 test('fresh profile and fresh settings are text only',()=>{assert.deepEqual(modelOf(lockProfile([],g))[0],legacy);assert.deepEqual(lockSettings({},g)['llm-pi-ai'].providers['litellm-cluster'].models[0],legacy);});
 test('an Image tick in Settings is reset to text at the next start; other user fields are kept',()=>{const ticked={...legacy,input:['text','image'],maxTokens:4096,contextWindow:1048576};assert.deepEqual(modelOf(lockProfile(withModel(ticked),g)),[{...ticked,input:['text']}]);});
 test('settings.yaml from configure_models.js ([text, image]) is held to text too',()=>{const fromConfigure={id:MODEL,name:'DeepSeek-V4.1-Flash (1M CED MoE)',contextWindow:1048576,maxTokens:8192,input:['text','image']};const y=lockSettings({'llm-pi-ai':{providers:{'litellm-cluster':{defaultInput:['text','image'],models:[fromConfigure]}}}},g);const prov=y['llm-pi-ai'].providers['litellm-cluster'];assert.deepEqual(prov.models,[{...fromConfigure,input:['text']}]);assert.equal(prov.defaultInput,undefined,'no provider-wide image default survives');});
 test('the lock still forces provider, gateway and model id; one model entry',()=>{const p=lockProfile(withModel({...legacy,maxTokens:2048}),g).find(e=>e.id==='llm-pi-ai').config.providers;assert.deepEqual(Object.keys(p),['litellm-cluster']);assert.equal(p['litellm-cluster'].baseURL,g);assert.equal(p['litellm-cluster'].apiKeyEnv,'DEEPSEEK_API_KEY');assert.deepEqual(p['litellm-cluster'].models,[{...legacy,maxTokens:2048}]);});
 test('every start is idempotent',()=>{for(const start of [[],withModel(legacy),withModel({...legacy,input:['text','image']})]){const once=lockProfile(start,g);assert.deepEqual(lockProfile(once,g),once);}});
}
export default {scope:'ACTUAL_IN_PROCESS_PURE_POLICY_TESTS',passed:rows.length,total:rows.length,rows,modelCalls:0,clusterWrites:0};
