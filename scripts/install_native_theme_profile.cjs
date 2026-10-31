'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const NAME='dsh-theme-custom-light',CLIENT_SHA='7002d9bebced3037c7d38f4ef342e5e6ffccbfc874bed8086b06eccd1480e88b';
const FILES=['package.json','cordis.patch.yml','dsh.plugin.json','README.md','LICENSE','lib/index.js','lib/client.js'];
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
function noLink(p){try{if(fs.lstatSync(p).isSymbolicLink())throw Error('Refuse symlink: '+p);}catch(e){if(e.code!=='ENOENT')throw e;}}
function install(stateHome,packageSource){
 if(!stateHome||!packageSource||!path.isAbsolute(stateHome)||!path.isAbsolute(packageSource))throw Error('Explicit absolute state and package paths required');
 const home=fs.realpathSync(stateHome),source=fs.realpathSync(packageSource);
 if(home===source||source.startsWith(home+path.sep))throw Error('Package source must be outside state home');
 for(const rel of FILES){let cursor=source;for(const part of rel.split('/')){cursor=path.join(cursor,part);noLink(cursor);}if(!fs.statSync(path.join(source,rel)).isFile())throw Error('Package member is not a file');}
 const manifest=JSON.parse(fs.readFileSync(path.join(source,'package.json'),'utf8'));
 if(manifest.name!==NAME||manifest.version!=='0.1.0'||manifest.dsh?.bundle?.patch!=='./cordis.patch.yml')throw Error('Unexpected package identity');
 if(sha(fs.readFileSync(path.join(source,'lib/client.js')))!==CLIENT_SHA)throw Error('Unqualified client bundle');
 const profile=path.join(home,'profiles','web'),packageFile=path.join(profile,'package.json'),dest=path.join(profile,'node_modules','dsh-theme-custom-light');
 for(const rel of ['profiles','profiles/web','profiles/web/package.json','profiles/web/node_modules','profiles/web/node_modules/dsh-theme-custom-light'])noLink(path.join(home,rel));
 const old=fs.existsSync(packageFile)?fs.readFileSync(packageFile):null;
 const original=old?JSON.parse(old.toString('utf8')):{name:'dsh-managed-web-profile',version:'1.0.0',private:true};
 if(!original||typeof original!=='object'||Array.isArray(original))throw Error('Expected profile manifest object');
 const next=structuredClone(original);
 if(next.dsh!==undefined&&(next.dsh===null||typeof next.dsh!=='object'||Array.isArray(next.dsh)))throw Error('Unexpected dsh profile configuration');
 next.dsh??={};
 if(next.dsh.profile!==undefined&&(next.dsh.profile===null||typeof next.dsh.profile!=='object'||Array.isArray(next.dsh.profile)))throw Error('Unexpected profile configuration');
 next.dsh.profile??={};
 const bundles=next.dsh.profile.bundles??[];
 if(!Array.isArray(bundles)||bundles.some(x=>typeof x!=='string')||new Set(bundles).size!==bundles.length)throw Error('Expected unique bundle names');
 const profileChanged=!bundles.includes(NAME);
 next.dsh.profile.bundles=profileChanged?[...bundles,NAME]:bundles;
 let packageInstalled=false,backup=null;
 if(fs.existsSync(dest)){
  for(const rel of FILES){let cursor=dest;for(const part of rel.split('/')){cursor=path.join(cursor,part);noLink(cursor);}if(!fs.existsSync(path.join(dest,rel))||!fs.readFileSync(path.join(dest,rel)).equals(fs.readFileSync(path.join(source,rel))))throw Error('Existing managed package differs; explicit upgrade review required');}
 }else{
  fs.mkdirSync(path.dirname(dest),{recursive:true,mode:0o700});
  const stage=fs.mkdtempSync(path.join(path.dirname(dest),'.theme-stage-'));
  for(const rel of FILES){const target=path.join(stage,rel);fs.mkdirSync(path.dirname(target),{recursive:true,mode:0o700});fs.copyFileSync(path.join(source,rel),target,fs.constants.COPYFILE_EXCL);}
  fs.renameSync(stage,dest);packageInstalled=true;
 }
 if(profileChanged){
  const beforeHash=old?sha(old):'absent',backupDir=path.join(home,'.native-theme-rollback',beforeHash);
  noLink(path.join(home,'.native-theme-rollback'));noLink(backupDir);
  fs.mkdirSync(backupDir,{recursive:true,mode:0o700});
  if(old){backup=path.join(backupDir,'web-package.json');noLink(backup);try{fs.writeFileSync(backup,old,{flag:'wx',mode:0o600});}catch(e){if(e.code!=='EEXIST'||!fs.readFileSync(backup).equals(old))throw e;}}
  else{const absent=path.join(backupDir,'package-was-absent');noLink(absent);if(!fs.existsSync(absent))fs.writeFileSync(absent,'true\n',{flag:'wx',mode:0o600});backup=absent;}
  const temp=path.join(profile,'.theme-package-'+crypto.randomBytes(8).toString('hex')+'.json');
  const text=JSON.stringify(next,null,2)+'\n';fs.writeFileSync(temp,text,{flag:'wx',mode:0o600});
  const current=fs.existsSync(packageFile)?fs.readFileSync(packageFile):null;
  if((old===null)!==(current===null)||(old&&(!current||!current.equals(old)))){fs.unlinkSync(temp);throw Error('Concurrent profile change; preserved current manifest');}
  fs.renameSync(temp,packageFile);
  if(!fs.readFileSync(packageFile).equals(Buffer.from(text)))throw Error('Profile manifest readback mismatch');
 }
 return {changed:profileChanged||packageInstalled,profileChanged,packageInstalled,packageName:NAME,packageVersion:manifest.version,clientSHA256:CLIENT_SHA,backup,profileSHA256:sha(fs.readFileSync(packageFile)),historyOrCredentialsRead:false,restartRequired:profileChanged||packageInstalled};
}
if(require.main===module)console.log(JSON.stringify(install(process.argv[2],process.argv[3])));
module.exports={install,FILES,CLIENT_SHA};
