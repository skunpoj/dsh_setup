const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const vm=require('node:vm'),http=require('node:http'),crypto=require('node:crypto');
const text=fs.readFileSync(path.join(__dirname,'../scripts/auth_proxy.js'),'utf8');
const fragment=text.slice(text.indexOf('// BEGIN ADMIN TELEMETRY'),text.indexOf('// END ADMIN TELEMETRY.'));
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-telemetry-'));
let now=Date.parse('2026-10-19T04:00:00Z'),bobAvailable=false,aliceOutput=40,bobOutput=10,imported=false,removeAlice=false,calls=0;
class Clock extends Date{static now(){return now;}}
function session(id,output){return {sessionId:id,running:true,credential:'DO_NOT_EXPORT',projections:{values:{
 title:'PRIVATE_PROMPT',turnOutline:[{prompt:'PRIVATE_PROMPT',response:'PRIVATE_RESPONSE'}],
 tokenUsage:{uncachedInputTokens:400,cacheReadTokens:100,cacheWriteTokens:50,outputTokens:output},
 sessionStats:{turns:2,steps:5,decodeTokens:output,decodeMs:output*50},inbox:{'next-turn':[{},{}],'next-step':[]},sessionListMetadata:{lastPromptAt:1}}}};}
const backend=http.createServer((request,response)=>{
 if(request.url.startsWith('/?token=')){response.writeHead(302,{'Set-Cookie':'dsh-auth-fixture='+request.url.split('=')[1]+'; HttpOnly'});return response.end();}
 let body='';request.on('data',b=>body+=b);request.on('end',()=>{
  calls++;assert.equal(JSON.parse(body).method,'session/list');assert.equal(request.url,'/api/session/list');
  const bob=(request.headers.cookie||'').includes('bob');
  if(bob&&!bobAvailable){response.writeHead(503);return response.end('PRIVATE_UPSTREAM_ERROR');}
  let items=bob?[session('bob-session',bobOutput)]:(removeAlice?[]:[session('alice-session',aliceOutput)]);
  if(!bob&&imported)items.push(session('imported-session',500000));
  response.setHeader('Content-Type','application/json');response.end(JSON.stringify({result:{ok:true,value:{items}}}));
 });
});
(async()=>{try{
 await new Promise(resolve=>backend.listen(0,'127.0.0.1',resolve));const port=backend.address().port;
 fs.writeFileSync(path.join(directory,'capacity.json'),JSON.stringify({observedAt:'2026-10-19T04:00:00Z',secret:'DO_NOT_EXPORT',runtimes:[{
  user:'alice',environment:'secure',workspaceFileBytes:1234,workspaceScanComplete:true,stateUsedBytes:4096,stateCapacityBytes:8192,sourcePath:'PRIVATE_PATH',password:'DO_NOT_EXPORT'}]}));
 const context=vm.createContext({http,fs,crypto,Map,Date:Clock,Buffer,Promise,setTimeout,clearTimeout,
  process:{env:{DSH_TRUSTED_HOST:'localhost'}},AUDIT_DIR:directory,
  USER_TARGETS:{alice:{secure:{host:'127.0.0.1',port,tokenFile:'/runtime-tokens/alice'}},bob:{internet:{host:'127.0.0.1',port,tokenFile:'/runtime-tokens/bob'}}},
  getDshToken:file=>file.split('/').at(-1)});
 vm.runInContext('function allUserTargets(){return USER_TARGETS;}\n'+fragment+'\nglobalThis.telemetry={adminTelemetry,projectSessionMetrics};',context);
 const api=context.telemetry;
 const data=await api.adminTelemetry();assert.equal(data.availableRuntimes,1);assert.equal(data.configuredRuntimes,2);
 assert.equal(data.totals.sessions,1);assert.equal(data.totals.runningAgents,1);assert.equal(data.totals.queuedMessages,2);
 assert.equal(data.totals.turns,2);assert.equal(data.totals.llmSteps,5);assert.equal(data.totals.inputTokens,550);
 assert.equal(data.totals.outputTokens,40);assert.equal(data.totals.recordedDecodeTokensPerSecond,20);assert.equal(data.totals.outputTokensPerSecond,null);
 const serialized=JSON.stringify(data);for(const privateText of ['PRIVATE_PROMPT','PRIVATE_RESPONSE','DO_NOT_EXPORT','PRIVATE_PATH','PRIVATE_UPSTREAM_ERROR','alice-session'])assert(!serialized.includes(privateText));
 assert.equal(data.storage.runtimes[0].workspaceFileBytes,1234);
 const before=calls;await Promise.all([api.adminTelemetry(),api.adminTelemetry()]);assert.equal(calls,before,'Cached reads must not repeat runtime requests');
 bobAvailable=true;now+=16000;const recovered=await api.adminTelemetry();assert.equal(recovered.availableRuntimes,2);assert.equal(recovered.totals.outputTokensPerSecond,null,'Do not infer a rate across incomplete coverage');
 aliceOutput+=32;bobOutput+=16;now+=16000;const changed=await api.adminTelemetry();assert.equal(changed.totals.outputTokensPerSecond,3);assert.equal(changed.totals.recentDecodeTokensPerSecond,20);
 imported=true;now+=16000;const copy=await api.adminTelemetry();assert.equal(copy.totals.outputTokensPerSecond,0,'Imported old history must not appear as new model output');assert(copy.totals.outputTokens>500000);
 removeAlice=true;now+=16000;const removed=await api.adminTelemetry();assert.equal(removed.totals.outputTokensPerSecond,null,'Removed histories reset the rate baseline');
 const malformed=session('bad',-1);malformed.projections.values.tokenUsage.outputTokens='PRIVATE_COUNTER';
 assert.equal(api.projectSessionMetrics([malformed],'alice','secure').row.usageSessions,0);
 const fractional=session('fractional',3);fractional.projections.values.sessionStats.decodeTokens=3;fractional.projections.values.sessionStats.decodeMs=0.5;
 assert.equal(api.projectSessionMetrics([fractional],'alice','secure').row.recordedDecodeTokensPerSecond,6000);
 assert.throws(()=>api.projectSessionMetrics(new Array(2001).fill({}),'alice','secure'));
 console.log(JSON.stringify({passed:true,checks:['actual bounded native HTTP protocol','partial runtime coverage','running agents and queues','turn and LLM-step counts','input/output accumulation','decode-time average','counter-delta output rate','request cache','imported-history exclusion from live rate','counter reset handling','private content and credentials excluded','bounded session projection','numeric-only storage projection']}));
 }finally{await new Promise(resolve=>backend.close(resolve));fs.rmSync(directory,{recursive:true,force:true});}})().catch(error=>{console.error(error);process.exitCode=1;});
