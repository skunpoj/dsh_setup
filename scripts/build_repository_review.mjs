import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root = path.resolve(import.meta.dirname, '..');
const modules = process.env.DSH_DOC_NODE_MODULES || 'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { marked } = await import(pathToFileURL(path.join(modules, 'marked/lib/marked.esm.js')));
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
// The model's narrative is an artifact, never executable markup.
marked.use({renderer: {
  html({text}) { return escape(text); },
  image({text}) { return `<span>${escape(text || 'Image omitted')}</span>`; },
  link({href, text}) {
    if (!/^(https?:\/\/|#)/.test(href)) return escape(text);
    return `<a href="${escape(href)}" rel="noopener noreferrer">${escape(text)}</a>`;
  }
}});
const source = fs.readFileSync(path.join(root, 'docs/REALISTIC_REPOSITORY_REVIEW_20261017.md'), 'utf8')
  .replace(/\]\((?!https?:|#)([^)]+)\)/g, (_, name) =>
    `](https://github.com/skunpoj/dsh_setup/blob/main/docs/${name})`);
const shell = fs.readFileSync(path.join(root, 'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html'), 'utf8');
const head = shell.slice(0, shell.indexOf('<body>')).replace(/<title>.*?<\/title>/,
  '<title>DSH — Real Repository Accuracy and Long-Output Test</title>');
const target = path.join(root, 'docs/REALISTIC_REPOSITORY_REVIEW_20261017.html');
fs.writeFileSync(target, `${head}<body><main>${marked.parse(source)}</main></body></html>`);
console.log(JSON.stringify({target}));
