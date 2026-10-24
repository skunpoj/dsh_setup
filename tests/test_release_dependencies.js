const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-release-dependencies-'));
function json(file,value){fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(value));}
function sdk(folder,version){json(path.join(folder,'package.json'),{name:'@earendil-works/pi-ai',version,main:'index.js'});fs.writeFileSync(path.join(folder,'index.js'),'throw new Error("Provider must not be imported");');}
function check(){return spawnSync(process.execPath,[path.join(__dirname,'../scripts/verify_release_dependencies.js'),'0.2.1-rc.2','1.3.0'],{env:{...process.env,DSH_PACKAGE_DIR:root},encoding:'utf8'});}
try{
 json(path.join(root,'package.json'),{name:'@deepseek-ai/dsh',version:'0.2.1-rc.2'});
 const adapter=path.join(root,'node_modules/@deepseek-ai/dsh-llm-pi-ai');
 json(path.join(adapter,'package.json'),{name:'@deepseek-ai/dsh-llm-pi-ai',version:'0.2.1-rc.2'});
 sdk(path.join(root,'node_modules/@earendil-works/pi-ai'),'1.3.0');
 let result=check();assert.equal(result.status,0,result.stderr);assert.equal(JSON.parse(result.stdout).providerImported,false);
 // A correct top-level package must not hide an unreviewed nested adapter SDK.
 sdk(path.join(adapter,'node_modules/@earendil-works/pi-ai'),'1.4.0');
 result=check();assert.notEqual(result.status,0);assert.match(result.stderr,/unreviewed SDK release/);
 sdk(path.join(adapter,'node_modules/@earendil-works/pi-ai'),'1.3.0');
 result=check();assert.notEqual(result.status,0);assert.match(result.stderr,/managed loader target/);
 console.log(JSON.stringify({adapterResolution:true,providerNotImported:true,nestedVersionDriftRejected:true,unhookedNestedSDKRejected:true}));
}finally{
 assert.equal(path.dirname(root),path.resolve(os.tmpdir()));
 assert(path.basename(root).startsWith('dsh-release-dependencies-'));
 fs.rmSync(root,{recursive:true,force:true});
}
