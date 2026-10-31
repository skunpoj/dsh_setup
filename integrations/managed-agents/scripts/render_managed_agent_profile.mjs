import fs from 'node:fs';
import {MODEL,lockProfile} from './managed_agent_policy.mjs';
const file='/opt/dsh/config/managed-agents.json';
const p=JSON.parse(fs.readFileSync(file,'utf8'));
if(p.model!==MODEL)throw Error('Operator model changed');
if(process.env.DSH_LITELLM_NAMESPACE){const n=process.env.DSH_LITELLM_NAMESPACE;if(!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(n))throw Error('Invalid deployment namespace');p.base_url='http://litellm.'+n+'.svc.cluster.local:4000/v1';}
const profile=lockProfile([],p.base_url);
fs.writeFileSync(file,JSON.stringify(p,null,2)+'\n',{mode:0o644});
fs.writeFileSync('/opt/dsh/config/managed-llm.patch.yml',JSON.stringify(profile,null,2)+'\n',{mode:0o644});
