'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {install,FILES,CLIENT_SHA,PRIOR,LEGACY_PRIOR}=require('../scripts/install_native_theme_profile.cjs');
const source=path.resolve(__dirname,'../plugins/custom-theme'),prior010=path.resolve(__dirname,'fixtures/bot-theme-0.1.0'),root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-native-theme-test-'));
const results=[];
function state(name){const p=path.join(root,name);fs.mkdirSync(p,{recursive:true});return p;}
function test(name,fn){fn();results.push(name);}
// The image ships the package read-only and copyFileSync keeps that mode, so fixtures that are tampered with
// below are made writable first. Installed copies stay read-only, as in a real workspace profile.
try{
 test('Fresh registration leaves session/credential sentinels unread and unchanged',()=>{
  const h=state('fresh'),forbidden=[path.join(h,'.credentials.yaml'),path.join(h,'sessions','sentinel')];fs.mkdirSync(path.join(h,'sessions'));for(const p of forbidden)fs.writeFileSync(p,'SYNTHETIC_UNREAD_SENTINEL');
  const read=fs.readFileSync;fs.readFileSync=function(p,...args){if(forbidden.includes(path.resolve(p)))throw Error('Installer read forbidden sentinel');return read.call(this,p,...args);};
  let r;try{r=install(h,source);}finally{fs.readFileSync=read;}
  assert.equal(r.changed,true);assert.equal(r.clientSHA256,CLIENT_SHA);assert.equal(r.historyOrCredentialsRead,false);
  const m=JSON.parse(fs.readFileSync(path.join(h,'profiles/web/package.json')));assert.deepEqual(m.dsh.profile.bundles,['@dsh-ext/custom-theme']);
  for(const p of forbidden)assert.equal(fs.readFileSync(p,'utf8'),'SYNTHETIC_UNREAD_SENTINEL');
 });
 test('Existing manifest fields and exact rollback bytes are preserved',()=>{
  const h=state('existing'),p=path.join(h,'profiles/web/package.json');fs.mkdirSync(path.dirname(p),{recursive:true});
  const m={name:'existing-profile',private:true,dependencies:{fixture:'file:./fixture'},custom:{preserve:true},dsh:{profile:{bundles:['fixture-plugin'],other:'keep'}}},raw=JSON.stringify(m,null,4)+'\n';fs.writeFileSync(p,raw);
  const r=install(h,source),next=JSON.parse(fs.readFileSync(p,'utf8'));assert.equal(fs.readFileSync(r.backup,'utf8'),raw);next.dsh.profile.bundles=['fixture-plugin'];assert.deepEqual(next,m);
 });
 test('Repeated registration is byte-idempotent and does not rewrite manifest',()=>{
  const h=state('repeat');install(h,source);const p=path.join(h,'profiles/web/package.json'),raw=fs.readFileSync(p),mtime=fs.statSync(p).mtimeMs;
  const r=install(h,source);assert.equal(r.changed,false);assert.equal(r.profileChanged,false);assert.equal(r.packageInstalled,false);assert(fs.readFileSync(p).equals(raw));assert.equal(fs.statSync(p).mtimeMs,mtime);
 });
 test('Unqualified client is rejected before state writes',()=>{
  const h=state('bad-client'),s=state('bad-package');for(const f of FILES){const out=path.join(s,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(source,f),out);}fs.chmodSync(path.join(s,'lib/client.js'),0o600);fs.writeFileSync(path.join(s,'lib/client.js'),'unqualified fixture');
  assert.throws(()=>install(h,s),/Unqualified client/);assert.deepEqual(fs.readdirSync(h),[]);
 });
 test('A different existing managed package requires explicit upgrade review',()=>{
  const h=state('existing-package');install(h,source);const p=path.join(h,'profiles/web/package.json'),raw=fs.readFileSync(p);fs.chmodSync(path.join(h,'profiles/web/node_modules/@dsh-ext/custom-theme/lib/client.js'),0o600);fs.writeFileSync(path.join(h,'profiles/web/node_modules/@dsh-ext/custom-theme/lib/client.js'),'different fixture');
  assert.throws(()=>install(h,source),/differs/);assert(fs.readFileSync(p).equals(raw));
 });
 test('A profile directory symlink is refused without modifying its target',()=>{
  const h=state('symlink'),target=state('symlink-target');fs.writeFileSync(path.join(target,'sentinel'),'keep');fs.symlinkSync(target,path.join(h,'profiles'),process.platform==='win32'?'junction':'dir');
  assert.throws(()=>install(h,source),/symlink/);assert.deepEqual(fs.readdirSync(target),['sentinel']);
 });
 test('Package source inside state is rejected',()=>{
  const h=state('nested'),s=path.join(h,'package');fs.mkdirSync(s);assert.throws(()=>install(h,s),/outside state/);assert.deepEqual(fs.readdirSync(h),['package']);
 });
 test('Malformed bundle inventory is refused without changing profile',()=>{
  const h=state('invalid-schema'),p=path.join(h,'profiles/web/package.json');fs.mkdirSync(path.dirname(p),{recursive:true});const raw='{"dsh":{"profile":{"bundles":["duplicate","duplicate"]}}}\n';fs.writeFileSync(p,raw);assert.throws(()=>install(h,source),/unique bundle/);assert.equal(fs.readFileSync(p,'utf8'),raw);assert(!fs.existsSync(path.join(h,'profiles/web/node_modules')));
 });
 test('Concurrent manifest edits are retained and never overwritten',()=>{
  const h=state('concurrent'),p=path.join(h,'profiles/web/package.json');fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,'{"name":"before"}\n');const write=fs.writeFileSync,concurrent='{"name":"concurrent-owner"}\n';let injected=false;
  fs.writeFileSync=function(file,...args){const r=write.call(this,file,...args);if(String(file).includes('.theme-package-')){write.call(this,p,concurrent);injected=true;}return r;};
  try{assert.throws(()=>install(h,source),/Concurrent profile/);}finally{fs.writeFileSync=write;}
  assert(injected);assert.equal(fs.readFileSync(p,'utf8'),concurrent);
 });
 test('The shipped client meets the 0.4.3 contract: native Appearance untouched, distinct Light/Dark palettes, theme-specific logo pairs, host-sized logo slots, the home headline and badge hidden whenever it loads, no embedded image payload, no HTML injection, no institution name',()=>{
  const client=fs.readFileSync(path.join(source,'lib/client.js'),'utf8');
  assert.equal(JSON.parse(fs.readFileSync(path.join(source,'package.json'),'utf8')).version,'0.4.3');
  assert.equal(PRIOR['0.3.5'],'561f7cf60bb4f916eb66b914849a66fb8ea27a12031f566e7819a1fa1761ada7','The exact deployed 0.3.5 bundle is an admitted rollback-preserving predecessor');
  assert.equal(PRIOR['0.4.2'],'1a6a8486ebb6081dfea08a84d3957ac58bf364ba308bcd1f64d6243520e26462','The exact deployed 0.4.2 bundle is admitted for rollback-preserving upgrade');
  assert(!/data:image\/[a-z+]+;base64,[A-Za-z0-9+\/]{64,}/.test(client),'The client embeds an image payload');
  assert(!/innerHTML|dangerouslySetInnerHTML|insertAdjacentHTML/.test(client),'The client injects HTML');
  assert(!/bot\.or\.th|bot_platform/i.test(client),'The client names the institution');
  assert(!/manual\/brand|DEFAULT_LOGO|logo\.png/.test(client),'The client carries a built-in or deployment logo path');
  assert(client.includes('/api/theme-default-logo'),'The deployment default logo comes from the gateway setting');
  assert(!/https?:\/\//.test(client),'The client bundle carries a URL');
  assert(!client.includes('Bank of Thailand'),'The client names the institution');
  assert(!/id:\s*['"]appearance['"]/.test(client),'The native Appearance row is replaced');
  assert.match(client,/name:\s*'settings\.general\.item',\s*id:\s*'custom-theme'/);
  for(const slot of ['sidebar.brand.mark','sidebar.brand.name','conversation.hero.brand.mark'])assert(client.includes("'"+slot+"'"),slot+' is handled');
  assert(client.includes('[class$="_headline"]>[class$="_titleGroup"]{display:none}'),'The hero headline and badge rule is present');
  assert.match(client,/if\s*\(want\s*&&\s*!off\)\s*off\s*=\s*ctx\.slots\.register\(\{name,\s*priority:\s*-10/,'Brand slots register only while wanted, at priority -10');
  assert(client.includes('darkTokens:DARK_THEME_TOKENS'),'Dark mode receives a distinct governed palette');
  assert(client.includes('Math.max(Number(size) || 24, 1)'),'Brand marks respect the host surface geometry');
  assert(client.includes('const height = 24'),'Open-sidebar brand name matches the native 24-pixel row');
 });
 test('An exact 0.1.0 install is upgraded in place; the old copy is kept and the run is repeatable',()=>{
  const h=state('upgrade'),dest=path.join(h,'profiles/web/node_modules/@bot/dsh-theme');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior010,f),out);}
  fs.writeFileSync(path.join(h,'profiles/web/package.json'),JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n');
  const sum=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  assert.equal(sum(path.join(dest,'lib/client.js')),LEGACY_PRIOR['0.1.0']);
  const r=install(h,source);
  assert.equal(r.upgradedFrom,'0.1.0');assert.equal(r.packageInstalled,true);assert.equal(r.profileChanged,true);
  assert.equal(fs.existsSync(dest),false,'The old package folder is moved aside');assert.deepEqual(JSON.parse(fs.readFileSync(path.join(h,'profiles/web/package.json'))).dsh.profile.bundles,['@dsh-ext/custom-theme']);
  assert.equal(sum(path.join(dest,'../../@dsh-ext/custom-theme/lib/client.js')),CLIENT_SHA);
  assert.equal(sum(path.join(h,'.native-theme-rollback','package-0.1.0-'+LEGACY_PRIOR['0.1.0'].slice(0,12),'lib/client.js')),LEGACY_PRIOR['0.1.0']);
  const again=install(h,source);assert.equal(again.changed,false);assert.equal(again.upgradedFrom,null);
 });
 test('An exact 0.2.0 install is upgraded in place; the old copy is kept',()=>{
  const h=state('upgrade-020'),dest=path.join(h,'profiles/web/node_modules/@bot/dsh-theme'),prior=path.resolve(__dirname,'fixtures/bot-theme-0.2.0');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior,f),out);}
  fs.writeFileSync(path.join(h,'profiles/web/package.json'),JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n');
  const sum=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  assert.equal(sum(path.join(dest,'lib/client.js')),LEGACY_PRIOR['0.2.0']);
  const r=install(h,source);assert.equal(r.upgradedFrom,'0.2.0');assert.equal(sum(path.join(dest,'../../@dsh-ext/custom-theme/lib/client.js')),CLIENT_SHA);
  assert.equal(sum(path.join(h,'.native-theme-rollback','package-0.2.0-'+LEGACY_PRIOR['0.2.0'].slice(0,12),'lib/client.js')),LEGACY_PRIOR['0.2.0']);
  assert.equal(install(h,source).changed,false);
 });
 test('An exact 0.3.0 install is upgraded in place; the old copy is kept',()=>{
  const h=state('upgrade-030'),dest=path.join(h,'profiles/web/node_modules/@bot/dsh-theme'),prior=path.resolve(__dirname,'fixtures/bot-theme-0.3.0');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior,f),out);}
  fs.writeFileSync(path.join(h,'profiles/web/package.json'),JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n');
  const sum=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  assert.equal(sum(path.join(dest,'lib/client.js')),LEGACY_PRIOR['0.3.0']);
  const r=install(h,source);assert.equal(r.upgradedFrom,'0.3.0');assert.equal(sum(path.join(dest,'../../@dsh-ext/custom-theme/lib/client.js')),CLIENT_SHA);
  assert.equal(sum(path.join(h,'.native-theme-rollback','package-0.3.0-'+LEGACY_PRIOR['0.3.0'].slice(0,12),'lib/client.js')),LEGACY_PRIOR['0.3.0']);
  assert.equal(install(h,source).changed,false);
 });
 test('An exact 0.3.1 install is upgraded in place; the old copy is kept',()=>{
  const h=state('upgrade-031'),dest=path.join(h,'profiles/web/node_modules/@bot/dsh-theme'),prior=path.resolve(__dirname,'fixtures/bot-theme-0.3.1');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior,f),out);}
  fs.writeFileSync(path.join(h,'profiles/web/package.json'),JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n');
  const sum=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  assert.equal(sum(path.join(dest,'lib/client.js')),LEGACY_PRIOR['0.3.1']);
  const r=install(h,source);assert.equal(r.upgradedFrom,'0.3.1');assert.equal(sum(path.join(dest,'../../@dsh-ext/custom-theme/lib/client.js')),CLIENT_SHA);
  assert.equal(sum(path.join(h,'.native-theme-rollback','package-0.3.1-'+LEGACY_PRIOR['0.3.1'].slice(0,12),'lib/client.js')),LEGACY_PRIOR['0.3.1']);
  assert.equal(install(h,source).changed,false);
 });
 test('An exact 0.3.2 install is upgraded in place; the old copy is kept',()=>{
  const h=state('upgrade-032'),dest=path.join(h,'profiles/web/node_modules/@bot/dsh-theme'),prior=path.resolve(__dirname,'fixtures/bot-theme-0.3.2');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior,f),out);}
  fs.writeFileSync(path.join(h,'profiles/web/package.json'),JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n');
  const sum=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  assert.equal(sum(path.join(dest,'lib/client.js')),LEGACY_PRIOR['0.3.2']);
  const r=install(h,source);assert.equal(r.upgradedFrom,'0.3.2');assert.equal(sum(path.join(dest,'../../@dsh-ext/custom-theme/lib/client.js')),CLIENT_SHA);
  assert.equal(sum(path.join(h,'.native-theme-rollback','package-0.3.2-'+LEGACY_PRIOR['0.3.2'].slice(0,12),'lib/client.js')),LEGACY_PRIOR['0.3.2']);
  assert.equal(install(h,source).changed,false);
 });
 test('An exact 0.3.3 install is upgraded in place; the old copy is kept',()=>{
  const h=state('upgrade-033'),dest=path.join(h,'profiles/web/node_modules/@bot/dsh-theme'),prior=path.resolve(__dirname,'fixtures/bot-theme-0.3.3');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior,f),out);}
  fs.writeFileSync(path.join(h,'profiles/web/package.json'),JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n');
  const sum=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
  assert.equal(sum(path.join(dest,'lib/client.js')),LEGACY_PRIOR['0.3.3']);
  const r=install(h,source);assert.equal(r.upgradedFrom,'0.3.3');assert.equal(sum(path.join(dest,'../../@dsh-ext/custom-theme/lib/client.js')),CLIENT_SHA);
  assert.equal(sum(path.join(h,'.native-theme-rollback','package-0.3.3-'+LEGACY_PRIOR['0.3.3'].slice(0,12),'lib/client.js')),LEGACY_PRIOR['0.3.3']);
  assert.equal(install(h,source).changed,false);
 });
 test('A changed copy under the earlier name is refused and nothing moves',()=>{
  const h=state('legacy-changed'),dest=path.join(h,'profiles/web/node_modules/@bot/dsh-theme'),prior=path.resolve(__dirname,'fixtures/bot-theme-0.3.3');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior,f),out);}
  fs.chmodSync(path.join(dest,'lib/client.js'),0o600);fs.appendFileSync(path.join(dest,'lib/client.js'),'\n// edited');
  const manifest=JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n';fs.writeFileSync(path.join(h,'profiles/web/package.json'),manifest);
  assert.throws(()=>install(h,source),/explicit upgrade review required/);
  assert(fs.existsSync(dest),'The edited copy stays where it is');assert.equal(fs.readFileSync(path.join(h,'profiles/web/package.json'),'utf8'),manifest);
  assert(!fs.existsSync(path.join(h,'profiles/web/node_modules/@dsh-ext/custom-theme')),'Nothing new is installed');
 });
 test('Rollback: the kept copy and the saved manifest restore the earlier state, and migrating again is repeatable and idempotent',()=>{
  const h=state('legacy-rollback'),nm=path.join(h,'profiles/web/node_modules'),dest=path.join(nm,'@bot/dsh-theme'),prior=path.resolve(__dirname,'fixtures/bot-theme-0.3.3');
  for(const f of FILES){const out=path.join(dest,f);fs.mkdirSync(path.dirname(out),{recursive:true});fs.copyFileSync(path.join(prior,f),out);}
  const manifest=JSON.stringify({name:'p',dsh:{profile:{bundles:['@bot/dsh-theme']}}},null,2)+'\n';fs.writeFileSync(path.join(h,'profiles/web/package.json'),manifest);
  const sum=q=>crypto.createHash('sha256').update(fs.readFileSync(q)).digest('hex');
  assert.equal(install(h,source).upgradedFrom,'0.3.3');
  // roll back the way an operator would: put the kept copy and the saved manifest back, remove the new package
  const kept=path.join(h,'.native-theme-rollback','package-0.3.3-'+LEGACY_PRIOR['0.3.3'].slice(0,12));
  fs.rmSync(path.join(nm,'@dsh-ext'),{recursive:true,force:true});fs.cpSync(kept,dest,{recursive:true});
  const saved=fs.readdirSync(path.join(h,'.native-theme-rollback')).filter(x=>!x.startsWith('package-')).map(x=>path.join(h,'.native-theme-rollback',x,'web-package.json')).find(fs.existsSync);
  fs.writeFileSync(path.join(h,'profiles/web/package.json'),fs.readFileSync(saved));
  assert.equal(sum(path.join(dest,'lib/client.js')),LEGACY_PRIOR['0.3.3']);assert.equal(fs.readFileSync(path.join(h,'profiles/web/package.json'),'utf8'),manifest);
  const again=install(h,source);assert.equal(again.upgradedFrom,'0.3.3');assert.equal(sum(path.join(nm,'@dsh-ext/custom-theme/lib/client.js')),CLIENT_SHA);
  assert.equal(install(h,source).changed,false);
 });
 console.log(JSON.stringify({passed:results.length,total:18,results,scope:'Real temporary filesystem, no live state/profile or provider calls'}));
 module.exports={passed:results.length,total:18,results};
}finally{
 const resolved=path.resolve(root),prefix=path.resolve(os.tmpdir())+path.sep+'dsh-native-theme-test-';
 if(!resolved.startsWith(prefix))throw Error('Refuse cleanup outside owned temporary root');
 fs.rmSync(resolved,{recursive:true,force:true});
}
