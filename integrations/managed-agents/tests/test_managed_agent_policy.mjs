import assert from 'node:assert/strict';
import {authorizeRequest,lockSettings,lockProfile,MODEL} from '../scripts/managed_agent_policy.mjs';
const rows=[];function test(name,fn){fn();rows.push({name,passed:true});}
for(const path of ['/v1/chat/completions','/v1/messages','/v1/messages/count_tokens'])test(path,()=>assert.equal(authorizeRequest('POST',path,{model:MODEL}).model,MODEL));
test('catalog',()=>assert.deepEqual(authorizeRequest('GET','/v1/models').models,[MODEL]));
for(const model of ['deepseek-flash','other','',null])test('bad model '+model,()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model}),/MODEL_LOCKED/));
for(const role of ['user','admin','proxy_admin'])test('role no bypass '+role,()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:'other',role}),/MODEL_LOCKED/));
for(const p of ['/key/generate','/model/new','/v1/chat/completions?model=other','//v1/chat/completions'])test('bad path '+p,()=>assert.throws(()=>authorizeRequest('POST',p,{model:MODEL}),/ROUTE_LOCKED/));
for(const k of ['api_base','api_key','base_url','custom_llm_provider','fallbacks','extra_headers'])test('bad override '+k,()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:MODEL,[k]:'x'}),/OVERRIDE_DENIED/));
test('nested override',()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:MODEL,extra_body:{api_base:'x'}}),/OVERRIDE_DENIED/));
test('settings catalog locked without mutating source',()=>{const x={keep:1,'llm-pi-ai':{providers:{other:{}}}},y=lockSettings(x,'http://litellm.dsh.svc.cluster.local:4000/v1');assert.equal(y.keep,1);assert.deepEqual(Object.keys(y['llm-pi-ai'].providers),['litellm-cluster']);assert.equal(y['llm-pi-ai'].providers['litellm-cluster'].models.length,1);assert.ok(x['llm-pi-ai'].providers.other);});
test('profile preserves unrelated tool',()=>{const x=lockProfile([{id:'tool',config:{keep:true}}],'http://litellm.dsh.svc.cluster.local:4000/v1');assert.equal(x.find(e=>e.id==='tool').config.keep,true);assert.equal(x.find(e=>e.id==='llm-deepseek-account').disabled,true);});
for(const u of ['https://example.com/v1','http://litellm.dsh.svc.cluster.local.evil:4000/v1','http://litellm.dsh.svc.cluster.local:4000/v1?x=1'])test('bad endpoint '+u,()=>assert.throws(()=>lockSettings({},u),/GATEWAY_INVALID/));
test('preserve existing canonical capabilities',()=>{const m={id:MODEL,input:['text','image'],contextWindow:1048576};const y=lockSettings({'llm-pi-ai':{providers:{'litellm-cluster':{models:[m]}}}},'http://litellm.dsh.svc.cluster.local:4000/v1');assert.equal(JSON.stringify(y['llm-pi-ai'].providers['litellm-cluster'].models[0]),JSON.stringify(m));});
test('nested model override refused',()=>assert.throws(()=>authorizeRequest('POST','/v1/chat/completions',{model:MODEL,extra_body:{model:'other'}}),/OVERRIDE_DENIED/));
export default {scope:'ACTUAL_IN_PROCESS_PURE_POLICY_TESTS',passed:rows.length,total:rows.length,rows,modelCalls:0,clusterWrites:0};
