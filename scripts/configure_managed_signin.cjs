'use strict';
// Managed-provider UI policy. Host authentication and provider credentials are untouched.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
function configure(profile,managedProvider){
 if(!Array.isArray(profile))throw Error('Expected profile array');
 // Same rule as the startup migration: empty-id insert entries may repeat.
 require('./upgrade_runtime_profile.cjs').assertUniqueIds(profile);
 const selected=profile.find(row=>row.id==='agent-default-model');
 if((selected?.config?.provider??managedProvider)!=='litellm-cluster')return structuredClone(profile);
 const provider=profile.find(row=>row.id==='llm-pi-ai')?.config?.providers?.['litellm-cluster'];
 if(!provider?.models?.some(model=>model.id===(selected?.config?.model??'deepseek-v4.1-flash')))throw Error('Managed model is missing');
 const result=structuredClone(profile);let ui=result.find(row=>row.id==='ui-settings-account');
 if(!ui){ui={id:'ui-settings-account'};result.push(ui);}
 ui.disabled=true;return result;
}
function main(home){
 if(!home)throw Error('Explicit state home required');
 const yaml=require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
 const file=path.join(home,'profiles/web/cordis.patch.yml');
 if(fs.lstatSync(file).isSymbolicLink())throw Error('Refuse profile symlink');
 const before=fs.readFileSync(file,'utf8'),parsed=yaml.parse(before),next=configure(parsed,process.env.DSH_MANAGED_TRANSPORT==='1'?'litellm-cluster':undefined);
 if(JSON.stringify(parsed)===JSON.stringify(next))return {changed:false,accountUIHidden:next.some(row=>row.id==='ui-settings-account'&&row.disabled===true)};
 const doc=yaml.parseDocument(before);let index=parsed.findIndex(row=>row.id==='ui-settings-account');
 if(index<0)doc.add({id:'ui-settings-account',disabled:true});else doc.setIn([index,'disabled'],true);
 const output=String(doc);if(JSON.stringify(yaml.parse(output))!==JSON.stringify(next))throw Error('Unexpected profile change');
 const hash=crypto.createHash('sha256').update(before).digest('hex');
 const backup=path.join(home,'.managed-signin-rollback',hash);fs.mkdirSync(backup,{recursive:true,mode:0o700});
 const retained=path.join(backup,'web-profile.yml');
 try{fs.writeFileSync(retained,before,{flag:'wx',mode:0o600});}catch(e){if(e.code!=='EEXIST'||fs.readFileSync(retained,'utf8')!==before)throw e;}
 const temp=file+'.signin-'+process.pid;fs.writeFileSync(temp,output,{flag:'wx',mode:0o600});
 if(fs.readFileSync(file,'utf8')!==before){fs.unlinkSync(temp);throw Error('Concurrent profile edit; original preserved');}
 fs.renameSync(temp,file);if(fs.readFileSync(file,'utf8')!==output)throw Error('Profile readback failed');
 return {changed:true,accountUIHidden:true,originalSHA256:hash,historyAndCredentialsTouched:false};
}
if(require.main===module)console.log(JSON.stringify(main(process.argv[2])));
module.exports={configure,main};
