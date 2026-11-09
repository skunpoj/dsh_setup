import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash,randomUUID} from 'node:crypto';
import {MODEL,lockSettings,lockProfile} from './managed_agent_policy.mjs';
const require=createRequire(import.meta.url);
const YAML=require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
const root=process.argv[2];
if(!['/state','/opt/dsh/seed/dsh-home'].includes(root))throw Error('Fixed profile root required');
const resolvedRoot=fs.realpathSync(root);
const p=JSON.parse(fs.readFileSync('/opt/dsh/config/managed-agents.json','utf8'));
if(p.model!==MODEL)throw Error('Operator model changed');
function replace(file,transform){
 if(!fs.existsSync(file))return;
 if(fs.lstatSync(file).isSymbolicLink()||!fs.realpathSync(file).startsWith(resolvedRoot+path.sep))throw Error('Unsafe profile path');
 const before=fs.readFileSync(file),after=Buffer.from(YAML.stringify(transform(YAML.parse(before.toString()))));
 if(before.equals(after))return;
 const st=fs.statSync(file);// the profile keeps its owner and mode: workspace pods read the seed as uid 10001
 const fingerprint=createHash('sha256').update(before).digest('hex');
 // The retained original lives in its own folder under the root, never beside the profile, so it is not read as profile content.
 const backupDir=path.join(root,'.managed-model-backups');fs.mkdirSync(backupDir,{recursive:true,mode:0o700});
 const backup=path.join(backupDir,path.relative(root,file).split(path.sep).join('__')+'.'+fingerprint.slice(0,12));
 try{fs.writeFileSync(backup,before,{flag:'wx',mode:0o600});}catch(e){if(e.code!=='EEXIST'||!fs.readFileSync(backup).equals(before))throw e;}
 if(!fs.readFileSync(file).equals(before))throw Error('Concurrent profile edit detected');
 const temp=file+'.managed-'+randomUUID();fs.writeFileSync(temp,after,{flag:'wx',mode:0o600});
 fs.chmodSync(temp,st.mode&0o777);try{fs.chownSync(temp,st.uid,st.gid);}catch(e){if(e.code!=='EPERM')throw e;}
 fs.renameSync(temp,file);
 const actual=YAML.parse(fs.readFileSync(file,'utf8'));const again=transform(actual);
 if(JSON.stringify(actual)!==JSON.stringify(again))throw Error('Managed profile readback differs');
}
for(const file of ['settings.yaml','.settings.yaml'])replace(path.join(root,file),x=>lockSettings(x||{},p.base_url));
for(const profile of ['web','tui','headless','sdk'])replace(path.join(root,'profiles',profile,'cordis.patch.yml'),x=>lockProfile(x||[],p.base_url));
