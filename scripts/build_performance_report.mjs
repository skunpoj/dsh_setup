import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const shell=fs.readFileSync(path.join(root,'docs/LLM_SETUP_AND_TEST_RESULTS.html'),'utf8');
const head=shell.slice(0,shell.indexOf('<body>'));
const name='PERFORMANCE_OPTIMIZATION_20261018';
const md=fs.readFileSync(path.join(root,'docs',name+'.md'),'utf8');
if(md.includes('RESULTS_PENDING'))throw Error('Performance qualification is incomplete');
const body=marked.parse(md).replace(/href="(?!https?:|#)([^"\s]+)"/g,(_,ref)=>
 ref.endsWith('.html')?`href="${ref}"`:`href="https://github.com/skunpoj/dsh_setup/blob/main/docs/${ref}"`);
const html=head.replace(/<title>.*?<\/title>/,'<title>DSH Performance Optimization on Four GPUs</title>')+`<body><main>${body}</main></body></html>`;
fs.writeFileSync(path.join(root,'docs',name+'.html'),html.replace(/\r\n/g,'\n'));
console.log(JSON.stringify({report:name+'.html',bytes:Buffer.byteLength(html)}));
