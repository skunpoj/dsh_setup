import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..'),docs=path.join(root,'docs');
const modules=process.env.DSH_DOC_NODE_MODULES;
if(!modules)throw Error('Set DSH_DOC_NODE_MODULES to the installed documentation dependency directory');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const name='USER_CREDENTIAL_MANAGEMENT';
const source=fs.readFileSync(path.join(docs,name+'.md'),'utf8');
const head='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>User-managed credentials — DSH</title><style>body{font:17px/1.65 system-ui;color:#17324d;background:#f3f6f9;margin:0}main{max-width:1050px;margin:auto;padding:32px;background:white}h1,h2,h3{color:#003366}a{color:#005a9c}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd8e1;padding:10px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f9;padding:16px}.flow{display:flex;flex-wrap:wrap;gap:10px}.flow span{padding:14px;border:1px solid #8ca8c0;border-radius:8px;background:#eef4fa}video{max-width:100%}@media(max-width:600px){main{padding:16px}table{display:block;overflow:auto}}</style></head>';
let content=marked.parse(source);
const video='data:video/mp4;base64,'+fs.readFileSync(path.join(docs,'videos/credential-management-fola.mp4')).toString('base64');
const captions='data:text/vtt;base64,'+fs.readFileSync(path.join(docs,'videos/credential-management-fola.vtt')).toString('base64');
content=content.replace(/<pre><code class="language-mermaid">[\s\S]*?<\/code><\/pre>/g,'<div class="flow" role="img" aria-label="User settings and harness aliases enter the credential broker, which checks policy and approval, uses the encrypted vault, calls a fixed connector, filters results and writes metadata-only audit"><span>User settings / harness alias</span><span>→ Broker identity and policy</span><span>→ Bound approval</span><span>→ Encrypted vault</span><span>→ Fixed connector</span><span>→ Filtered result + audit</span></div>');
fs.writeFileSync(path.join(docs,name+'.html'),head+'<body><main><p><a href="DSH_USER_MANUAL.html">User manual</a></p>'+content+'<h2>Video supplement</h2><p>English Fola-narrated lesson: 106 seconds with aligned captions. This explains the implemented API-token/PAT controls.</p><video controls preload="metadata" style="width:100%" src="'+video+'"><track kind="captions" src="'+captions+'" srclang="en" label="English" default></video><p><a download="credential-management-fola.mp4" href="'+video+'">Download video</a> · <a download="credential-management-fola.vtt" href="'+captions+'">Captions</a></p></main>'+'</body></html>');
const paragraph='User-managed credentials: users enter secrets through a dedicated settings form, while the harness receives only aliases. A separate broker checks the owner, workspace, environment, destination and action before using the secret. Consequential actions require bound approval; audit logs exclude secret values. Implemented for configured API-token/PAT connectors; OAuth consent and Kerberos acquisition are not included. Read the <a href="USER_CREDENTIAL_MANAGEMENT.html">credential management guide and Fola video</a>.';
const targets=['DSH_USER_MANUAL','DSH_PLATFORM_GUIDE','DSH_SECURITY_ENVIRONMENT_AND_FEATURES','DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT','MANAGED_CLIENT_SUPPORT','THREE_RISK_CONTROLS','SECURITY'];
for(const target of targets){
  const md=path.join(docs,target+'.md');
  if(!fs.existsSync(md))continue;
  let text=fs.readFileSync(md,'utf8');
  const marker='<!-- credential-management-design -->';
  const section=marker+'\n\n## User-managed credentials\n\n'+paragraph.replace(/<a href="([^"]+)">([^<]+)<\/a>/g,'[$2]($1)')+'\n';
  if(text.includes(marker))text=text.slice(0,text.indexOf(marker)).trimEnd()+'\n\n'+section;else text+='\n'+section;fs.writeFileSync(md,text);
  const html=path.join(docs,target+'.html');
  if(fs.existsSync(html)){let h=fs.readFileSync(html,'utf8');if(h.includes(marker))h=h.replace(/<!-- credential-management-design -->[\s\S]*?<\/section>/,marker+'<section><h2>User-managed credentials</h2><p>'+paragraph+'</p></section>');else h=h.replace('</main>',marker+'<section><h2>User-managed credentials</h2><p>'+paragraph+'</p></section></main>');fs.writeFileSync(html,h);}
}
const readme=path.join(root,'README.md');let r=fs.readFileSync(readme,'utf8');
r=r.replace('The broker and settings UI are planned, not deployed.','Implemented for configured API-token/PAT connectors; OAuth consent and Kerberos acquisition are not included.');fs.writeFileSync(readme,r);if(!r.includes('docs/USER_CREDENTIAL_MANAGEMENT.html'))fs.writeFileSync(readme,r+'\n## User-managed credentials\n\n[Credential broker design and video supplement](docs/USER_CREDENTIAL_MANAGEMENT.html): aliases instead of secrets in chat; owner/workspace/environment/action policy; lifecycle and audit controls. The broker and settings UI are planned, not deployed.\n');
console.log('Credential guide and related source/HTML references updated');
