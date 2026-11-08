import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {default:{chromium}}=await import(pathToFileURL(path.join(modules,'playwright/index.js')));
const out=path.resolve(process.argv[2] || path.join(root,'outputs/platform-guide'));
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.DSH_DOC_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(path.join(root,'docs/DSH_PLATFORM_GUIDE.html')).href);
 assert.equal(await page.locator('.mermaid-wrapper').count(),3);
 for(const width of [1440,760,390]){
  await page.setViewportSize({width,height:1050});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
 }
 const first=page.locator('.mermaid-wrapper').first();
 const group=first.locator('svg>g');
 await first.getByRole('button',{name:'Zoom in'}).click();assert.match(await group.getAttribute('style'),/scale\(1\.2\)/);
 await first.getByRole('button',{name:'Reset'}).click();assert.match(await group.getAttribute('style'),/scale\(1\)/);
 let event=page.waitForEvent('download');await first.getByRole('button',{name:'Save SVG'}).click();
 let download=await event;const svg=path.join(out,'architecture.svg');await download.saveAs(svg);assert.match(fs.readFileSync(svg,'utf8'),/<svg/);
 event=page.waitForEvent('download');await first.getByRole('button',{name:'Save PNG'}).click();
 download=await event;const png=path.join(out,'architecture.png');await download.saveAs(png);assert.equal(fs.readFileSync(png).subarray(1,4).toString(),'PNG');
 assert.deepEqual(errors,[]);
 await page.screenshot({path:path.join(out,'platform-guide.png'),fullPage:true});
 console.log(JSON.stringify({passed:true,diagrams:3,viewports:3,svgExport:true,pngExport:true}));
}finally{await browser.close()}
