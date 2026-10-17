const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert'),crypto=require('crypto');
const {verify}=require('../scripts/verify_upstream_contract');
const source=fs.readFileSync(path.join(__dirname,'../scripts/configure_models.js'),'utf8');
const targets=[...new Set([...source.matchAll(/\$\{baseModulesDir\}\/([^`]+)/g)].map(m=>m[1]))].sort();
const reviewed=JSON.parse(fs.readFileSync(path.join(__dirname,'../scripts/upstream_patch_contract.json'),'utf8'));
assert.deepEqual(reviewed.targets.map(t=>t.path).sort(),targets,'Every current configurator target must have a reviewed contract');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-contract-'));
try{
 const file=path.join(root,'node_modules/@deepseek-ai/example/lib/index.js');fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,'reviewed');
 const contract={targets:[{path:'example/lib/index.js',sha256:crypto.createHash('sha256').update('reviewed').digest('hex')}]};
 assert.deepEqual(verify(root,contract),[]);
 fs.writeFileSync(file,'changed upstream body');assert.equal(verify(root,contract)[0].reason,'changed');
 fs.unlinkSync(file);assert.equal(verify(root,contract)[0].reason,'missing');

 fs.writeFileSync(file,'reviewed');
 fs.writeFileSync(path.join(root,'package.json'),JSON.stringify({name:'@deepseek-ai/dsh',version:'1.0.0'}));
 const metadata=path.join(root,'node_modules/@deepseek-ai/example/package.json');
 fs.writeFileSync(metadata,JSON.stringify({name:'@deepseek-ai/example',version:'1.0.0'}));
 const versioned={baselineVersion:'1.0.0',targets:[{...contract.targets[0],packageVersion:'1.0.0'}]};
 assert.deepEqual(verify(root,versioned),[]);
 fs.writeFileSync(metadata,JSON.stringify({name:'@deepseek-ai/example',version:'2.0.0'}));
 assert(verify(root,versioned).some(x=>x.reason==='module-identity-or-version'));
 fs.writeFileSync(path.join(root,'package.json'),JSON.stringify({name:'wrong',version:'1.0.0'}));
 assert(verify(root,versioned).some(x=>x.reason==='package-identity-or-version'));
 assert(verify(root,{targets:[{path:'../escape',sha256:'0'}]})[0].reason==='unsafe-target');
 // Direct invocation must refuse incomplete upstream inputs before touching a profile.
 const {spawnSync}=require('child_process');const home=path.join(root,'must-not-exist');
 const denied=spawnSync(process.execPath,[path.join(__dirname,'../scripts/configure_models.js')],{env:{...process.env,DSH_PACKAGE_DIR:root,DSH_HOME:home},encoding:'utf8'});
 assert.notEqual(denied.status,0);assert(!fs.existsSync(home));
 console.log('Reviewed targets accepted; changed/missing inputs, wrong package identity/version, unsafe paths and direct unguarded configuration refused.');
}finally{fs.rmSync(root,{recursive:true,force:true});}
// The existing candidate job runs this suite; cover the managed transport too.
require('./test_managed_inference_transport.js');

const patchset=JSON.parse(fs.readFileSync(path.join(__dirname,'../patches/dsh-0.2.0-rc.2/manifest.json'),'utf8'));
assert.equal(patchset.configuratorSHA256,crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname,'../scripts/configure_models.js'))).digest('hex'),'Regenerate reviewed patch export after changing configurator');
assert.equal(patchset.patchSHA256,crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname,'../patches/dsh-0.2.0-rc.2/compatibility.patch'))).digest('hex'));
assert.deepEqual(patchset.targets.map(x=>x.path).sort(),reviewed.targets.map(x=>x.path).sort());
