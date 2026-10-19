import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const args=process.argv.slice(2);const option=name=>{const i=args.indexOf(name);return i<0?null:args[i+1];};
const out=path.resolve(option('--output') || path.join(root,'docs/DSH_PLATFORM_GUIDE.html'));
const privatePath=option('--private-inventory');
if(privatePath&&out===path.join(root,'docs/DSH_PLATFORM_GUIDE.html'))throw Error('Private inventory must never overwrite the public portable guide');
const snapshot=JSON.parse(fs.readFileSync(path.join(root,'docs/context-evidence/platform-deployment-inventory-20261017.json'),'utf8'));
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
let source=fs.readFileSync(path.join(root,'docs/DSH_PLATFORM_GUIDE.md'),'utf8').replace(/^# [^\r\n]*(?:\r?\n|$)/,'');
const summary=`Inventory observed at **${snapshot.observedAtUTC}**: **${snapshot.deploymentsInMainNamespace} Deployments** in the DSH/inference namespace — **${snapshot.activeDeployments} active and ${snapshot.scaledToZeroDeployments} scaled to zero**. The active application layer includes **20 main runtimes (10 No Internet + 10 Internet)** and **2 additional owner-only runtimes**, plus shared supporting workloads. A separate CPU Ollama workload is also deployed.`;
const table='| Workload / private runtime role | Desired | Ready | Observed state |\n|---|---:|---:|---|\n'+snapshot.workloads.map(x=>`| ${x.workload} | ${x.desired} | ${x.ready} | ${x.state} |`).join('\n');
let details='Access examples: `https://dsh.example.com`, its `/admin`, `/terminal` and `/proxy/<approved-port>/` routes; separate `https://dsh2.example.com` and `https://dsh3.example.com` instances. These example domains are not live service addresses.';
if(privatePath){
 const site=JSON.parse(fs.readFileSync(privatePath,'utf8'));
 const main=site.ingresses.flatMap(i=>i.hosts).find(h=>h.startsWith('dsh.'));
 if(!main || !/^[a-zA-Z0-9.-]+$/.test(main))throw Error('Main DSH access hostname missing');
 details=`Open [DSH](https://${main}) and choose your working environment. Administrators use [Admin overview](https://${main}/admin); the authenticated [web terminal](https://${main}/terminal) opens inside your private environment.`;
}
source=source.replace('DEPLOYMENT_SUMMARY',summary).replace('PUBLIC_DEPLOYMENT_TABLE',table).replace('SITE_DEPLOYMENT_DETAILS',details);
let append=marked.parse(source);
let idx=0;
append=append.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,(_,code)=>`<section class="mermaid-wrapper"><div class="mermaid-header"><span>Architecture ${++idx}</span><div class="mermaid-toolbar"><button onclick="panZoomMermaid(this,'zoomIn')" aria-label="Zoom in">+</button><button onclick="panZoomMermaid(this,'zoomOut')" aria-label="Zoom out">−</button><button onclick="panZoomMermaid(this,'reset')">Reset</button><button onclick="panZoomMermaid(this,'fullscreen')">Fullscreen</button><button onclick="exportMermaid(this,'svg')">Save SVG</button><button onclick="exportMermaid(this,'png')">Save PNG</button><button onclick="exportMermaid(this,'copy')">Copy code</button></div></div><div class="mermaid-container"><div class="mermaid" data-raw-code="${code.replaceAll('"','&quot;')}">${code}</div></div></section>`);
append=append.replace(/<img src="(images\/platform\/[^"\s]+)" alt="([^"]*)">/g,(_,name,alt)=>{
 const p=path.resolve(root,'docs',name);if(!p.startsWith(path.join(root,'docs/images/platform')+path.sep)||!fs.existsSync(p))throw Error('Missing or unscoped screenshot '+name);
 return `<img src="data:image/png;base64,${fs.readFileSync(p).toString('base64')}" alt="${alt}" data-source="${esc(name)}">`;
});
let shell=fs.readFileSync(path.join(root,'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html'),'utf8');

const h1='<p class="meta">Enterprise AI Platform</p><h1>DeepSeek Harness (DSH)</h1><p>Enterprise Agentic Coding &amp; Knowledge Gateway</p>';
const intro=`<p>This guide explains DSH’s security controls, features, deployment architecture and practical usage, followed by LLM/GPU setup instructions.</p><p class="meta">Deployment inventory: ${esc(snapshot.observedAtUTC)}.</p>`;
let content=append;let count=0;const toc=[];
content=content.replace(/<h2(?:\s[^>]*)?>([\s\S]*?)<\/h2>/g,(_,title)=>{const id='guide-section-'+(++count);toc.push(`<a href="#${id}">${title}</a>`);return `<h2 id="${id}">${title}</h2>`;});
const head=shell.slice(0,shell.indexOf('<body>')).replace(/<title>.*?<\/title>/,'<title>DSH Platform Guide — Features, Deployments, Usage and LLM/GPU Setup</title>').replace('</style>',`img{display:block;max-width:100%;height:auto;margin:20px auto;border:1px solid #cbd5e1;border-radius:10px} main>p:has(img){margin-top:24px}.meta{overflow-wrap:anywhere}table{table-layout:fixed}h2{scroll-margin-top:20px}@media print{img{max-height:220mm;object-fit:contain}.mermaid-wrapper{break-inside:avoid}} </style>`);
const scripts=shell.slice(shell.indexOf('</main>')+7);
fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,(head+'<body><main>'+h1+intro+`<nav aria-label="Contents">${toc.join('')}</nav>`+content+'</main>'+scripts).replace(/\r\n/g,'\n'));
console.log(JSON.stringify({output:out,sections:count,diagrams:idx,embeddedScreenshots:(append.match(/data:image\/png/g)||[]).length,privateSiteEdition:Boolean(privatePath)}));
