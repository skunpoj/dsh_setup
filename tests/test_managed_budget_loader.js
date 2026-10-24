// Exercise real loader registration in fresh processes; no network/model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const sdk = process.argv[2] || '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js';
const hook = path.resolve(__dirname,'../scripts/managed_inference_transport.cjs');
function run(target, origin, expected) {
  const script = `import transport from ${JSON.stringify(pathToFileURL(hook).href)};
    transport.registerManagedBudget(${JSON.stringify(origin)},${JSON.stringify(target)});
    const {clampMaxTokensToContext} = await import(${JSON.stringify(pathToFileURL(target).href)});
    const model={provider:'litellm-cluster',api:'openai-completions',id:'deepseek-flash',baseUrl:'http://litellm.llm.svc.cluster.local:4000/v1',contextWindow:1048576,maxTokens:8192};
    const result=clampMaxTokensToContext(model,{messages:[{role:'user',content:'x'.repeat(5600000)}]},8192);
    if(result!==${expected})throw new Error('Unexpected budget '+result);`;
  return spawnSync(process.execPath,['--input-type=module','-e',script],{encoding:'utf8',env:{...process.env,DSH_MANAGED_TRANSPORT:'0',NODE_OPTIONS:''}});
}
for(const origin of ['http://litellm.llm.svc.cluster.local:4000','https://external.example','http://litellm.llm.svc.cluster.local:4001']) {
  const child=run(sdk,origin,origin==='http://litellm.llm.svc.cluster.local:4000'?8192:1);
  assert.equal(child.status,0,child.stderr);
}
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-sdk-drift-'));
try {
  const drift=path.join(dir,'simple-options.mjs');
  fs.writeFileSync(drift,fs.readFileSync(sdk,'utf8')+'\n');
  const child=run(drift,'http://litellm.llm.svc.cluster.local:4000',8192);
  assert.notEqual(child.status,0);
  assert.match(child.stderr,/Managed token budget SDK source changed/);
} finally {fs.rmSync(dir,{recursive:true,force:true});}
console.log(JSON.stringify({actualLoaderManagedOriginOnly:true,actualLoaderSourceDriftRefused:true}));
