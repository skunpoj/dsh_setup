// Run actual reviewed/patched pure functions with synthetic dependencies only.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const root=process.env.DSH_PACKAGE_DIR||'/usr/local/lib/node_modules/@deepseek-ai/dsh';
const base=path.join(root,'node_modules/@deepseek-ai');
function read(name){return fs.readFileSync(path.join(base,name+'/lib/index.js'),'utf8');}
const pi=read('dsh-llm-pi-ai');
const sandbox={Buffer,Map,Error,requestImageTarget:()=>({}),requestImageHandleText:()=> 'real image handle'};
vm.createContext(sandbox);
vm.runInContext(pi.slice(pi.indexOf('function userContent('),pi.indexOf('/** Convert a projected declaration')),sandbox);
const sc=read('dsh-api-session-controller');
vm.runInContext(sc.slice(sc.indexOf('async function buildModelCatalog('),sc.indexOf('/**\n* Check a GUI selection')),sandbox);
// Upstream discovery intentionally withholds uncredentialed routes. Exercise
// the installed method with synthetic auth, without a credential store or I/O.
sandbox.LlmError=class extends Error {};
vm.runInContext('class DiscoveryProbe { '+pi.slice(pi.indexOf('\tlistModels(provider) {'),pi.indexOf('\tresolveModel(provider, model, _signal) {'))+' }; globalThis.DiscoveryProbe=DiscoveryProbe;',sandbox);
(async()=>{
 const discovery=new sandbox.DiscoveryProbe();
 discovery.current=()=>({models:{getModels:()=>[{id:'deepseek-v4.1-flash',name:'Managed',input:['text','image']} ]}});
 discovery.profileOf=()=>({});
 discovery.config={resolveApiKey:async()=>{throw Object.assign(new sandbox.LlmError('synthetic absent key'),{code:'MISSING_CREDENTIAL'});}};
 assert.equal((await discovery.listModels('litellm-cluster')).length,0,'Missing credentials must not advertise a fake healthy route');
 discovery.config.resolveApiKey=async()=> 'synthetic-no-network-key';
 assert.equal((await discovery.listModels('litellm-cluster'))[0].id,'deepseek-v4.1-flash');
 const ref={attachmentId:'sha256:'+ 'a'.repeat(64),name:'old.png'};
 const messages=[{content:[{type:'image',attachment:ref}]}];
 const signal=new AbortController().signal;
 const missing=Object.assign(new Error('missing'),{code:'ATTACHMENT_NOT_FOUND'});
 const omitted=await sandbox.prepareRequestImages(messages,{readImageRequest:async()=>{throw missing;}},{},signal);
 assert.equal(omitted.size,0);
 assert.equal(sandbox.userContent(messages[0].content,omitted,()=>({})),'[image omitted: attachment old.png not found on host]');
 const corruption=Object.assign(new Error('corrupt'),{code:'ATTACHMENT_READ_FAILED'});
 await assert.rejects(sandbox.prepareRequestImages(messages,{readImageRequest:async()=>{throw corruption;}},{},signal),e=>e===corruption);
 const aborted=new AbortController();aborted.abort();
 await assert.rejects(sandbox.prepareRequestImages(messages,{readImageRequest:async()=>{throw missing;}},{},aborted.signal),e=>e===missing);
 const original={data:new Uint8Array([1,2,3]),mediaType:'image/png',bytes:3};
 const present=await sandbox.prepareRequestImages(messages,{readImageRequest:async()=>original},{},signal);
 const content=sandbox.userContent(messages[0].content,present,()=>({}));
 assert.equal(content[1].data,'AQID');assert.equal(content[1].mimeType,'image/png');
 let reads=0;
 await sandbox.prepareRequestImages([{content:[...messages[0].content,...messages[0].content]}],{readImageRequest:async()=>{reads++;return original;}},{},signal);
 assert.equal(reads,1,'Duplicate images must still deduplicate');
 const ctx={agentDefaultModel:{currentSelection:()=>({provider:'litellm-cluster',model:'deepseek-v4.1-flash'})},llm:{
  listProviders:()=>[{id:'litellm-cluster',name:'Managed'},{id:'failed-provider',name:'Broken'}],
  listModels:async id=>{if(id==='failed-provider')throw new Error('synthetic catalog error');return [{id:'deepseek-v4.1-flash',name:'Managed'}];},
  resolveModelInfo:async()=>({reasoning:{efforts:[{id:'low',name:'Low'}],defaultEffort:'low'}})
 }};
 const catalog=await sandbox.buildModelCatalog(ctx);
 assert.equal(catalog.default.provider,'litellm-cluster');
 assert.equal(JSON.stringify(catalog.routableProviders),'["litellm-cluster"]');
 assert.equal(catalog.failures[0].id,'failed-provider','Provider failures must not be replaced with fake healthy data');
 assert.equal(catalog.groups[0].models[0].reasoning.defaultEffort,'low');
 const contract=require('../scripts/upstream_patch_contract.json'),crypto=require('crypto');
 for(const e of contract.targets.filter(e=>e.patched===false))assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(base,e.path))).digest('hex'),e.sha256,'Protected upstream permission/UI/prompt bytes changed: '+e.path);
 console.log(JSON.stringify({missingCredentialCatalogWithheld:true,syntheticCredentialCatalogVisible:true,missingImageTruthful:true,corruptImagePropagated:true,cancellationPreserved:true,realImagePreserved:true,duplicateImagesDeduplicated:true,actualCatalogFunction:true,providerFailurePreserved:true,protectedUpstreamFiles:8,inference:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
