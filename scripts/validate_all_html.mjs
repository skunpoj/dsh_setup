// Offline rendering and content qualification for every tracked documentation HTML.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const out=path.resolve(process.argv[2] || path.join(root,'outputs/html-validation'));
fs.mkdirSync(out,{recursive:true});
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {default:{chromium}}=await import(pathToFileURL(path.join(modules,'playwright/index.js')));
const names=execFileSync('git',['ls-files','--cached','--others','--exclude-standard','docs/*.html'],{cwd:root,encoding:'utf8'}).trim().split(/\r?\n/).filter(Boolean);
const browser=await chromium.launch({headless:true,executablePath:process.env.DSH_DOC_BROWSER || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const record={timeUTC:new Date().toISOString(),scope:'Saved HTML content and rendering; no live security acceptance',pages:[],failures:[]};
try{
 for(const name of [...new Set(names)]){
  const page=await browser.newPage();const errors=[],external=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route(/^https?:/,r=>{external.push(r.request().url());return r.abort();});
  const checks=[];
  for(const width of [1440,760,390]){
   await page.setViewportSize({width,height:1050});await page.goto(pathToFileURL(path.join(root,name)).href);
   if(await page.evaluate(()=>Object.hasOwn(window,'__reportReady')))await page.waitForFunction(()=>window.__reportReady || window.__reportErrors?.length,{timeout:60000});
   await page.waitForTimeout(250);
   const facts=await page.evaluate(()=>({title:document.title,language:document.documentElement.lang,h1:document.querySelectorAll('h1').length,
    textLength:document.body.innerText.length,scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth,
    diagramErrors:window.__reportErrors||[],brokenImages:[...document.images].filter(x=>!x.complete||x.naturalWidth===0).length,
    diagrams:document.querySelectorAll('.mermaid-container svg').length,
    localLinks:[...document.querySelectorAll('a[href]')].map(a=>a.getAttribute('href')).filter(h=>!h.match(/^(https?:|mailto:|#|data:)/))}));
   const missing=facts.localLinks.filter(h=>!fs.existsSync(path.resolve(root,path.dirname(name),decodeURIComponent(h.split('#')[0].split('?')[0]))));
   const failed=[];if(!facts.title||facts.h1!==1||facts.textLength<200)failed.push('Missing readable document content');
   if(facts.scrollWidth>width+2)failed.push('Page-level horizontal overflow');
   if(facts.diagramErrors.length||facts.brokenImages||missing.length)failed.push('Diagram, image or local link failure');
   checks.push({width,...facts,missingLocalLinks:missing,failures:failed});
   if(failed.length)record.failures.push({name,width,failures:failed});
   if(width===1440)await page.screenshot({path:path.join(out,path.basename(name,'.html')+'.png')});
  }
  if(name.endsWith('/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html')){
   const headings=await page.locator('main > h2').allTextContents();
   assert.deepEqual(headings,['1 Prevent external leakage','2 Prevent damage or excessive access','3 Keep results contained']);
   assert.equal(await page.locator('#embedded-llm-guide, #embedded-readme, details[id^="evidence-"]').count(),0);
  }
  if(errors.length||external.length)record.failures.push({name,errors,unexpectedExternalResources:external});
  record.pages.push({name,checks,errors,externalResources:external.length});await page.close();
 }
 record.passed=record.failures.length===0;
 fs.writeFileSync(path.join(out,'all-html-validation.json'),JSON.stringify(record,null,2));
 console.log(JSON.stringify({pages:record.pages.length,viewportChecks:record.pages.length*3,passed:record.passed,failures:record.failures}));
 if(!record.passed)process.exitCode=1;
}finally{await browser.close();}
