'use strict';
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const {createSessionDemand,publicStatus,runtimeName}=require('../scripts/session_demand');
const {atomicJSON,readJSON}=require('../scripts/capacity_policy');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'session-demand-'));
try{
 fs.mkdirSync(path.join(root,'policy'));fs.mkdirSync(path.join(root,'inventory'));
 const a={host:'dsh-u-'+'a'.repeat(16)+'-secure.llm.svc.cluster.local',port:3081},b={host:'dsh-u-'+'b'.repeat(16)+'-internet.llm.svc.cluster.local',port:3081};
 assert.equal(runtimeName({host:'litellm.llm.svc.cluster.local'}),null,'Only private user runtimes are managed');
 let t=Date.parse('2026-10-30T00:00:00Z');const now=()=>t;
 const d=createSessionDemand({root,now});assert.equal(d.seeded(),false);
 d.touch(a);t+=1000;d.touch(b);t+=1000;d.touch(a);
 d.flush(3600000);let file=readJSON(path.join(root,'policy','demand.json'));
 assert.deepEqual(Object.keys(file.runtimes).sort(),[runtimeName(a),runtimeName(b)].sort());
 assert.equal(file.runtimes[runtimeName(a)].requestedAt,'2026-10-30T00:00:00.000Z','Queue order keeps the first request time');
 assert.equal(file.runtimes[runtimeName(a)].lastActivityAt,'2026-10-30T00:00:02.000Z');
 assert(!JSON.stringify(file).includes('alice'),'No user names are published');
 // Socket bytes from the browser count as activity without adding listeners.
 const socket={bytesRead:0,destroyed:false};d.watch(socket,b);t+=60000;socket.bytesRead=10;d.flush(3600000);
 assert.equal(readJSON(path.join(root,'policy','demand.json')).runtimes[runtimeName(b)].lastActivityAt,new Date(t).toISOString());
 // Idle runtimes drop out; a release (sign-out) drops at once.
 t+=3600001;socket.destroyed=true;d.touch(a);d.flush(3600000);file=readJSON(path.join(root,'policy','demand.json'));
 assert.deepEqual(Object.keys(file.runtimes),[runtimeName(a)]);
 d.release([a]);d.flush(3600000);assert.deepEqual(readJSON(path.join(root,'policy','demand.json')).runtimes,{});
 // A gateway restart reloads demand instead of stopping everyone.
 d.touch(b);d.flush(3600000);const restarted=createSessionDemand({root,now});assert.equal(restarted.seeded(),true);
 restarted.flush(3600000);assert(readJSON(path.join(root,'policy','demand.json')).runtimes[runtimeName(b)]);
 // Missing or stale controller state fails open (proxy as before).
 assert.equal(d.state(a).state,'unknown');
 atomicJSON(path.join(root,'inventory','sessions.json'),{version:1,observedAt:new Date(t).toISOString(),available:true,
  runtimes:{[runtimeName(a)]:{state:'waiting',position:2},[runtimeName(b)]:{state:'running'}},summary:{running:1,starting:0,waiting:1,stopped:3,startsAvailable:0,idleTimeoutSeconds:3600}});
 assert.deepEqual(d.state(a),{state:'waiting',position:2});assert.deepEqual(d.state(b),{state:'running'});
 assert.equal(d.state({host:'litellm.llm.svc'}).state,'unmanaged');
 t+=120000;assert.equal(d.state(a).state,'unknown','Stale controller state fails open');
 // Public status is aggregate only.
 const s=publicStatus({summary:{running:3,starting:1,waiting:2,stopped:9,startsAvailable:0,idleTimeoutSeconds:3600}},
  {capacity:{observedUsage:{cpu:4,memoryGiB:500,reservedCPU:40,reservedMemoryGiB:600},resources:[{resource:'cpu',available:24},{resource:'memoryGiB',available:400}]}});
 assert.deepEqual(s.workspaces,{running:3,starting:1,waiting:2,stopped:9,capacity:4});assert.equal(s.idleTimeoutMinutes,60);
 assert.deepEqual(s.cpu,{totalCores:64,reservedCores:40,usedCores:4,reservedPercent:63,usedPercent:6});assert.deepEqual(s.memory,{totalGiB:1000,reservedGiB:600,usedGiB:500,reservedPercent:60,usedPercent:50});
 assert(!JSON.stringify(s).includes('dsh-u-'),'No runtime identities in public status');
 assert.equal(publicStatus(null,null).available,false);
 // Totals for the sign-in bars, GPU allocation and concurrent workspace capacity.
 const full=publicStatus({summary:{running:3,starting:1,waiting:0,stopped:9,startsAvailable:6,idleTimeoutSeconds:3600}},
  {capacity:{observedUsage:{cpu:4,memoryGiB:500,reservedCPU:40,reservedMemoryGiB:600,cpuAllocatable:64,memoryGiBAllocatable:1000,gpuAllocatable:4,gpuRequested:4},resources:[{resource:'cpu',available:24},{resource:'memoryGiB',available:400}]}});
 assert.deepEqual(full.cpu,{totalCores:64,reservedCores:40,usedCores:4,reservedPercent:63,usedPercent:6});
 assert.deepEqual(full.memory,{totalGiB:1000,reservedGiB:600,usedGiB:500,reservedPercent:60,usedPercent:50});
 assert.deepEqual(full.gpu,{total:4,allocated:4,allocatedPercent:100});
 assert.equal(full.workspaces.capacity,10,'running + starting + can start now');
 // Spawn progress passes through validated; unknown stages are dropped.
 atomicJSON(path.join(root,'inventory','sessions.json'),{version:1,observedAt:new Date(t).toISOString(),available:true,
  runtimes:{[runtimeName(a)]:{state:'starting',progress:{stage:'pulling-image',percent:45,detail:'Loading the workspace image'}},[runtimeName(b)]:{state:'starting',progress:{stage:'<script>',percent:50}}},summary:{running:0,starting:2,waiting:0,stopped:0,startsAvailable:1,idleTimeoutSeconds:3600}});
 assert.deepEqual(d.state(a).progress,{stage:'pulling-image',percent:45,detail:'Loading the workspace image'});
 assert.equal(d.state(b).progress,undefined,'Unknown stage is not trusted');
 console.log('Session demand: first-come order, idle and sign-out release, restart survival, fail-open state and aggregate status passed');
}finally{fs.rmSync(root,{recursive:true,force:true});}
