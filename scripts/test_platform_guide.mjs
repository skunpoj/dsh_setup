import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const mod=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {default:{chromium}}=await import(pathToFileURL(path.join(mod,'playwright/index.js')));
const output=process.argv[2];fs.mkdirSync(output,{recursive:true});
const files=[path.join(root,'docs/DSH_PLATFORM_GUIDE.html'),...(process.argv[3]?[process.argv[3]]:[])];
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const results=[];
try {
for(const [i,file] of files.entries()){
const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
for(const width of [1440,760,390]){
await page.setViewportSize({width,height:1050});await page.goto(pathToFileURL(file).href);await page.waitForFunction(()=>window.__reportReady,{timeout:60000});
const state=await page.evaluate(()=>({sections:[...document.querySelectorAll('main>h2')].map(e=>e.textContent),diagrams:document.querySelectorAll('.mermaid-container svg').length,images:[...document.images].map(e=>({ok:e.complete&&e.naturalWidth>0,embedded:e.src.startsWith('data:')})),toc:[...document.querySelectorAll('nav a')].map(e=>({href:e.hash,exists:!!document.querySelector(e.hash)})),overflow:document.documentElement.scrollWidth>innerWidth+2,text:document.body.innerText}));
assert.equal(state.sections.length,10);assert.equal(state.sections.at(-1),'LLM and GPU setup');assert.equal(state.diagrams,4);assert.equal(state.images.length,5);assert.ok(state.images.every(x=>x.ok&&x.embedded));assert.ok(state.toc.every(x=>x.exists));assert.equal(new Set(state.toc.map(x=>x.href)).size,10);assert.equal(state.overflow,false);assert.ok(state.text.includes('35 Deployments'));assert.ok(state.text.includes('29 active and 6 scaled to zero'));assert.ok(state.text.toLowerCase().includes('synthetic'));assert.ok(state.text.includes('1,048,576'));
if(i===0)assert.ok(!state.text.includes('Private-site deployment and ingress inventory'));else assert.ok(state.text.includes('Private-site deployment and ingress inventory'));
results.push({edition:i===0?'portable':'private-site',width,sections:10,diagrams:4,embeddedScreenshots:5,passed:true});
if(width===1440){for(const [section,label] of [[5,'features'],[8,'screenshots'],[10,'gpu-setup']]){await page.locator('#guide-section-'+section).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,`${i}-${label}.png`)});}}
}
const controls=page.locator('.mermaid-wrapper').last();await controls.scrollIntoViewIfNeeded();await controls.getByRole('button',{name:'Zoom in',exact:true}).click();await controls.getByRole('button',{name:'Reset',exact:true}).click();
const downloadPromise=page.waitForEvent('download');await controls.getByRole('button',{name:'Save SVG',exact:true}).click();const download=await downloadPromise;await download.saveAs(path.join(output,`diagram-${i}.svg`));assert.ok(fs.readFileSync(path.join(output,`diagram-${i}.svg`),'utf8').includes('<svg'));
assert.deepEqual(errors,[]);await page.close();
}
fs.writeFileSync(path.join(output,'platform-guide-validation.json'),JSON.stringify({passed:true,results},null,2));console.log(JSON.stringify({passed:true,viewportChecks:results.length}));
}finally{await browser.close();}

