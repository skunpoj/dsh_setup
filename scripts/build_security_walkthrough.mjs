import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root = path.resolve(import.meta.dirname, '..');
const moduleRoot = process.env.DSH_DOC_NODE_MODULES || 'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { marked } = await import(pathToFileURL(path.join(moduleRoot, 'marked/lib/marked.esm.js')));
const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const source = fs.readFileSync(path.join(root, 'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md'), 'utf8');
let html = marked.parse(source);
const heading = html.match(/<h1>[\s\S]*?<\/h1>/)?.[0] || '';
html = html.replace(heading, '');
let diagram = 0;
html = html.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g, (_, code) => {
  diagram++;
  return `<section class="mermaid-wrapper"><div class="mermaid-header"><span>Architecture ${diagram}</span><div class="mermaid-toolbar">
  <button onclick="panZoomMermaid(this,'zoomIn')" aria-label="Zoom in">+</button>
  <button onclick="panZoomMermaid(this,'zoomOut')" aria-label="Zoom out">−</button>
  <button onclick="panZoomMermaid(this,'reset')">Reset</button>
  <button onclick="panZoomMermaid(this,'fullscreen')">Fullscreen</button>
  <button onclick="exportMermaid(this,'svg')">Save SVG</button>
  <button onclick="exportMermaid(this,'png')">Save PNG</button>
  <button onclick="exportMermaid(this,'copy')">Copy code</button>
  </div></div><div class="mermaid-container"><div class="mermaid" data-raw-code="${code.replaceAll('"','&quot;')}">${code}</div></div></section>`;
});
const toc = [];
html = html.replace(/<h2>(.*?)<\/h2>/g, (_, title) => { const id = `section-${toc.length+1}`; toc.push(`<a href="#${id}">${title}</a>`); return `<h2 id="${id}">${title}</h2>`; });
const evidence = [
  ['design-consistency-live-20261016.json','Local routing, audit and network checks'],
  ['remote-spark-recheck-20261016.json','Authenticated remote-worker egress retest'],
  ['package-workflow-live-20261016.json','Controlled offline package transfer'],
  ['legacy-owner-restoration-live-20261016.json','Owner access and peer denial'],
  ['owner-admin-terminal-live-20261016.json','Authenticated terminal execution'],
  ['admin-private-persistence-20261016.json','Private-state restart persistence'],
  ['legacy-auth-content-review-20261016.json','Legacy-instance access review']
];
html = html.replace(/href="(?!https?:|#)([^"\s]+)"/g, (_, name) => `href="https://github.com/skunpoj/dsh_setup/blob/main/docs/${name}"`);
const guide = marked.parse(fs.readFileSync(path.join(root,'docs/LLM_SETUP_AND_TEST_RESULTS.md'),'utf8')).replace(/href="(?!https?:|#)([^"\s]+)"/g, (_, name) => `href="https://github.com/skunpoj/dsh_setup/blob/main/docs/${name}"`);
html += `<details id="embedded-llm-guide"><summary>LLM setup guide and verified test results</summary>${guide}</details>`;
const readmeHtml = marked.parse(fs.readFileSync(path.join(root,'README.md'),'utf8')).replace(/href="(?!https?:|#)([^"\s]+)"/g, (_, name) => `href="https://github.com/skunpoj/dsh_setup/blob/main/${name}"`);
html += `<details id="embedded-readme"><summary>Deployment README</summary>${readmeHtml}</details>`;
html += '<details id="verification-records"><summary>Verification records — supporting technical references</summary><p>Raw logs and historical migration records stay in separate files. The risk-control narrative above is the primary report.</p><ul>';
for (const [name,label] of evidence) html += `<li><a href="https://github.com/skunpoj/dsh_setup/blob/main/docs/context-evidence/${name}">${escape(label)}</a></li>`;
html += '</ul></details>';
const assets = ['mermaid-10.8.0.min.js','svg-pan-zoom-3.6.1.min.js','smpeda-diagram-controls.js'].map(name => fs.readFileSync(path.join(root,'docs/assets',name),'utf8').replace(/<\/script/gi,'<\\/script'));
const result = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DSH Pilot — Controlling Data Leakage, Source Damage and Result Exposure</title><style>
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf2f7;color:#193047;font:16px/1.75 'Segoe UI','Leelawadee UI',Tahoma,sans-serif}main{max-width:1280px;margin:28px auto;background:#fff;padding:44px 50px;border-radius:14px}h1{font-size:32px;line-height:1.3;color:#075985}h2{font-size:24px;margin-top:48px;border-top:1px solid #d3e0eb;padding-top:20px;color:#075985}h3{margin-top:30px}a{color:#0369a1}nav{padding:18px 24px;background:#eff6ff;border-radius:10px;columns:2}nav a{display:block;margin:6px 0;break-inside:avoid}p,li{margin-bottom:12px}table{border-collapse:collapse;width:100%;font-size:14px;margin:22px 0}th,td{padding:12px;border:1px solid #cedce8;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:#e6f1f8}tr:nth-child(even){background:#f8fafc}code{font:13px Consolas,monospace;overflow-wrap:anywhere;background:#edf2f7;padding:2px 4px}pre{padding:18px;background:#f1f5f9;overflow:auto;white-space:pre-wrap;font:13px/1.6 Consolas,monospace}details{border:1px solid #cddce8;padding:14px;margin:12px 0}summary{cursor:pointer;font-weight:600}.mermaid-wrapper{margin:24px 0;background:#0b0f19;border:1px solid #334155;border-radius:10px;overflow:hidden}.mermaid-header{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;padding:12px 16px;background:#1e293b;color:#f8fafc}.mermaid-toolbar{display:flex;flex-wrap:wrap;gap:6px}.mermaid-toolbar button{border:1px solid #64748b;border-radius:5px;background:#0f172a;color:#e2e8f0;padding:7px 10px;cursor:pointer}.mermaid-toolbar button:hover{background:#334155}.mermaid-container{padding:18px;height:590px;overflow:hidden;position:relative}.mermaid-container .mermaid{width:100%;height:100%}.mermaid-container svg{width:100%;height:100%;max-width:none!important}.mermaid-wrapper:fullscreen{width:100vw;height:100vh;border-radius:0}.mermaid-wrapper:fullscreen .mermaid-container{height:calc(100vh - 80px)}.status{background:#fff7df;border-left:5px solid #d69e2e;padding:14px 20px}.meta{color:#52687a;font-size:13px}@media(max-width:760px){main{margin:0;padding:24px 16px}nav{columns:1}table{font-size:12px}th,td{padding:7px}.mermaid-container{height:480px}}@media print{main{margin:0;padding:0}body{background:#fff}nav,.mermaid-toolbar{display:none}h2{break-after:avoid}tr,.mermaid-wrapper{break-inside:avoid}.mermaid-container{height:480px}details>pre{display:block}}
</style></head><body><main>${heading}<div class="status"><strong>Three controls govern this pilot: prevent external leakage, prevent source damage or excessive access, and keep results contained.</strong> Main DSH protections are deployed; remote-worker egress and read-only source scope do not yet meet every condition in the original brief.</div><nav aria-label="Contents">${toc.join('')}<a href="#verification-records">Supporting verification records</a></nav>${html}<p class="meta">Built from tracked Markdown. Diagram controls adapted from SMP EDA ARCHITECTURE_AND_DATAFLOW.html; local Mermaid 10.8.0 / svg-pan-zoom 3.6.1. No CDN required.</p></main>
<script>${assets[0]}</script><script>${assets[1]}</script><script>${assets[2]}</script><script>
window.__reportReady=false;window.__reportErrors=[];
mermaid.initialize({startOnLoad:false,theme:'dark',securityLevel:'strict',flowchart:{htmlLabels:false},themeVariables:{background:'#0b0f19',mainBkg:'#1e293b',primaryColor:'#1e40af',primaryTextColor:'#f8fafc',lineColor:'#94a3b8'}});
(async()=>{try{await mermaid.run({querySelector:'.mermaid'});initMermaidPanZoom();window.__reportReady=true;}catch(error){window.__reportErrors.push(error.message);console.error(error);}})();
</script></body></html>`;
const target=path.join(root,'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html');
const normalized=result.replace(/\r\n/g,'\n');
fs.writeFileSync(target,normalized); console.log(JSON.stringify({target,diagrams:diagram,sections:toc.length,bytes:Buffer.byteLength(normalized)}));
const guidePage=result.slice(0,result.indexOf('<body>')).replace(/<title>.*?<\/title>/,'<title>Shared LLM — Setup and Verified Test Results</title>')+`<body><main>${guide}</main></body></html>`;
fs.writeFileSync(path.join(root,'docs/LLM_SETUP_AND_TEST_RESULTS.html'),guidePage.replace(/\r\n/g,'\n'));
