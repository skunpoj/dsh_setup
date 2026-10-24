#!/usr/bin/env node
'use strict';
// Runtime routing identity authenticates broker USE only; provider secrets are never returned.
const fs=require('node:fs'),https=require('node:https'),path=require('node:path');
async function main(){
 const directory=process.env.DSH_CREDENTIAL_TOOLS_DIR||'/state/credential-tools';
 const config=JSON.parse(fs.readFileSync(path.join(directory,'client.json'),'utf8'));
 const action=process.argv[2]||'list';if(!['list','profiles','execute','result'].includes(action))throw Error('Use list, profiles, execute or result');
 const input=process.argv[3]?JSON.parse(process.argv[3]):{};
 if(action==='execute'&&!input.workspace)input.workspace=path.basename(fs.realpathSync(process.cwd()));
 const body=Buffer.from(JSON.stringify({action,input}));
 const environment=process.env.DSH_ENVIRONMENT;
 if(!config.runtimeTokenFile&&!['secure','internet'].includes(environment))throw Error('Private environment identity unavailable');
 const token=fs.readFileSync(config.runtimeTokenFile||path.join('/runtime-tokens',environment),'utf8').trim();
 const r=await new Promise((resolve,reject)=>{const q=https.request(new URL('/v1/connections',config.url),{method:'POST',ca:fs.readFileSync(path.join(directory,'ca.pem')),headers:{Authorization:'Bearer '+token,'Content-Type':'application/json','Content-Length':body.length}},r=>{const chunks=[];let n=0;r.on('data',b=>{n+=b.length;if(n>65536)r.destroy(Error('Bounded response exceeded'));else chunks.push(b);});r.on('error',reject);r.on('end',()=>{if(r.statusCode!==200)return reject(Error('Connection operation denied or unavailable'));resolve(Buffer.concat(chunks).toString());});});q.setTimeout(20000,()=>q.destroy(Error('Connection timeout')));q.on('error',reject);q.end(body);});
 console.log(r);
}
main().catch(()=>{console.error('Connection operation denied or unavailable. Manage connections in DSH → Credentials.');process.exitCode=1;});
