import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const shell=fs.readFileSync(path.join(root,'docs/LLM_SETUP_AND_TEST_RESULTS.html'),'utf8');
const head=shell.slice(0,shell.indexOf('<body>'));
for(const [name,title]of [['JUPYTERLAB','JupyterLab in a private DSH environment'],['MANAGED_CLIENT_SUPPORT','DSH managed coding clients'],['INFERENCE_OPTIMIZATION_EXPERIENCE','DSH inference optimization — decisions, trials and lessons'],['MODEL_UPDATE_1017','DeepSeek-V4.1-Flash-1017 — setup and qualification'],['ADMIN_USAGE_TELEMETRY','DSH administrator — usage and storage']]){
 const source=fs.readFileSync(path.join(root,'docs',name+'.md'),'utf8');
 let body=marked.parse(source).replace(/href="(?!https?:|#)([^"\s]+)"/g,(_,ref)=>ref.endsWith('.html')?`href="${ref}"`:`href="https://github.com/skunpoj/dsh_setup/blob/main/docs/${ref}"`);
 body=body.replace(/<img src="(images\/platform\/[^"\s]+)" alt="([^"]*)">/g,(_,image,alt)=>{
  const file=path.resolve(root,'docs',image);if(!file.startsWith(path.join(root,'docs/images/platform')+path.sep))throw Error('Unscoped image');
  return `<img style="max-width:100%;height:auto" src="data:image/png;base64,${fs.readFileSync(file).toString('base64')}" alt="${alt}">`;
 });
 const html=head.replace(/<title>.*?<\/title>/,`<title>${title}</title>`)+'<body><main>'+body+'</main></body></html>';
 fs.writeFileSync(path.join(root,'docs',name+'.html'),html.replaceAll('\r\n','\n'));
 console.log(JSON.stringify({report:name+'.html',bytes:Buffer.byteLength(html)}));
}
