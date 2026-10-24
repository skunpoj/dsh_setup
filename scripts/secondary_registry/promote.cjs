'use strict';
// Remote institutional builder only. No build, container start, deploy, prune or retry.
function plan(c){
 if(!c||Object.keys(c).sort().join()!==['configDigest','layers','sourceRef','targetRef'].sort().join())throw Error('Exact qualified-image inputs required');
 const digest=/^sha256:[a-f0-9]{64}$/;
 if(!digest.test(c.configDigest)||!Array.isArray(c.layers)||!c.layers.length||c.layers.some(x=>!digest.test(x)))throw Error('Original qualified config and ordered layers required');
 if(!/^[a-z0-9.-]+(?::[0-9]{1,5})?\/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$/.test(c.sourceRef))throw Error('Immutable source reference required');
 if(!/^[a-z0-9.-]+(?::[0-9]{1,5})?\/[a-z0-9._/-]+:candidate-[a-z0-9-]+$/.test(c.targetRef)||c.targetRef.includes('/../'))throw Error('Explicit unique candidate target required');
 return [['pull',c.sourceRef],['image','inspect',c.sourceRef],['tag',c.sourceRef,c.targetRef],['push',c.targetRef]];
}
function verify(inspect,c){const a=Array.isArray(inspect)?inspect[0]:null;if(!a||a.Id!==c.configDigest||JSON.stringify(a.RootFS?.Layers)!==JSON.stringify(c.layers))throw Error('Qualified image content differs');return true;}
async function promote(c,run){const commands=plan(c);await run(commands[0]);verify(JSON.parse(await run(commands[1])),c);await run(commands[2]);const pushed=await run(commands[3]);const matches=[...pushed.matchAll(/digest:\s*(sha256:[a-f0-9]{64})/g)];if(matches.length!==1)throw Error('Unambiguous pushed manifest digest required');const ref=c.targetRef.slice(0,c.targetRef.lastIndexOf(':'))+'@'+matches[0][1];await run(['pull',ref]);verify(JSON.parse(await run(['image','inspect',ref])),c);return {immutableRef:ref,configDigest:c.configDigest,orderedLayers:c.layers,pushPullVerified:true,containerStarted:false,deployed:false};}
if(require.main===module){
 const fs=require('node:fs'),cp=require('node:child_process');
 if(process.env.DSH_REMOTE_REGISTRY_OPERATOR!=='approved-remote-builder'||process.argv.length!==4)throw Error('Remote operator admission and config/NEW receipt paths required');
 const c=JSON.parse(fs.readFileSync(process.argv[2],'utf8')); plan(c);
 // Reserve the receipt before any network/daemon operation; existing evidence refuses replay.
 const receipt=fs.openSync(process.argv[3],'wx',384);
 fs.writeFileSync(receipt,JSON.stringify({status:'started',deployed:false}));
 const run=args=>new Promise((resolve,reject)=>{const p=cp.spawn('docker',args,{shell:false,stdio:['ignore','pipe','pipe']});let out='',size=0,refused=false,killTimer;const stop=()=>{refused=true;p.kill('SIGTERM');killTimer=setTimeout(()=>p.kill('SIGKILL'),5000);};const timer=setTimeout(stop,300000);for(const s of[p.stdout,p.stderr])s.on('data',b=>{size+=b.length;if(size>8*1024*1024){if(!refused)stop();}else out+=b.toString();});p.on('error',e=>{clearTimeout(timer);clearTimeout(killTimer);reject(e);});p.on('close',code=>{clearTimeout(timer);clearTimeout(killTimer);code===0&&!refused?resolve(out):reject(Error('Docker operation failed; preserve protected operator logs, do not retry automatically'));});});
 promote(c,run).then(r=>{fs.ftruncateSync(receipt,0);fs.writeSync(receipt,JSON.stringify(r,null,2),0,'utf8');fs.closeSync(receipt);console.log('Same qualified image push/pull verified; no deployment.');}).catch(()=>{fs.ftruncateSync(receipt,0);fs.writeSync(receipt,JSON.stringify({status:'failed',deployed:false,retryAutomatically:false}),0,'utf8');fs.closeSync(receipt);console.error('Registry promotion refused or failed; no deployment performed.');process.exitCode=1;});
}
module.exports={plan,verify,promote};
