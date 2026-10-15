import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const modules = process.env.DSH_DOC_NODE_MODULES || 'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { default: { chromium } } = await import(pathToFileURL(path.join(modules,'playwright/index.js')));
const root=path.resolve(import.meta.dirname,'..');
const out=path.resolve(process.env.DSH_DOC_QA_OUTPUT || 'C:/Users/skunpojt/outputs/dsh-report-review-20261015');
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
try {
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 const page=await context.newPage(); const errors=[];const external=[];
 page.on('pageerror',error=>errors.push(error.message));
 page.on('request',request=>{if(/^https?:/.test(request.url()))external.push(request.url());});
 await page.goto(pathToFileURL(path.join(root,'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html')).href);
 await page.waitForFunction(()=>window.__reportReady || window.__reportErrors?.length,{timeout:60000});
 assert.deepEqual(await page.evaluate(()=>window.__reportErrors),[]);
 await page.waitForTimeout(1200);
 assert.equal(await page.locator('.mermaid-container svg').count(),3);
 assert.equal(await page.locator('script[src]').count(),0);
 assert.deepEqual(external,[]);
 const panel=page.locator('.mermaid-wrapper').first();
 const zoom=()=>page.evaluate(()=>mermaidPanZoomInstances.get(document.querySelector('.mermaid-container')).getZoom());
 const initial=await zoom();await panel.getByRole('button',{name:'Zoom in',exact:true}).click();const increased=await zoom();assert(increased>initial);
 await panel.getByRole('button',{name:'Reset',exact:true}).click();assert(Math.abs(await zoom()-initial)<0.001);
 await panel.getByRole('button',{name:'Fullscreen',exact:true}).click();await page.waitForFunction(()=>!!document.fullscreenElement);await page.evaluate(()=>document.exitFullscreen());
 let copied='';page.on('dialog',async dialog=>{copied=dialog.defaultValue();await dialog.accept();});
 await panel.getByRole('button',{name:'Copy code',exact:true}).click();await page.waitForTimeout(250);
 const copySucceeded=copied.includes('flowchart TB') || (await panel.innerText()).includes('Copied!');assert(copySucceeded);
 const downloads=[];
 for(const [button,filename] of [['Save SVG','architecture-live.svg'],['Save PNG','architecture-live.png']]) {
  const pending=page.waitForEvent('download',{timeout:20000});await panel.getByRole('button',{name:button,exact:true}).click();const download=await pending;await download.saveAs(path.join(out,filename));downloads.push(filename);
 }
 const svg=fs.readFileSync(path.join(out,downloads[0]),'utf8');assert(svg.includes('<svg'));assert(!/<g[^>]*class="svg-pan-zoom_viewport"[^>]*transform=/.test(svg));
 const png=fs.readFileSync(path.join(out,downloads[1]));assert.equal(png.subarray(1,4).toString(),'PNG');
 await page.goto(pathToFileURL(path.join(root,'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html')).href);await page.waitForFunction(()=>window.__reportReady);await page.waitForTimeout(900);
 const clippedNodes = await page.locator('.mermaid-container').evaluateAll(containers => containers.flatMap((container, diagram) => {
  const frame=container.getBoundingClientRect();
  return Array.from(container.querySelectorAll('g.node')).filter(node => {
   const box=node.getBoundingClientRect();
   return box.left<frame.left-2 || box.right>frame.right+2 || box.top<frame.top-2 || box.bottom>frame.bottom+2;
  }).map(node=>({diagram:diagram+1,label:node.textContent}));
 }));
 assert.deepEqual(clippedNodes,[], 'Initial diagram view must show every node');
 await page.screenshot({path:path.join(out,'report-overview.png')});
 await page.locator('.mermaid-wrapper').first().screenshot({path:path.join(out,'report-architecture.png')});
 for (let i=1;i<3;i++) await page.locator('.mermaid-wrapper').nth(i).screenshot({path:path.join(out,`report-architecture-${i+1}.png`)});
 assert.deepEqual(errors,[]);
 const record={time:new Date().toISOString(),renderedDiagrams:3,initialNodesUnclipped:true,externalResourceRequests:external.length,zoom:true,reset:true,fullscreen:true,copySource:copySucceeded,svgExport:true,pngExport:true,pageErrors:errors,pngWidth:png.readUInt32BE(16),pngHeight:png.readUInt32BE(20)};
 fs.writeFileSync(path.join(out,'html-verification.json'),JSON.stringify(record,null,2));console.log(JSON.stringify(record));
}finally{await browser.close();}
