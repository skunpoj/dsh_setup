import fs from 'node:fs';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const root=path.dirname(fileURLToPath(import.meta.url));
const pins=PINS;
export default function managedClientActivation(ctx, config){
 try {
  for(const [name,hash]of Object.entries({...pins,'startup.mjs':config?.selfSha256})){
   const p=path.join(root,name),s=fs.lstatSync(p);
   if(!s.isFile()||s.isSymbolicLink()||s.uid!==process.getuid()||s.nlink!==1||s.size>1048576)throw Error('Invalid managed boot asset');
   if(crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')!==hash)throw Error('Boot asset fingerprint differs');
  }
  const result=spawnSync('/usr/bin/python3',[path.join(root,'reactivate.py')],{timeout:15000,maxBuffer:32768,stdio:'pipe'});
  if(result.error||result.status!==0)throw Error('Activation helper did not finish');
 }catch{
  // Optional launch compatibility must never stop DSH or change other plugins.
  try{const base=path.resolve(root,'../..');const s=fs.lstatSync(base);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==process.getuid())throw Error();const tmp=path.join(base,'.boot-failure-'+process.pid+'-'+Date.now());fs.writeFileSync(tmp,JSON.stringify({ok:false,error_type:'BootValidationOrExecutionError',native_pid:process.pid,observed_ms:Date.now(),model_calls:0}),{flag:'wx',mode:0o600});fs.renameSync(tmp,path.join(base,'boot-status.json'));}catch{}
  console.warn('Managed client activation was not applied; inspect private boot status.');
 }
}
