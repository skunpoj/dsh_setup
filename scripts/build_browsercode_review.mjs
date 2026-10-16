import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root = path.resolve(import.meta.dirname, '..');
const modules = process.env.DSH_DOC_NODE_MODULES || 'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { marked } = await import(pathToFileURL(path.join(modules, 'marked/lib/marked.esm.js')));
// Reuse the existing offline SMP-style diagram controls, assets and typography.
// Rebuild that shell with build_security_walkthrough.mjs when its assets change.
const shell = fs.readFileSync(path.join(root, 'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html'), 'utf8');
let html = marked.parse(fs.readFileSync(path.join(root, 'docs/BROWSERCODE_AND_BOT_DSH_REVIEW.md'), 'utf8'));
let diagrams = 0;
html = html.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g, (_, code) => {
  diagrams++;
  const prototype = shell.match(/<section class="mermaid-wrapper">[\s\S]*?<\/section>/)?.[0];
  if (!prototype) throw Error('Diagram shell missing');
  return prototype.replace(/Architecture 1/, `Architecture ${diagrams}`)
    .replace(/<div class="mermaid" data-raw-code="[\s\S]*?<\/div>/,
      `<div class="mermaid" data-raw-code="${code.replaceAll('"','&quot;')}">${code}</div>`);
});
const toc = [];
html = html.replace(/<h2>(.*?)<\/h2>/g, (_, title) => {
  const id = `review-${toc.length + 1}`;
  toc.push(`<a href="#${id}">${title}</a>`);
  return `<h2 id="${id}">${title}</h2>`;
});
html = html.replace(/href="(?!https?:|#)([^"\s]+)"/g, (_, name) =>
  `href="https://github.com/skunpoj/dsh_setup/blob/main/docs/${name}"`);
const start = shell.indexOf('<main>'), end = shell.indexOf('</main>', start);
if (start < 0 || end < 0) throw Error('Report shell missing');
const heading = html.match(/<h1>[\s\S]*?<\/h1>/)?.[0] || '';
html = html.replace(heading, '');
const result = (shell.slice(0, start) + `<main>${heading}<nav aria-label="Contents">${toc.join('')}</nav>${html}</main>` + shell.slice(end + 7))
  .replace(/<title>.*?<\/title>/, '<title>BrowserCode and BOT DSH — Architecture and Risk Review</title>');
fs.writeFileSync(path.join(root, 'docs/BROWSERCODE_AND_BOT_DSH_REVIEW.html'), result.replace(/\r\n/g, '\n'));
console.log(JSON.stringify({diagrams, sections: toc.length}));
