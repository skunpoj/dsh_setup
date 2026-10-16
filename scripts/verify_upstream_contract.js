// Refuse changed/missing upstream patch targets before any overlay mutation.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
function verify(root,contract){
 const mismatches=[];
 for(const entry of contract.targets){
  const file=path.join(root,'node_modules/@deepseek-ai',entry.path);
  if(!fs.existsSync(file)){mismatches.push({path:entry.path,reason:'missing'});continue;}
  const actual=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  if(actual!==entry.sha256)mismatches.push({path:entry.path,reason:'changed',actualSha256:actual});
 }
 return mismatches;
}
module.exports={verify};
if(require.main===module){
 const contract=JSON.parse(fs.readFileSync(path.join(__dirname,'upstream_patch_contract.json'),'utf8'));
 const mismatches=verify(process.env.DSH_PACKAGE_DIR||'/usr/local/lib/node_modules/@deepseek-ai/dsh',contract);
 console.log(JSON.stringify({reviewedBaseline:contract.baselineVersion,checkedTargets:contract.targets.length,mismatches}));
 if(mismatches.length){console.error('Upstream patch contract changed. Review source and tests before updating reviewed hashes; refusing candidate.');process.exitCode=1;}
}
