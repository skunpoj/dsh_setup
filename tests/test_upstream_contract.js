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
 console.log('Reviewed target accepted; changed and missing upstream targets refused.');
}finally{fs.rmSync(root,{recursive:true,force:true});}
// The existing candidate job runs this suite; cover the managed transport too.
require('./test_managed_inference_transport.js');
