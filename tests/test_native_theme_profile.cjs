'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {install,FILES,CLIENT_SHA}=require('../scripts/install_native_theme_profile.cjs');
const source=path.resolve(__dirname,'../plugins/dsh-theme-custom-light'),root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-native-theme-test-'));
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
  const m=JSON.parse(fs.readFileSync(path.join(h,'profiles/web/package.json')));assert.deepEqual(m.dsh.profile.bundles,['dsh-theme-custom-light']);
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
  const h=state('existing-package');install(h,source);const p=path.join(h,'profiles/web/package.json'),raw=fs.readFileSync(p);fs.chmodSync(path.join(h,'profiles/web/node_modules/dsh-theme-custom-light/lib/client.js'),0o600);fs.writeFileSync(path.join(h,'profiles/web/node_modules/dsh-theme-custom-light/lib/client.js'),'different fixture');
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
 console.log(JSON.stringify({passed:results.length,total:9,results,scope:'Real temporary filesystem, no live state/profile or provider calls'}));
 module.exports={passed:results.length,total:9,results};
}finally{
 const resolved=path.resolve(root),prefix=path.resolve(os.tmpdir())+path.sep+'dsh-native-theme-test-';
 if(!resolved.startsWith(prefix))throw Error('Refuse cleanup outside owned temporary root');
 fs.rmSync(resolved,{recursive:true,force:true});
}
