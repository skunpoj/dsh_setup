import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const shell=fs.readFileSync(path.join(root,'docs/LLM_SETUP_AND_TEST_RESULTS.html'),'utf8');
const head=shell.slice(0,shell.indexOf('<body>'));
for(const [name,title]of [['APP_URLS_AND_INGRESS','DSH — Application URLs and ingress'],['FLEXIBLE_DEPLOYMENT','DSH — Flexible deployment and inference endpoints'],['JUPYTERLAB','JupyterLab in a private DSH environment'],['MANAGED_CLIENT_SUPPORT','DSH managed coding clients'],['INFERENCE_OPTIMIZATION_EXPERIENCE','DSH inference optimization — decisions, trials and lessons'],['MODEL_UPDATE_1017','DeepSeek-V4.1-Flash-1017 — setup and qualification'],['ADMIN_USAGE_TELEMETRY','DSH administrator — usage and storage']]){
 const source=fs.readFileSync(path.join(root,'docs',name+'.md'),'utf8');
 let body=marked.parse(source).replace(/href="(?!https?:|#)([^"\s]+)"/g,(_,ref)=>ref.endsWith('.html')?`href="${ref}"`:`href="https://github.com/skunpoj/dsh_setup/blob/main/docs/${ref}"`);
 body=body.replace(/<img src="(images\/platform\/[^"\s]+)" alt="([^"]*)">/g,(_,image,alt)=>{
  const file=path.resolve(root,'docs',image);if(!file.startsWith(path.join(root,'docs/images/platform')+path.sep))throw Error('Unscoped image');
  return `<img style="max-width:100%;height:auto" src="data:image/png;base64,${fs.readFileSync(file).toString('base64')}" alt="${alt}">`;
 });
 let reportHead=head,tail='</body></html>';
 if(name==='FLEXIBLE_DEPLOYMENT'){
  const architecture=fs.readFileSync(path.join(root,'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html'),'utf8');reportHead=architecture.slice(0,architecture.indexOf('<body>'));tail=architecture.slice(architecture.indexOf('</main>')+7);
  body=body.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,(_,code)=>`<section class="mermaid-wrapper"><div class="mermaid-header"><span>Deployment architecture</span><div class="mermaid-toolbar"><button onclick="panZoomMermaid(this,'zoomIn')" aria-label="Zoom in">+</button><button onclick="panZoomMermaid(this,'zoomOut')" aria-label="Zoom out">−</button><button onclick="panZoomMermaid(this,'reset')">Reset</button><button onclick="panZoomMermaid(this,'fullscreen')">Fullscreen</button><button onclick="exportMermaid(this,'svg')">Save SVG</button><button onclick="exportMermaid(this,'png')">Save PNG</button></div></div><div class="mermaid-container"><div class="mermaid" data-raw-code="${code.replaceAll('"','&quot;')}">${code}</div></div></section>`);
 }
 const html=reportHead.replace(/<title>.*?<\/title>/,`<title>${title}</title>`)+'<body><main>'+body+'</main>'+tail;
 fs.writeFileSync(path.join(root,'docs',name+'.html'),html.replaceAll('\r\n','\n'));
 console.log(JSON.stringify({report:name+'.html',bytes:Buffer.byteLength(html)}));
}
