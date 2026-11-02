'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm');
const {page}=require('../scripts/agent_task_gateway');

async function scenario(allowOnce){
 const elements=new Map(),calls=[],timers=[];
 const get=id=>{if(!elements.has(id))elements.set(id,{value:'',checked:false,disabled:false,textContent:'',scrollHeight:0,options:[]});return elements.get(id)};
 get('runtime').value='sdk';get('backend').value='private';get('backend').options=[{value:'openshell',disabled:true}];
 get('project').value='.';get('prompt').value='synthetic only';get('writes').checked=allowOnce;get('approved').checked=true;
 const ticket={approvalId:'a'.repeat(32),generation:'g1',toolName:'write',callId:'native1',allowOnceAdmitted:allowOnce};
 const fetch=async(path,options={})=>{
  calls.push({path,options});
  let result;
  if(path.endsWith('/capabilities'))result={backends:[{id:'openshell',enabled:false,reason:'not qualified'}]};
  else if(path==='/api/agent-tasks')result={taskId:'b'.repeat(32)};
  else if(path.includes('/events?'))result={state:'awaiting_approval',events:[],next:1,nativeApproval:ticket};
  else if(path.endsWith('/approve'))result={state:'running'};
  else throw Error('Unexpected synthetic HTTP path');
  return {ok:true,json:async()=>result};
 };
 const html=page('c'.repeat(64)),script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
 vm.runInNewContext(script,{document:{getElementById:get},fetch,setTimeout:fn=>{timers.push(fn);return timers.length},console});
 await get('task').onsubmit({preventDefault(){}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('approve').disabled,!allowOnce);
 assert.equal(get('reject').disabled,false);
 assert.equal(get('approve').textContent,'Allow SDK action once');
 const action=allowOnce?'approve':'reject';
 await get(action).onclick();
 const decisions=calls.filter(x=>x.path.endsWith('/approve'));
 assert.equal(decisions.length,1);
 assert.deepEqual(JSON.parse(decisions[0].options.body),{approvalId:ticket.approvalId,generation:'g1',outcome:allowOnce?'allowed-once':'rejected'});
 assert.equal(decisions[0].options.credentials,'same-origin');
 assert.equal(get('approve').disabled,true);assert.equal(get('reject').disabled,true);
 assert.equal(calls.filter(x=>x.path==='/api/agent-tasks').length,1);
}
async function capabilityScenario(enabled){
 const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',disabled:false,options:[]});return elements.get(id)};
 get('runtime').value='sdk';get('runtime').options=[{value:'sdk'},{value:'claude'}];
 get('backend').options=[{value:'openshell'}];get('handoff').options=[{value:''},{value:'sdk'}];
 const fetch=async()=>({ok:true,json:async()=>({backends:[{id:'openshell',enabled:false,reason:'pending'}],
  runtimeDetails:{sdk:{enabled,handoffEnabled:false,reason:'native qualification pending'}}})});
 const script=page('c'.repeat(64)).match(/<script>([\s\S]*?)<\/script>/)[1];
 vm.runInNewContext(script,{document:{getElementById:get},fetch,setTimeout:()=>0,console});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(get('runtime').options[0].disabled,!enabled);
 assert.equal(get('runtime').value,enabled?'sdk':'claude');
 assert.equal(get('handoff').options[1].disabled,true);
 assert.equal(get('handoff').disabled,enabled);
}
async function main(){await scenario(false);await scenario(true);await capabilityScenario(false);await capabilityScenario(true);console.log(JSON.stringify({passed:4,failed:0,scope:'synthetic-page-script-only',providerCalls:0}));}
main().catch(e=>{console.error(e);process.exitCode=1});
