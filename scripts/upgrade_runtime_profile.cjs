// Operator/init-container migration. Never reads credentials or session events.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const ids=['agent-default-model','session-title-llm','llm-deepseek','llm-deepseek-account'];
function migrate(original,seed){
 if(!Array.isArray(original)||!Array.isArray(seed))throw Error('Expected profile arrays');
 for(const entries of [original,seed]){const keys=entries.map(x=>x.id);if(keys.some(x=>typeof x!=='string')||new Set(keys).size!==keys.length)throw Error('Profile IDs must be unique');}
 const result=structuredClone(original);
 for(const id of ids){const desired=seed.find(x=>x.id===id);if(!desired)throw Error('Qualified seed entry missing: '+id);
  const old=result.find(x=>x.id===id);
  if(old){if(id.startsWith('llm-deepseek'))old.disabled=true;else{old.disabled=false;old.config={...old.config,provider:desired.config.provider,model:desired.config.model};}}
  else {const added=structuredClone(desired);added.disabled=id.startsWith('llm-deepseek');result.push(added);}
 }
 const model=result.find(x=>x.id==='llm-pi-ai')?.config?.providers?.['litellm-cluster']?.models?.find(x=>x.id==='deepseek-v4.1-flash');
 if(!model)throw Error('Existing internal canonical model is missing; manual review required');
 return result;
}
function main(){
 const home=path.resolve(process.argv[2]||'');if(!process.argv[2])throw Error('Explicit state home required');
 const file=path.join(home,'profiles/web/cordis.patch.yml');if(fs.lstatSync(file).isSymbolicLink())throw Error('Refuse profile symlink');
 const yaml=require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
 const old=fs.readFileSync(file,'utf8'),seed=yaml.parse(fs.readFileSync('/opt/dsh/seed/dsh-home/profiles/web/cordis.patch.yml','utf8'));
 const before=yaml.parse(old),next=migrate(before,seed);
 if(JSON.stringify(before)===JSON.stringify(next)){console.log(JSON.stringify({changed:false,managedDefault:'deepseek-v4.1-flash'}));return;}
 const sha=crypto.createHash('sha256').update(old).digest('hex');const backup=path.join(home,'.upstream-profile-rollback',sha);
 fs.mkdirSync(backup,{recursive:true,mode:0o700});const retained=path.join(backup,'web-profile.yml');
 try{fs.writeFileSync(retained,old,{flag:'wx',mode:0o600});}catch(e){if(e.code!=='EEXIST'||fs.readFileSync(retained,'utf8')!==old)throw e;}
 const tmp=file+'.upgrade-'+process.pid;fs.writeFileSync(tmp,yaml.stringify(next),{flag:'wx',mode:0o600});
 if(fs.readFileSync(file,'utf8')!==old){fs.unlinkSync(tmp);throw Error('Concurrent profile change; preserved original');}
 fs.renameSync(tmp,file);const actual=yaml.parse(fs.readFileSync(file,'utf8'));if(JSON.stringify(actual)!==JSON.stringify(next))throw Error('Profile readback mismatch');
 console.log(JSON.stringify({changed:true,originalSHA256:sha,managedDefault:'deepseek-v4.1-flash',historyAndCredentialsTouched:false}));
}
if(require.main===module)main();module.exports={migrate};
