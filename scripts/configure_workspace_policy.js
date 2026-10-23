'use strict';
// Containers have no desktop Documents resolver. Keep first-use files inside
// the already isolated, persistent workspace rather than the container HOME.
const fs = require('fs');
const path = require('path');
function configure(profile) {
  if (!Array.isArray(profile)) throw new Error('Web profile must be an array');
  let entry = profile.find(item => item.id === 'workspace-controller');
  if (!entry) {
    entry = {id:'workspace-controller',name:'@deepseek-ai/dsh-api-workspace-controller',config:{}};
    profile.push(entry);
  }
  entry.config ??= {};
  entry.config.documentsDirectory = '/workspace';
  return require('./configure_managed_signin.cjs').configure(profile,process.env.DSH_MANAGED_TRANSPORT==='1'?'litellm-cluster':undefined);
}
if (require.main === module) {
  const YAML = require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
  const file = path.join(process.argv[2], 'profiles/web/cordis.patch.yml');
  const original = fs.readFileSync(file,'utf8');
  const next = YAML.stringify(configure(YAML.parse(original)));
  if (next !== original) {
    const backup = file+'.before-workspace-policy-'+Date.now();
    fs.writeFileSync(backup,original,{flag:'wx',mode:0o600});
    const temporary = file+'.workspace-'+process.pid;
    fs.writeFileSync(temporary,next,{flag:'wx',mode:0o600});
    if (fs.readFileSync(file,'utf8') !== original) { fs.unlinkSync(temporary); throw new Error('Concurrent profile change'); }
    fs.renameSync(temporary,file);
  }
  const result=YAML.parse(fs.readFileSync(file,'utf8')).find(item=>item.id==='workspace-controller');
  if(result.config.documentsDirectory!=='/workspace')throw new Error('Workspace policy readback mismatch');
  console.log(JSON.stringify({documentsDirectory:'/workspace',preservesExistingRegistry:true}));
}
module.exports={configure};
