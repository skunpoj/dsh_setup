import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const shell=fs.readFileSync(path.join(root,'docs/LLM_SETUP_AND_TEST_RESULTS.html'),'utf8');
const head=shell.slice(0,shell.indexOf('<body>')).replace(/<title>.*?<\/title>/,'<title>DSH Deployment, Persistence and Functional Review</title>');
const body=marked.parse(fs.readFileSync(path.join(root,'docs/DEPLOYMENT_AND_FUNCTION_REVIEW_20261017.md'),'utf8'))
 .replace(/href="(?!https?:|#)([^"\s]+)"/g,(_,name)=>name.endsWith('.html')
  ? `href="${name}"` : `href="https://github.com/skunpoj/dsh_setup/blob/main/docs/${name}"`);
const out=path.join(root,'docs/DEPLOYMENT_AND_FUNCTION_REVIEW_20261017.html');
fs.writeFileSync(out,(head+`<body><main>${body}</main></body></html>`).replace(/\r\n/g,'\n'));
console.log(JSON.stringify({report:path.basename(out),bytes:fs.statSync(out).size}));
