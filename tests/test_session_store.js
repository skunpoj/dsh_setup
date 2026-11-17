const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),crypto=require('crypto');
const {SessionStore,TTL_MS}=require('../scripts/session_store');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-session-store-'));
const token=()=>crypto.randomBytes(24).toString('hex');
let now=2000000000000;const clock=()=>now;
const row=user=>({user,internet:'off',created:now,accountStamp:'a'.repeat(64)});
try{
 const file=path.join(root,'sessions.json'),a=token(),b=token();
 let s=new SessionStore(file,{clock});s.set(a,row('alice'));s.set(b,row('bobby'));
 const bytes=fs.readFileSync(file,'utf8');assert(!bytes.includes(a)&&!bytes.includes(b));assert.equal(s.size,2);
 if(process.platform!=='win32')assert.equal(fs.statSync(file).mode&0o777,0o600);
 s=new SessionStore(file,{clock});assert.equal(s.get(a).user,'alice');assert.equal(s.get(b).user,'bobby');
 // A stored digest is not accepted as a bearer credential.
 assert.equal(s.get(JSON.parse(bytes).sessions[0].digest),undefined);
 s.delete(a);s=new SessionStore(file,{clock});assert(!s.has(a));assert(s.has(b));
 s.removeUser('bobby');s=new SessionStore(file,{clock});assert.equal(s.size,0);
 s.set(a,row('alice'));now+=TTL_MS;assert.equal(s.get(a),undefined);assert.equal(new SessionStore(file,{clock}).size,0);
 now+=1;s.set(b,row('bobby'));const invalid=new SessionStore(file,{clock,verify:()=>false});assert(!invalid.has(b));
 const retained=fs.readFileSync(file);fs.writeFileSync(file,'{"version":1,');assert.throws(()=>new SessionStore(file,{clock}));assert.equal(fs.readFileSync(file,'utf8'),'{"version":1,');fs.writeFileSync(file,retained);
 if(process.platform!=='win32'){
  fs.chmodSync(file,0o644);assert.throws(()=>new SessionStore(file,{clock}));fs.chmodSync(file,0o600);
  const link=path.join(root,'linked.json');fs.symlinkSync(file,link);assert.throws(()=>new SessionStore(link,{clock}));fs.unlinkSync(link);
  fs.linkSync(file,link);assert.throws(()=>new SessionStore(file,{clock}));fs.unlinkSync(link);
  const unsafe=path.join(root,'unsafe');fs.mkdirSync(unsafe);fs.chmodSync(unsafe,0o777);assert.throws(()=>new SessionStore(path.join(unsafe,'sessions.json'),{clock}));
  const directoryLink=path.join(root,'directory-link');fs.symlinkSync(root,directoryLink);assert.throws(()=>new SessionStore(path.join(directoryLink,'sessions.json'),{clock}));fs.unlinkSync(directoryLink);
 }
 const parentFile=path.join(root,'not-directory');fs.writeFileSync(parentFile,'fixture');const broken=new SessionStore(path.join(root,'new.json'),{clock});broken.file=path.join(parentFile,'sessions.json');assert.throws(()=>broken.set(token(),row('alice')));assert.equal(broken.size,0);
 // Old v1 rows survive alongside durable, target-scoped standalone sessions.
 const legacy=token(),agent=token();s=new SessionStore(file,{clock});s.set(legacy,row('alice'));const originalV1=fs.readFileSync(file);
 s.set(agent,{...row('alice'),runtime:'claude-code',targetKey:'1'.repeat(24)});
 const backups=fs.readdirSync(root).filter(n=>n.startsWith('sessions.json.before-standalone-'));assert.equal(backups.length,1);assert.deepEqual(fs.readFileSync(path.join(root,backups[0])),originalV1);
 s=new SessionStore(file,{clock});assert.equal(s.get(legacy).user,'alice');assert.equal(s.get(agent).runtime,'claude-code');assert.equal(s.get(agent).targetKey,'1'.repeat(24));
 assert.throws(()=>s.set(token(),{...row('alice'),runtime:'dsh-sdk',targetKey:'1'.repeat(24)}));assert.throws(()=>s.set(token(),{...row('alice'),targetKey:'1'.repeat(24)}));
 s.delete(agent);assert(s.has(legacy));assert(!new SessionStore(file,{clock}).has(agent));s.removeUser('alice');assert(!new SessionStore(file,{clock}).has(legacy));
 console.log(JSON.stringify({passed:true,hashedTokensOnly:true,serverExpiry:true,durableLogoutAndUserRevocation:true,corruptionRefusedWithoutOverwrite:true,failedWriteNotAuthenticated:true,linuxPermissionsAndLinkChecks:process.platform!=='win32'}));
}finally{assert(root.startsWith(path.join(os.tmpdir(),'dsh-session-store-')));fs.rmSync(root,{recursive:true,force:true});}
