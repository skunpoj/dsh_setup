import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const root=path.resolve(import.meta.dirname,'..');
const docs=path.join(root,'docs');
const modules=process.env.DSH_DOC_NODE_MODULES;
if(!modules)throw Error('Set DSH_DOC_NODE_MODULES to the installed documentation dependency directory');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const source=fs.readFileSync(path.join(docs,'GOVERNED_HARNESS_RUNTIME_COMPARISON.md'),'utf8');
const content=marked.parse(source,{gfm:true});
const head=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Governed Harness and managed agent-runtime comparison</title><style>*{box-sizing:border-box}body{margin:0;background:#edf2f7;color:#193047;font:16px/1.65 system-ui,sans-serif}main{max-width:1500px;margin:24px auto;background:#fff;padding:36px;border-radius:12px}h1,h2,h3{color:#075985;line-height:1.3}a{color:#0369a1}code{overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f3f6f9;padding:14px;overflow:auto}.table-wrap{width:100%;overflow:auto;margin:18px 0 28px}table{border-collapse:collapse;min-width:1100px;width:100%;table-layout:auto}td,th{border:1px solid #c8d5e1;padding:10px;vertical-align:top;text-align:left;overflow-wrap:normal;word-break:normal;hyphens:none}th{background:#e9f3f9;position:sticky;top:0}li{margin:.45em 0}.notice{background:#fff7ed;border-left:5px solid #f59e0b;padding:12px 16px}@media(max-width:700px){main{margin:0;padding:18px}table{min-width:1000px}}</style></head>`;
const wrapped=content.replace(/<table>[\s\S]*?<\/table>/g,match=>`<div class="table-wrap">${match}</div>`);
const nav='<nav><a href="THREE_RISK_CONTROLS.html">Three risk controls</a> · <a href="AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html">Agent runtime status</a> · <a href="../README.md">Repository overview</a></nav>';
fs.writeFileSync(path.join(docs,'GOVERNED_HARNESS_RUNTIME_COMPARISON.html'),head+`<body><main>${nav}${wrapped}</main></body></html>`);
console.log('Governed Harness comparison HTML generated');
