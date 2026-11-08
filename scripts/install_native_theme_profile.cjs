'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const NAME='@dsh-ext/custom-theme',VERSION='0.4.3',CLIENT_SHA='02922e773805c7ee2f5eb57f6edfed352f5bd1d394ccda8c0970b2f4eb1b790b';
// Internal migration only: releases up to 0.3.3 were installed under this earlier package name. Omit this block when porting to a public repository.
const LEGACY_NAME='@bot/dsh-theme';
// Earlier qualified releases that may sit in a profile under the earlier package name. Only these exact bytes are migrated; the old copy is kept.
const LEGACY_PRIOR={'0.1.0':'5a959c0dee3b3630a73e35db68a9695e75bb9bb490e58d90fb7a234147bbce4a','0.2.0':'e5e3c6368bf76ec415537292fc656857a34704daa191cc823c4ba01c710181a0','0.3.0':'97a18c372139b9c163c3509ddc589add713403eb212886939c8d3e1cb01d3d4d','0.3.1':'64b6a4af701748a3d0eb840ad0ad18c359d7167b2195b64f536a6860c161a01f','0.3.2':'c7e2f2c7ce8ca4fda572d2a4c54bdff3be78612d6d5c790959d816436fdbedfb','0.3.3':'df01fcebfb8f7b92b346445420a384a70066ca55b1597fcb98597ff53b4d0da6'};
const PRIOR={'0.3.4':'6058510668b546add781698566086e1d685a66983460a097450fd146bbe88c07','0.3.5':'561f7cf60bb4f916eb66b914849a66fb8ea27a12031f566e7819a1fa1761ada7','0.4.1':'ebcb0090971ff99fd9de6d5bd129f54cb48c7f7ed762acf378782fe74c23107d','0.4.2':'1a6a8486ebb6081dfea08a84d3957ac58bf364ba308bcd1f64d6243520e26462'};
const FILES=['package.json','cordis.patch.yml','README.md','lib/index.js','lib/client.js','src/restore-native-gateway.mjs'];
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
function noLink(p){try{if(fs.lstatSync(p).isSymbolicLink())throw Error('Refuse symlink: '+p);}catch(e){if(e.code!=='ENOENT')throw e;}}
function install(stateHome,packageSource){
 if(!stateHome||!packageSource||!path.isAbsolute(stateHome)||!path.isAbsolute(packageSource))throw Error('Explicit absolute state and package paths required');
 const home=fs.realpathSync(stateHome),source=fs.realpathSync(packageSource);
 if(home===source||source.startsWith(home+path.sep))throw Error('Package source must be outside state home');
 for(const rel of FILES){let cursor=source;for(const part of rel.split('/')){cursor=path.join(cursor,part);noLink(cursor);}if(!fs.statSync(path.join(source,rel)).isFile())throw Error('Package member is not a file');}
 const manifest=JSON.parse(fs.readFileSync(path.join(source,'package.json'),'utf8'));
 if(manifest.name!==NAME||manifest.version!==VERSION||manifest.dsh?.bundle?.patch!=='./cordis.patch.yml')throw Error('Unexpected package identity');
 if(sha(fs.readFileSync(path.join(source,'lib/client.js')))!==CLIENT_SHA)throw Error('Unqualified client bundle');
 const profile=path.join(home,'profiles','web'),packageFile=path.join(profile,'package.json'),dest=path.join(profile,'node_modules','@dsh-ext','custom-theme'),legacyDest=path.join(profile,'node_modules','@bot','dsh-theme');
 for(const rel of ['profiles','profiles/web','profiles/web/package.json','profiles/web/node_modules','profiles/web/node_modules/@bot','profiles/web/node_modules/@bot/dsh-theme','profiles/web/node_modules/@dsh-ext','profiles/web/node_modules/@dsh-ext/custom-theme'])noLink(path.join(home,rel));
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
 const profileChanged=!bundles.includes(NAME)||bundles.includes(LEGACY_NAME);
 next.dsh.profile.bundles=profileChanged?[...bundles.map(x=>x===LEGACY_NAME?NAME:x).filter((x,i,a)=>a.indexOf(x)===i),...(bundles.includes(NAME)||bundles.includes(LEGACY_NAME)?[]:[NAME])]:bundles;
 let packageInstalled=false,backup=null;
 let upgradedFrom=null;
 // Migration from the earlier package name: only an exact qualified copy is moved aside (kept for rollback); anything else needs review.
 if(fs.existsSync(legacyDest)){
  let old2=null;try{old2=JSON.parse(fs.readFileSync(path.join(legacyDest,'package.json'),'utf8'));}catch{}
  const legacySha=old2&&old2.name===LEGACY_NAME&&Object.hasOwn(LEGACY_PRIOR,old2.version)?LEGACY_PRIOR[old2.version]:null;
  if(!legacySha||!fs.existsSync(path.join(legacyDest,'lib/client.js'))||sha(fs.readFileSync(path.join(legacyDest,'lib/client.js')))!==legacySha)throw Error('Existing package under the earlier name differs; explicit upgrade review required');
  const keepLegacy=path.join(home,'.native-theme-rollback','package-'+old2.version+'-'+legacySha.slice(0,12));
  noLink(path.join(home,'.native-theme-rollback'));noLink(keepLegacy);fs.mkdirSync(path.dirname(keepLegacy),{recursive:true,mode:0o700});
  if(fs.existsSync(keepLegacy))fs.rmSync(legacyDest,{recursive:true,force:true});else fs.renameSync(legacyDest,keepLegacy);
  upgradedFrom=old2.version;packageInstalled=true;
 }
 const stageCopy=()=>{const stage=fs.mkdtempSync(path.join(path.dirname(dest),'.theme-stage-'));
  for(const rel of FILES){const target=path.join(stage,rel);fs.mkdirSync(path.dirname(target),{recursive:true,mode:0o700});fs.copyFileSync(path.join(source,rel),target,fs.constants.COPYFILE_EXCL);}
  return stage;};
 if(fs.existsSync(dest)){
  const same=FILES.every(rel=>{let cursor=dest;for(const part of rel.split('/')){cursor=path.join(cursor,part);noLink(cursor);}return fs.existsSync(path.join(dest,rel))&&fs.readFileSync(path.join(dest,rel)).equals(fs.readFileSync(path.join(source,rel)));});
  if(!same){
   let prior=null;try{prior=JSON.parse(fs.readFileSync(path.join(dest,'package.json'),'utf8'));}catch{}
   const priorSha=prior&&prior.name===NAME&&Object.hasOwn(PRIOR,prior.version)?PRIOR[prior.version]:null;
   if(!priorSha||!fs.existsSync(path.join(dest,'lib/client.js'))||sha(fs.readFileSync(path.join(dest,'lib/client.js')))!==priorSha)throw Error('Existing managed package differs; explicit upgrade review required');
   // Qualified upgrade: the new copy is staged first, the old one moves to the rollback folder, then the new one takes its place.
   const stage=stageCopy(),keep=path.join(home,'.native-theme-rollback','package-'+prior.version+'-'+priorSha.slice(0,12));
   noLink(path.join(home,'.native-theme-rollback'));noLink(keep);fs.mkdirSync(path.dirname(keep),{recursive:true,mode:0o700});
   if(fs.existsSync(keep))fs.rmSync(dest,{recursive:true,force:true});else fs.renameSync(dest,keep);
   fs.renameSync(stage,dest);packageInstalled=true;upgradedFrom=prior.version;
  }
 }else{
  fs.mkdirSync(path.dirname(dest),{recursive:true,mode:0o700});
  fs.renameSync(stageCopy(),dest);packageInstalled=true;
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
 return {changed:profileChanged||packageInstalled,profileChanged,packageInstalled,packageName:NAME,packageVersion:manifest.version,upgradedFrom,clientSHA256:CLIENT_SHA,backup,profileSHA256:sha(fs.readFileSync(packageFile)),historyOrCredentialsRead:false,restartRequired:profileChanged||packageInstalled};
}
if(require.main===module)console.log(JSON.stringify(install(process.argv[2],process.argv[3])));
module.exports={install,FILES,CLIENT_SHA,PRIOR,LEGACY_PRIOR};
