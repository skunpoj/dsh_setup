// Real upstream app browser qualification against a disposable built image.
// Owner scope only. Never types/submits a conversation or calls inference.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{spawn,spawnSync}=require('node:child_process');
const port=31998,name=`dsh-browser-${process.pid}`,output=process.env.DSH_CANDIDATE_BROWSER_OUTPUT||'candidate-evidence/upstream-browser';
const image=process.env.DSH_CANDIDATE_IMAGE||'dsh-upstream-candidate';
fs.mkdirSync(output,{recursive:true});
const themeSource=path.resolve(__dirname,'../plugins/dsh-theme-custom-light');
const args=['run','--rm','--name',name,'--mount',`type=bind,source=${themeSource},target=/opt/dsh/plugins/dsh-theme-custom-light,readonly`,'--network','host','--user','10001:10001','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--tmpfs','/tmp:rw,nosuid,nodev,size=256m,mode=1777','--tmpfs','/workspace:rw,nosuid,nodev,size=16m,uid=10001,gid=10001','--tmpfs','/native-cache:rw,exec,nosuid,nodev,size=16m,uid=10001,gid=10001','--entrypoint','node',image,'/opt/dsh/scripts/serve_candidate_browser.js'];
const server=spawn('docker',args,{stdio:['ignore','pipe','pipe']});
let log='',closed=false,spawnError,browser,page,phase='startup';const browserDiagnostics=[];
server.stdout.on('data',b=>{log=(log+b.toString()).slice(-32000);});server.stderr.on('data',b=>{log=(log+b.toString()).slice(-32000);});server.on('error',e=>spawnError=e);server.on('exit',()=>closed=true);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{try{
 const {CUSTOM_LIGHT_TOKENS:expectedThemeTokens}=await import(require('node:url').pathToFileURL(path.join(themeSource,'src/palette.mjs')).href);
 const normalizeToken=value=>value.trim().toLowerCase().replace(/^#([0-9a-f])([0-9a-f])([0-9a-f])$/,'#$1$1$2$2$3$3');
 const assertTokens=(actual,expected)=>{for(const [key,value] of Object.entries(expected))assert.equal(normalizeToken(actual[key]),normalizeToken(value),'Rendered palette differs at '+key);};
 const deadline=Date.now()+90000;let ready;
 while(Date.now()<deadline&&!closed&&!spawnError){ready=log.split(/\r?\n/).map(line=>{try{return JSON.parse(line)}catch{return null}}).find(value=>value?.browserReady);if(ready)break;await sleep(200);}
 assert(!spawnError,spawnError?.message);
 if(!ready){const diagnostic={stage:'disposable-upstream-startup',closed,log:log.replace(/token[=:]\s*[A-Za-z0-9_-]+/gi,'token=[REDACTED]').replace(/synthetic-browser-no-inference/g,'[SYNTHETIC KEY REDACTED]').slice(-16000)};fs.writeFileSync(path.join(output,'startup-failure.json'),JSON.stringify(diagnostic,null,2)+'\n');console.error(JSON.stringify(diagnostic));}
 assert(ready,'Disposable upstream app did not become ready; sanitized startup-failure.json saved');
 assert.equal(ready.themeBundle?.clientSHA256,'59848c883759a3e8f16be55f7f2127187b0d0cb7213167d94b587b4b8c982fdd','Actual native profile did not install the qualified theme bundle');
 const {chromium}=require(process.env.DSH_PLAYWRIGHT||'playwright');
 browser=await chromium.launch({headless:true,args:['--host-resolver-rules=MAP dsh-ci.test 127.0.0.1','--no-proxy-server',`--unsafely-treat-insecure-origin-as-secure=http://dsh-ci.test:${port}`]});
 const iterations=[];let rows;
 for(let iteration=0;iteration<3;iteration++){
 const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'en-US'});
 let holdSessionList=false,sessionListGate,releaseSessionList,heldSessionList,markSessionListHeld,delayedSessionLists=0;
 const externalRequests=[],pageErrors=[],inferenceRequests=[];
 await context.route('**/*',async route=>{const url=new URL(route.request().url());if(!['127.0.0.1','dsh-ci.test'].includes(url.hostname)){externalRequests.push(url.origin);return route.abort();}if(/\/v1\/(chat|responses|completions)/.test(url.pathname)){inferenceRequests.push(url.pathname);return route.abort();}if(holdSessionList&&url.pathname==='/api/session/list'){delayedSessionLists++;markSessionListHeld();await sessionListGate;}return route.continue();});
 page=await context.newPage();page.setDefaultTimeout(25000);page.on('pageerror',e=>pageErrors.push(e.message));page.on('console',message=>{if(message.type()==='error')browserDiagnostics.push({type:'console',message:message.text().replace(/token[=:]\s*[A-Za-z0-9_-]+/gi,'token=[REDACTED]').slice(0,1000)});});page.on('response',response=>{if(response.status()>=400)browserDiagnostics.push({type:'http',status:response.status(),path:new URL(response.url()).pathname});});
 const settings=()=>page.getByRole('button',{name:'Settings',exact:true});
 const modelsModule=()=>page.locator('style[data-plugin="@deepseek-ai/dsh-client-ui-settings-models"]').first();
 // The pinned upstream shell closes Settings when first-run onboarding appears.
 // Observe the initial Host session answer and Models module, then let React commit
 // before interacting. A visible sidebar alone is not application readiness.
 async function navigateReady(navigate,label,delaySession=false){
  phase='iteration-'+iteration+':'+label;
  const sessionResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/session/list');
  if(delaySession){
   holdSessionList=true;
   sessionListGate=new Promise(resolve=>releaseSessionList=resolve);
   heldSessionList=new Promise(resolve=>markSessionListHeld=resolve);
  }
  let timer;
  try{
   const release=delaySession?(async()=>{
    await Promise.race([heldSessionList,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Controlled session-list request was not observed')),25000);})]);
    await settings().waitFor({state:'visible'});
    await modelsModule().waitFor({state:'attached'});
    holdSessionList=false;releaseSessionList();
   })():Promise.resolve();
   await Promise.all([navigate(),release]);
   const response=await sessionResponse;assert.equal(response.status(),200);
   const envelope=await response.json();assert.equal(envelope.result?.ok,true,'Initial Host session list failed');assert(Array.isArray(envelope.result.value?.items));
   await modelsModule().waitFor({state:'attached'});
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  }finally{clearTimeout(timer);holdSessionList=false;releaseSessionList?.();}
 }
 await navigateReady(()=>page.goto(`http://dsh-ci.test:${port}/?token=${encodeURIComponent(ready.token)}`,{waitUntil:'domcontentloaded'}),'initial',iteration!==1);
 // Managed LiteLLM profiles expose Settings directly. Opening is idempotent.
 const openSettings=async()=>{await settings().click();await page.getByRole('dialog').waitFor({state:'visible'});assert.equal(await settings().getAttribute('aria-expanded'),'true');};
 await settings().waitFor({state:'visible'});
 const selector=()=>page.getByRole('button',{name:/^Select model/});
 await selector().waitFor({state:'visible'});await selector().click();
 const drill=page.getByRole('menuitem',{name:/^Model/});if(await drill.count())await drill.click();
 const group=page.getByRole('group',{name:'Model and reasoning effort',exact:true});
 const models=group.locator('[data-model-id]');await models.nth(4).waitFor({state:'visible'});
 rows=await models.evaluateAll(nodes=>nodes.map(node=>({provider:node.getAttribute('data-provider-id'),model:node.getAttribute('data-model-id')})));
 assert(rows.length>=5,'Actual DOM model selector lacks managed catalog');assert(rows.every(row=>row.provider==='litellm-cluster'),'External provider rendered in model selector');assert(rows.some(row=>row.model==='deepseek-v4.1-flash'));
 await page.keyboard.press('Escape');await group.waitFor({state:'hidden'});await openSettings();
 const dialog=page.getByRole('dialog');await dialog.waitFor({state:'visible'});
 const modelsNav=dialog.getByRole('button',{name:'Models',exact:true});
 await modelsNav.click();await dialog.getByRole('heading',{name:'Models',exact:true}).waitFor({state:'visible'});
 await dialog.getByText('Cluster LiteLLM Gateway',{exact:true}).first().waitFor({state:'visible'});
 await page.screenshot({path:path.join(output,'upstream-model-settings-'+iteration+'.png'),fullPage:true});
 phase='iteration-'+iteration+':general-before-reload';
 await dialog.getByRole('button',{name:'General',exact:true}).click();
 // Exercise the actual registered plugin in the upstream renderer, not a service double.
 phase='iteration-'+iteration+':native-theme';
 const appearance=()=>page.getByRole('dialog').getByRole('combobox',{name:'Appearance',exact:true});
 await appearance().waitFor({state:'visible'});
 assert.deepEqual(await appearance().locator('option').evaluateAll(nodes=>nodes.map(n=>({value:n.value,label:n.textContent}))),[
  {value:'light',label:'Light'},{value:'dark',label:'Dark'},{value:'system',label:'System'},{value:'custom-light',label:'Custom Light'}]);
 const readAppearance=()=>page.evaluate(keys=>{const css=getComputedStyle(document.body);return{dark:document.body.hasAttribute('data-ds-dark-theme'),background:css.backgroundColor,base:css.getPropertyValue('--dsw-alias-bg-base').trim(),font:parseFloat(css.getPropertyValue('--dsh-content-font-size')),tokens:Object.fromEntries(keys.map(key=>[key,css.getPropertyValue(key).trim()]))};},Object.keys(expectedThemeTokens));
 const settleAppearance=async(id,dark)=>{
  await page.waitForFunction(({id,dark})=>document.querySelector('select[aria-label="Appearance"]')?.value===id&&document.body.hasAttribute('data-ds-dark-theme')===dark,{id,dark},{timeout:8000});
 };
 await appearance().selectOption('light');await settleAppearance('light',false);const themeLight=await readAppearance();
 await appearance().selectOption('dark');await settleAppearance('dark',true);const themeDark=await readAppearance();
 assert.notEqual(themeDark.background,themeLight.background,'Native Dark remained visually Light');
 if(iteration===0)await page.screenshot({path:path.join(output,'native-dark.png'),fullPage:true});
 await appearance().selectOption('system');
 await page.emulateMedia({colorScheme:'light'});await settleAppearance('system',false);assert.equal((await readAppearance()).background,themeLight.background);
 await page.emulateMedia({colorScheme:'dark'});await settleAppearance('system',true);assert.equal((await readAppearance()).background,themeDark.background);
 await appearance().selectOption('custom-light');await settleAppearance('custom-light',false);
 await page.waitForFunction(()=>getComputedStyle(document.body).getPropertyValue('--dsw-alias-bg-base').trim().toLowerCase()==='#f4f7fa');
 const themeCustom=await readAppearance();assert.equal(themeCustom.background,'rgb(244, 247, 250)');assertTokens(themeCustom.tokens,expectedThemeTokens);
 if(iteration===0)await page.screenshot({path:path.join(output,'custom-light.png'),fullPage:true});
 const fontPersistenceReceipts=[];
 const projectThemeSetting=view=>({namespace:view?.ns,fontSize:view?.value?.fontSize,userFontSize:view?.user?.fontSize,revision:view?.revision});
 const readDurableFont=async(label,expected)=>{
  const read=await page.evaluate(async({rpcId})=>{
   const transport=globalThis.__DSH_TRANSPORT__;
   const send=typeof transport?.fetch==='function'?transport.fetch.bind(transport):window.fetch.bind(window);
   const response=await send('/api/settings/describe',{method:'POST',credentials:'same-origin',headers:{'content-type':'application/json'},body:JSON.stringify({type:'client-request',rpcId,method:'settings/describe',payload:{args:{}}})});
   const envelope=await response.json();
   const view=envelope.result?.ok===true?envelope.result.value?.namespaces?.find(item=>item.ns==='ui-theme'):undefined;
   return{status:response.status,ok:envelope.result?.ok===true,errorCode:envelope.result?.error?.code,setting:view?{namespace:view.ns,fontSize:view.value?.fontSize,userFontSize:view.user?.fontSize,revision:view.revision}:null};
  },{rpcId:'theme-font-read-'+iteration+'-'+label});
  assert.equal(read.status,200,'Durable font read HTTP status: '+label);
  assert.equal(read.ok,true,'Durable font read refused: '+label+' '+(read.errorCode||'UNKNOWN'));
  assert.equal(read.setting?.namespace,'ui-theme','Durable font namespace missing: '+label);
  assert.equal(read.setting.fontSize,expected,'Host effective font differs: '+label);
  assert.equal(read.setting.userFontSize,expected,'Host saved user font differs: '+label);
  assert.notEqual(read.setting.revision,undefined,'Durable font read has no revision: '+label);
  fontPersistenceReceipts.push({phase:label,expected,...read.setting});
  return read.setting;
 };
 const changeFontAndVerifySaved=async(buttonName,expected,label)=>{
  const [response]=await Promise.all([
   page.waitForResponse(reply=>{
    if(new URL(reply.url()).pathname!=='/api/settings/mutate'||reply.request().method()!=='POST')return false;
    let input;try{input=reply.request().postDataJSON();}catch{return false;}
    const args=input?.payload?.args;
    return args?.ns==='ui-theme'&&Array.isArray(args.ops)&&args.ops.some(op=>op.op==='set'&&Array.isArray(op.path)&&op.path.length===1&&op.path[0]==='fontSize'&&op.value===expected);
   }),
   page.getByRole('dialog').getByRole('button',{name:buttonName,exact:true}).click()
  ]);
  assert.equal(await response.finished(),null,'Font write transport did not finish: '+label);
  assert.equal(response.status(),200,'Font write HTTP status: '+label);
  const input=response.request().postDataJSON();
  assert.deepEqual(input.payload.args.ops,[{op:'set',path:['fontSize'],value:expected}],'Unexpected font mutation: '+label);
  const envelope=await response.json();
  assert.equal(envelope.result?.ok,true,'Font write refused: '+label+' '+(envelope.result?.error?.code||'UNKNOWN'));
  const saved=projectThemeSetting(envelope.result.value);
  assert.equal(saved.namespace,'ui-theme','Font write returned another namespace: '+label);
  assert.equal(saved.fontSize,expected,'Accepted font write has wrong effective value: '+label);
  assert.equal(saved.userFontSize,expected,'Accepted font write has wrong saved user value: '+label);
  assert.notEqual(saved.revision,undefined,'Accepted font write has no revision: '+label);
  fontPersistenceReceipts.push({phase:label+'-ack',expected,...saved});
  await readDurableFont(label+'-readback',expected);
  await page.waitForFunction(value=>parseFloat(getComputedStyle(document.body).getPropertyValue('--dsh-content-font-size'))===value,expected);
 };
 const themeFontBefore=themeCustom.font;assert(Number.isFinite(themeFontBefore));
 phase='iteration-'+iteration+':font-increase-ack';
 await changeFontAndVerifySaved('Increase font size',themeFontBefore+1,'increase');
 assert.equal(await appearance().inputValue(),'custom-light','Font adoption reset Custom appearance');assertTokens((await readAppearance()).tokens,expectedThemeTokens);
 const coding=()=>page.getByRole('switch',{name:'Show coding view',exact:true}).or(page.getByRole('checkbox',{name:'Show coding view',exact:true}));
 await coding().waitFor({state:'visible'});const before=await coding().isChecked();
 await coding().click();
 for(let n=0;n<80&&(await coding().isChecked())===before;n++)await sleep(100);
 assert.equal(await coding().isChecked(),!before,'Host-backed owner preference did not settle');
 for(let n=0;n<80&&!(await coding().isEnabled());n++)await sleep(100);
 assert(await coding().isEnabled(),'Host-backed preference acknowledgement did not settle');
 phase='iteration-'+iteration+':font-before-reload';
 await readDurableFont('before-reload',themeFontBefore+1);
 // Fresh navigation reconnects the real application with the server-minted cookie.
 await dialog.getByRole('button',{name:'Close',exact:true}).click();await dialog.waitFor({state:'hidden'});
 await navigateReady(()=>page.reload({waitUntil:'domcontentloaded'}),'reload');await settings().waitFor({state:'visible'});
 await openSettings();phase='iteration-'+iteration+':general-after-reload';await page.getByRole('dialog').getByRole('button',{name:'General',exact:true}).click();
 // Reload must preserve both the actual Custom palette and the acknowledged font.
 phase='iteration-'+iteration+':theme-after-reload';
 await readDurableFont('after-reload',themeFontBefore+1);
 await appearance().waitFor({state:'visible'});await settleAppearance('custom-light',false);
 await page.waitForFunction(expected=>parseFloat(getComputedStyle(document.body).getPropertyValue('--dsh-content-font-size'))===expected,themeFontBefore+1);
 const themeReload=await readAppearance();assert.equal(themeReload.base.toLowerCase(),'#f4f7fa');assert.equal(themeReload.background,'rgb(244, 247, 250)');assertTokens(themeReload.tokens,expectedThemeTokens);
 await appearance().selectOption('light');await settleAppearance('light',false);assert.equal((await readAppearance()).background,themeLight.background,'Leaving Custom retained its palette');assertTokens((await readAppearance()).tokens,themeLight.tokens);
 phase='iteration-'+iteration+':font-decrease-ack';
 await changeFontAndVerifySaved('Decrease font size',themeFontBefore,'decrease');
 await appearance().selectOption('system');await page.emulateMedia({colorScheme:'light'});await settleAppearance('system',false);
 await coding().waitFor({state:'visible'});assert.equal(await coding().isChecked(),!before,'Host owner preference did not persist across reload');
 await page.getByRole('dialog').getByRole('button',{name:'Close',exact:true}).click();
 await selector().waitFor({state:'visible'});await selector().click();const reopened=page.getByRole('menuitem',{name:/^Model/});if(await reopened.count())await reopened.click();await page.getByRole('group',{name:'Model and reasoning effort',exact:true}).locator('[data-model-id="deepseek-v4.1-flash"]').waitFor({state:'visible'});
 assert.deepEqual(pageErrors,[]);assert.deepEqual(inferenceRequests,[]);
 if(iteration===1)assert.equal(delayedSessionLists,0);else assert(delayedSessionLists>=1,'Controlled initialization case was not exercised');
 iterations.push({iteration,fontPersistenceReceipts,theme:{light:themeLight,dark:themeDark,custom:themeCustom,afterReload:themeReload,systemFollowsOS:true,fontWritePreservedCustom:true,nativeExitRestored:true},initialSessionAnswerVerified:true,delayedSessionLists,settingsPreferencePersisted:true,pageErrors,blockedExternalOrigins:[...new Set(externalRequests)]});
 await context.close();
 }
 await browser.close();browser=null;
 spawnSync('docker',['stop','--time','5',name],{encoding:'utf8',timeout:10000});
 for(let n=0;n<30&&!closed;n++)await sleep(100);
 const receipts=log.split(/\r?\n/).flatMap(line=>{try{const item=JSON.parse(line);return typeof item.modelRequests==='number'?[item]:[]}catch{return []}});
 assert(receipts.length,'Mock inference counter receipt missing');assert(receipts.every(item=>item.modelRequests===0),'App attempted inference during UI qualification');
 const result={iterations,actualNativeThemePluginBrowser:true,qualifiedThemeClientSHA256:ready.themeBundle.clientSHA256,themeAppearanceVerifiedAllIterations:true,allIterationsRequired:true,actualUpstreamBrowser:true,ownerScopeOnly:true,syntheticNonLoopbackTrustedHost:true,tlsAcceptance:false,managedModelSelectorDOM:rows,hostBackedModelsSettingsRendered:true,reloadReconnect:true,pageErrors:[],blockedExternalOrigins:[...new Set(iterations.flatMap(item=>item.blockedExternalOrigins))],modelRequests:0,hostOwnerPreferencePersistedAcrossReload:true,settingsWritesTested:true,ordinaryPeerPolicyTested:false,inferenceAcceptance:false};
 fs.writeFileSync(path.join(output,'result.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result));
 }catch(error){
 if(page&&!page.isClosed()){
  await page.screenshot({path:path.join(output,'upstream-browser-failure.png'),fullPage:true}).catch(()=>{});
  const snapshot=await page.locator('body').ariaSnapshot().catch(()=>'(DOM unavailable)');
  fs.writeFileSync(path.join(output,'browser-failure.json'),JSON.stringify({phase,error:error.message,diagnostics:browserDiagnostics.slice(-30),dom:snapshot.replaceAll('synthetic-browser-no-inference','[SYNTHETIC KEY REDACTED]').slice(-24000)},null,2)+'\n');
 }
 throw error;
 }finally{if(browser)await browser.close();spawnSync('docker',['rm','--force',name],{stdio:'ignore',timeout:10000});}})().catch(error=>{console.error(error.message);process.exitCode=1;});
