'use strict';
// Web DSH asks each agent runtime a question and shows its answer. Offline: the real /agent-tasks page script runs in a
// VM against a synthetic broker that speaks the broker's /v1 event protocol (as proxied by agent_task_gateway.js).
// No model, no network, no workspace.
const assert=require('node:assert/strict'),vm=require('node:vm');
const {page,renderTaskOutput}=require('../scripts/agent_task_gateway');

// 1. Answer rendering, per runtime.
const claudeLines=[
 {type:'system',subtype:'init',session_id:'s1',tools:['Read']},
 {type:'assistant',message:{content:[{type:'text',text:'Let me read the README.'},{type:'tool_use',name:'Read',input:{file_path:'README.md'}}]}},
 {type:'user',message:{content:[{type:'tool_result',content:'# DSH secret-free readme'}]}},
 {type:'assistant',message:{content:[{type:'text',text:'The README describes DSH.'}]}},
 {type:'result',subtype:'success',is_error:false,result:'The README describes DSH.'}].map(x=>JSON.stringify(x)+'\n');
const render=(runtime,lines)=>{const state={};return lines.map(l=>renderTaskOutput(runtime,l,state)).join('');};
assert.equal(render('claude',claudeLines),'Let me read the README.\n[tool: Read]\nThe README describes DSH.\n','assistant text and tool names; result not repeated; tool results and init hidden');
assert.equal(render('claude',[JSON.stringify({type:'system'})+'\n',JSON.stringify({type:'result',is_error:false,result:'Only a result.'})+'\n']),'Only a result.\n','result shown when no assistant text came through');
assert.match(render('claude',[JSON.stringify({type:'result',is_error:true,subtype:'error_max_turns'})+'\n']),/\[error: error_max_turns\]/);
assert.equal(render('claude',['{"type":"assistant","message":{"content":[{"type":"te\n']),'{"type":"assistant","message":{"content":[{"type":"te\n','a truncated JSON line falls back to the raw text');
assert.equal(render('claude',['guard: model start admitted\n']),'guard: model start admitted\n','plain guard lines stay visible');
assert.equal(render('deepagents',['Deep Agents answer: 42\n','{"not":"claude"}\n']),'Deep Agents answer: 42\n{"not":"claude"}\n','Deep Agents output is shown verbatim');
assert.equal(render('sdk',['SDK answer\n']),'SDK answer\n','SDK output is shown verbatim');
assert.equal(renderTaskOutput('claude',undefined,{}),'');

// 2. The page asks each runtime and shows its answer.
function harness({capabilities,events,create}){
 const elements=new Map(),calls=[];let timers=[];
 const get=id=>{if(!elements.has(id))elements.set(id,{value:'',checked:false,disabled:false,textContent:'',scrollHeight:0,options:[]});return elements.get(id)};
 get('runtime').options=[{value:'sdk'},{value:'claude'},{value:'deepagents'},{value:'kilo'}];get('backend').value='private';get('backend').options=[{value:'private'},{value:'openshell'}];
 get('handoff').options=[{value:''},{value:'sdk'},{value:'claude'},{value:'deepagents'}];get('project').value='.';get('approved').checked=true;
 let polls=0;
 const fetch=async(path,options={})=>{calls.push({path,options});let status=200,result;
  if(path.endsWith('/capabilities'))result=capabilities;
  else if(path==='/api/agent-tasks'){[status,result]=create(JSON.parse(options.body));}
  else if(path.includes('/events?'))result=events(polls++);
  else throw Error('Unexpected synthetic path '+path);
  return {ok:status<400,json:async()=>result};};
 vm.runInNewContext(page('c'.repeat(64)).match(/<script>([\s\S]*?)<\/script>/)[1],{document:{getElementById:get},fetch,setTimeout:fn=>{timers.push(fn);return timers.length},console});
 return {get,calls,async drain(){const settle=async()=>{for(let k=0;k<10;k++)await new Promise(r=>setImmediate(r));};await settle();for(let i=0;i<20&&timers.length;i++){const t=timers;timers=[];for(const fn of t)await fn();await settle();}}};
}
const caps=sdkEnabled=>({runtimes:['claude','deepagents','kilo','sdk'],runtimeDetails:{sdk:{enabled:sdkEnabled,handoffEnabled:false,reason:'Official SDK native runtime qualification pending'}},backends:[{id:'private',enabled:true},{id:'openshell',enabled:false,reason:'pending'}]});
const id='d'.repeat(32);
const output=(runtime,text,sequence)=>({sequence,type:'output',data:{runtime,text}});
async function ask(runtime,lines,{sdkEnabled=true,expectStatus=202}={}){
 const h=harness({capabilities:caps(sdkEnabled),create:body=>expectStatus===202?[202,{taskId:id,state:'queued'}]:[expectStatus,{error:'OFFICIAL_SDK_NOT_QUALIFIED'}],
  events:n=>n===0?{taskId:id,state:'running',events:lines.map((t,i)=>output(runtime,t,i+1)),next:lines.length,nativeApproval:null}
               :{taskId:id,state:'completed',events:[{sequence:lines.length+1,type:'state',data:{state:'completed'}}],next:lines.length+1,nativeApproval:null}});
 await new Promise(r=>setImmediate(r));
 h.get('runtime').value=runtime;h.get('prompt').value='What does the README say?';
 await h.get('task').onsubmit({preventDefault(){}});await h.drain();
 return h;
}
(async()=>{
 let h=await ask('claude',claudeLines);
 const sent=JSON.parse(h.calls.find(c=>c.path==='/api/agent-tasks').options.body);
 assert.deepEqual(sent,{runtime:'claude',backend:'private',project:'.',prompt:'What does the README say?',writes:false,approved:true});
 assert.equal(h.calls.find(c=>c.path==='/api/agent-tasks').options.headers['X-DSH-Agent-CSRF'],'c'.repeat(64));
 assert.equal(h.get('output').textContent,'Let me read the README.\n[tool: Read]\nThe README describes DSH.\n');assert.doesNotMatch(h.get('output').textContent,/"type"/);
 assert.equal(h.get('status').textContent,'Task completed');assert.equal(h.get('start').disabled,false);
 h=await ask('deepagents',['Deep Agents: the README describes DSH.\n']);assert.equal(h.get('output').textContent,'Deep Agents: the README describes DSH.\n');assert.equal(h.get('status').textContent,'Task completed');
 h=await ask('sdk',['SDK: the README describes DSH.\n']);assert.equal(h.get('output').textContent,'SDK: the README describes DSH.\n');
 // Unqualified SDK: the option is disabled and the page falls back to the first enabled runtime; a forced request shows the broker's refusal.
 h=harness({capabilities:caps(false),create:()=>[503,{error:'OFFICIAL_SDK_NOT_QUALIFIED'}],events:()=>{throw Error('no events');}});
 h.get('runtime').value='sdk';await new Promise(r=>setImmediate(r));
 assert.equal(h.get('runtime').options[0].disabled,true);assert.equal(h.get('runtime').value,'claude');
 h.get('runtime').value='sdk';await h.get('task').onsubmit({preventDefault(){}});
 assert.equal(h.get('status').textContent,'OFFICIAL_SDK_NOT_QUALIFIED');assert.equal(h.get('start').disabled,false);
 // Handoff: Claude then Deep Agents; each stage's output is rendered with its own runtime.
 h=harness({capabilities:caps(true),create:body=>{assert.equal(body.handoffRuntime,'deepagents');return [202,{taskId:id,state:'queued'}];},
  events:n=>n===0?{taskId:id,state:'handoff',events:[output('claude',claudeLines[3],1),{sequence:2,type:'handoff',data:{from:'claude',to:'deepagents'}},output('deepagents','Deep Agents reviewed it.\n',3)],next:3,nativeApproval:null}
               :{taskId:id,state:'completed',events:[],next:3,nativeApproval:null}});
 await new Promise(r=>setImmediate(r));h.get('runtime').value='claude';h.get('handoff').value='deepagents';h.get('handoffPrompt').value='Review it';h.get('prompt').value='Summarise';
 await h.get('task').onsubmit({preventDefault(){}});await h.drain();
 assert.equal(h.get('output').textContent,'The README describes DSH.\nDeep Agents reviewed it.\n');
 console.log(JSON.stringify({passed:true,checks:['claude stream-json rendered as answer','result-only answer','error result','truncated line fallback','deepagents verbatim','sdk verbatim','request body and CSRF','unqualified SDK disabled and refused','claude to deepagents handoff'],providerCalls:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
