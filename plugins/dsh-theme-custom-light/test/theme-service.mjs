import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
const base=path.dirname(fileURLToPath(import.meta.url));
const requireTest=createRequire(import.meta.url);
const themeCode=await fs.readFile(requireTest.resolve('@deepseek-ai/dsh-client-ui-theme/client'),'utf8');
const {SlotCore}=await import(pathToFileURL(requireTest.resolve('@deepseek-ai/dsh-client-ui-slots')).href);
const packageDir=path.resolve(base,'..');
const pluginCode=await fs.readFile(path.join(packageDir,'lib/client.js'),'utf8');
const CUSTOM='custom-light', KEY='dsh-theme-custom-light/selection/v1';
const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function make({preference='system',saved,loading=false,brokenStorage=false}={}) {
 const events=new Map(), effects=[], hostListeners=new Set(), mediaListeners=new Set();
 const nativeDisposers=[], pluginDisposers=[]; let activeEffects=nativeDisposers;
 const defaults={fontSize:14,codeFontSize:13,terminalFontSize:13,textFontFamily:'',codeFontFamily:'',terminalFontFamily:''};
 let value=loading?undefined:{...defaults,preference};
 const writes=[]; const memory=new Map(saved?[[KEY,saved]]:[]);
 const storage={getItem:k=>{if(brokenStorage)throw Error('blocked');return memory.get(k)??null;},setItem:(k,v)=>{if(brokenStorage)throw Error('blocked');memory.set(k,v);}};
 const media={matches:false,addEventListener:(_n,l)=>mediaListeners.add(l),removeEventListener:(_n,l)=>mediaListeners.delete(l)};
 const host={getSnapshot:()=>({status:value?'ready':'loading',value,writable:true}),subscribe:l=>{hostListeners.add(l);return()=>hostListeners.delete(l);},set:async(k,v)=>{writes.push([k,v]);value={...value,[k]:v};for(const l of [...hostListeners])l();},mutate:async(ops)=>{for(const o of ops){writes.push([o.path[0],o.value]);value={...value,[o.path[0]]:o.value};}for(const l of [...hostListeners])l();}};
 const ctx={effect:f=>{const d=f();if(typeof d==='function')activeEffects.push(d);},inject:()=>{},on:(event,l)=>{const a=events.get(event)??new Set();a.add(l);events.set(event,a);return()=>a.delete(l);},emit:(event,v)=>{for(const l of [...(events.get(event)??[])])l(v);}};
 const React={createContext:()=>({}),forwardRef:f=>f,memo:f=>f,createElement:(type,props,...children)=>({type,props:props??{},children}),useState:f=>[typeof f==='function'?f():f,()=>{}],useEffect:()=>{}};
 let moduleExports; const runtime=vm.createContext({queueMicrotask,console,matchMedia:()=>media,localStorage:storage,window:{__ModuleLoader__:{load:spec=>{moduleExports=spec.factory(name=>name==='react'?React:name==='@deepseek-ai/dsh-client-store'?{defineStore:x=>x}:{});}}}});
 vm.runInContext(themeCode,runtime);ctx.theme=new moduleExports.ThemeRuntime(ctx,host);
 const core=new SlotCore();core.register({name:'root',children:{'settings.general.item':{kind:'list',scope:'root'}}},()=>null);
 const original=()=>null;core.register({name:'settings.general.item',id:'appearance',order:10},original);
 const fonts=()=>null;core.register({name:'settings.general.item',id:'font-size',order:11},fonts);
 ctx.configForms={get:ns=>{assert.equal(ns,'ui-theme');return host;}};
 ctx.slots={inject:(_n,f)=>{const d=f();if(typeof d==='function')pluginDisposers.push(d);},register:(options,component)=>core.register(options,component)};
 vm.runInContext(pluginCode,runtime);activeEffects=pluginDisposers;moduleExports.apply(ctx);
 const appearance=()=>core.entriesOfSlot('settings.general.item').find(e=>e.options.id==='appearance');
 const controller=appearance().inject().controller;
 return {ctx,core,host,writes,memory,media,controller,original,fonts,appearance,
 flip:dark=>{media.matches=dark;for(const l of [...mediaListeners])l();},
 adopt:next=>{value={...defaults,...next};for(const l of [...hostListeners])l();},
 unload:()=>{for(const d of [...pluginDisposers].reverse())d();},
 clean:()=>{for(const d of [...nativeDisposers].reverse())d();}};
}
const results=[];
async function test(name,fn){try{await fn();results.push({name,pass:true});}catch(e){results.push({name,pass:false,error:e.message});}}
const tokens=s=>JSON.stringify(s.active.tokens);
await test('Native Light and Dark keep their original empty token definitions',async()=>{const f=make();for(const id of ['light','dark']){f.controller.choose(id);await settle();assert.equal(f.ctx.theme.getTheme().active.id,id);assert.equal(tokens(f.ctx.theme.getTheme()),'{}');}f.unload();f.clean();});
await test('System follows both OS light and dark without custom overrides',async()=>{const f=make();f.controller.choose('system');f.flip(true);assert.equal(f.ctx.theme.getTheme().active.id,'dark');f.flip(false);assert.equal(f.ctx.theme.getTheme().active.id,'light');assert.equal(tokens(f.ctx.theme.getTheme()),'{}');f.unload();f.clean();});
await test('No default selection change and no storage write on first install',async()=>{const f=make({preference:'dark'});await settle();assert.equal(f.ctx.theme.getTheme().preference,'dark');assert.equal(f.memory.size,0);assert.equal(f.writes.length,0);f.unload();f.clean();});
await test('Custom is explicitly selected, light-semantic, and carries 32 preserved alias tokens',async()=>{const f=make();f.controller.choose(CUSTOM);await settle();const s=f.ctx.theme.getTheme();assert.equal(s.preference,CUSTOM);assert.equal(s.active.colorScheme,'light');assert.equal(Object.keys(s.active.tokens).length,32);assert.equal(s.active.tokens['--dsw-alias-button-primary-fill'],'#003366');f.flip(true);assert.equal(f.ctx.theme.getTheme().active.id,CUSTOM);f.unload();f.clean();});
await test('Custom survives font writes and asynchronous native host adoption',async()=>{const f=make();f.controller.choose(CUSTOM);f.ctx.theme.setFontSize('text',f.ctx.theme.getTheme().fontSizes.text+1);await settle();assert.equal(f.ctx.theme.getTheme().preference,CUSTOM);assert(f.writes.some(([k])=>k==='fontSize'));f.adopt({preference:'dark',fontSize:16});await settle();assert.equal(f.ctx.theme.getTheme().preference,CUSTOM);f.unload();f.clean();});
await test('Custom restores on reload even when native settings load later',async()=>{const saved=JSON.stringify({version:1,custom:true,fallback:'dark'});const f=make({saved,loading:true});await settle();assert.equal(f.ctx.theme.getTheme().preference,CUSTOM);f.adopt({preference:'dark'});await settle();assert.equal(f.ctx.theme.getTheme().preference,CUSTOM);f.unload();f.clean();});
await test('Each native choice exits Custom and remains native after host echo',async()=>{for(const id of ['light','dark','system']){const f=make();f.controller.choose(CUSTOM);f.controller.choose(id);await settle();assert.equal(f.ctx.theme.getTheme().preference,id);assert.equal(JSON.parse(f.memory.get(KEY)).custom,false);assert.equal(tokens(f.ctx.theme.getTheme()),'{}');f.unload();f.clean();}});
await test('Queued restoration cannot undo a later native selection',async()=>{const f=make();f.controller.choose(CUSTOM);f.adopt({preference:'dark'});f.controller.choose('light');await settle();assert.equal(f.ctx.theme.getTheme().preference,'light');f.unload();f.clean();});
await test('Unload restores the native row, preference and untouched font row',async()=>{const f=make({preference:'dark'});f.controller.choose(CUSTOM);await settle();assert.notEqual(f.appearance().component,f.original);assert.equal(f.core.entriesOfSlot('settings.general.item').find(e=>e.options.id==='font-size').component,f.fonts);f.unload();await settle();assert.equal(f.ctx.theme.getTheme().preference,'dark');assert.equal(f.appearance().component,f.original);assert(!f.ctx.theme.getTheme().themes.some(t=>t.id===CUSTOM));f.clean();});
await test('Unload before pending restoration does not reactivate Custom',async()=>{const f=make();f.controller.choose(CUSTOM);f.adopt({preference:'dark'});f.unload();await settle();assert.equal(f.ctx.theme.getTheme().preference,'dark');f.clean();});
await test('Foreign plugin token layer is preserved during selection and unload',async()=>{const f=make();const remove=f.ctx.theme.overrideTokens('foreign-plugin',{'--dsw-alias-label-primary':{light:'#112233',dark:'#ddeeff'}});f.controller.choose(CUSTOM);assert.equal(f.ctx.theme.getTheme().active.tokens['--dsw-alias-label-primary'],'#112233');f.unload();await settle();assert.equal(f.ctx.theme.getTheme().active.tokens['--dsw-alias-label-primary'],'#112233');remove();f.clean();});
await test('A foreign registered custom theme is not overridden by restoration',async()=>{const f=make();const remove=f.ctx.theme.register({id:'foreign-custom',colorScheme:'dark',tokens:{}});f.controller.choose(CUSTOM);f.ctx.theme.setTheme('foreign-custom');await settle();assert.equal(f.ctx.theme.getTheme().preference,'foreign-custom');assert.equal(f.controller.getSnapshot().custom,false);f.unload();assert.equal(f.ctx.theme.getTheme().preference,'foreign-custom');remove();f.clean();});
await test('Blocked or malformed browser storage keeps native mode operable',async()=>{for(const setup of [{brokenStorage:true},{saved:'{not-json'},{saved:JSON.stringify({version:1,custom:true,fallback:'injected-id'})}]){const f=make(setup);await settle();assert.equal(f.ctx.theme.getTheme().preference,'system');f.controller.choose('dark');await settle();assert.equal(f.ctx.theme.getTheme().preference,'dark');f.unload();f.clean();}});
await test('Unknown choice is rejected before settings or theme changes',async()=>{const f=make();assert.throws(()=>f.controller.choose('unknown'));assert.equal(f.writes.length,0);assert.equal(f.memory.size,0);f.unload();f.clean();});
await test('Published module-loader bundle exposes four accessible selector choices',async()=>{const f=make();const row=f.appearance().component(f.appearance().inject());const label=row.children[0];const select=label.children[1];assert.equal(select.type,'select');assert.equal(select.props['aria-label'],'Appearance');assert.deepEqual(Array.from(select.children,c=>c.props.value),['light','dark','system',CUSTOM]);select.props.onChange({target:{value:CUSTOM}});await settle();assert.equal(f.ctx.theme.getTheme().preference,CUSTOM);f.unload();f.clean();});
const report={at:new Date().toISOString(),scope:'In-process service compatibility; exact official published 0.2.1-rc.2 ThemeRuntime and SlotCore, DOM/React renderer and server transport mocked.',passed:results.filter(x=>x.pass).length,total:results.length,results,notVerified:['Real DSH browser rendering or screenshot','Server settings transport and actual ModuleLoader dependency resolution','Gateway removal in running workload','RKE2 Test/Production rollout or running image digest','Full pixel parity for CSS rules outside the 32 supported alias tokens']};
console.log(JSON.stringify(report));
if(report.passed!==report.total)throw new Error('Theme compatibility checks failed');
export {report};
