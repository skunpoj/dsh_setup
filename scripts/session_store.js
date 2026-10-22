'use strict';
// One protected writer per gateway. Cookie bearer values are never persisted.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const TTL_MS=86400000,MAX_ENTRIES=2048,MAX_BYTES=1048576;
const tokenHash=token=>typeof token==='string'&&/^[a-f0-9]{48}$/.test(token)?crypto.createHash('sha256').update(token).digest('hex'):null;
class SessionStore extends Map {
 constructor(file,{clock=Date.now,verify=()=>true}={}){
  super();if(!path.isAbsolute(file))throw Error('Session store needs a protected absolute path');
  this.file=file;this.clock=clock;this.verify=verify;
  fs.mkdirSync(path.dirname(file),{recursive:true,mode:0o700});
  this.secureParent();
  let fd;
  try{
   fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
   const s=fs.fstatSync(fd);if(!s.isFile()||s.nlink!==1||s.size>MAX_BYTES||(process.platform!=='win32'&&((s.mode&0o077)||s.uid!==process.getuid())))throw Error('Session store permissions or shape invalid');
   const bytes=fs.readFileSync(fd);if(bytes.length>MAX_BYTES)throw Error('Session store too large');
   const value=JSON.parse(bytes);if(value.version!==1||Object.keys(value).sort().join(',')!=='sessions,version'||!Array.isArray(value.sessions)||value.sessions.length>MAX_ENTRIES)throw Error('Invalid session store');
   for(const row of value.sessions){
    if(!row||Object.keys(row).sort().join(',')!=='accountStamp,created,digest,internet,user'||!this.valid(row)||!/^[a-f0-9]{64}$/.test(row.digest)||super.has(row.digest))throw Error('Invalid session row');
    if(row.created+TTL_MS>clock())super.set(row.digest,{user:row.user,internet:row.internet,created:row.created,accountStamp:row.accountStamp});
   }
  }catch(e){if(e.code!=='ENOENT')throw Error('Protected session store unavailable; refusing startup');}
  finally{if(fd!==undefined)fs.closeSync(fd);}
 }
 valid(row){return row&&/^[a-z0-9_.-]{1,30}$/.test(row.user)&&['on','off'].includes(row.internet)&&Number.isSafeInteger(row.created)&&row.created>0&&row.created<=this.clock()+30000&&/^[a-f0-9]{64}$/.test(row.accountStamp);}
 secureParent(){const s=fs.lstatSync(path.dirname(this.file));if(!s.isDirectory()||s.isSymbolicLink()||(process.platform!=='win32'&&((s.mode&0o077)||s.uid!==process.getuid())))throw Error('Session directory must be private and owned by the gateway');}
 prune(){for(const [key,row]of super.entries())if(row.created+TTL_MS<=this.clock())super.delete(key);}
 persist(){
  this.secureParent();
  const rows=[...super.entries()].map(([digest,r])=>({digest,user:r.user,internet:r.internet,created:r.created,accountStamp:r.accountStamp}));
  const bytes=JSON.stringify({version:1,sessions:rows});if(Buffer.byteLength(bytes)>MAX_BYTES)throw Error('Session capacity exceeded');
  const tmp=path.join(path.dirname(this.file),'.sessions-'+crypto.randomBytes(12).toString('hex'));let fd;
  try{fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,bytes);fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,this.file);
   if(process.platform!=='win32'){const dir=fs.openSync(path.dirname(this.file),'r');try{fs.fsyncSync(dir);}finally{fs.closeSync(dir);}}
  }
  finally{if(fd!==undefined)fs.closeSync(fd);try{fs.unlinkSync(tmp);}catch(e){if(e.code!=='ENOENT')throw e;}}
 }
 set(token,row){
  const key=tokenHash(token);if(!key||!this.valid(row))throw Error('Invalid session');this.prune();
  if(!super.has(key)&&super.size>=MAX_ENTRIES)throw Error('Session capacity exceeded');
  const old=super.get(key);super.set(key,row);
  try{this.persist();}catch(e){if(old)super.set(key,old);else super.delete(key);throw e;}return this;
 }
 get(token){
  const key=tokenHash(token);if(!key)return;this.prune();const row=super.get(key);
  if(row&&!this.verify(row)){super.delete(key);return;}return row;
 }
 has(token){return this.get(token)!==undefined;}
 delete(token){
  const key=tokenHash(token),old=key&&super.get(key);if(!old)return false;super.delete(key);
  try{this.persist();}catch(e){super.set(key,old);throw e;}return true;
 }
 removeUser(user){
  const removed=[...super.entries()].filter(([,r])=>r.user===user);for(const[k]of removed)super.delete(k);
  if(removed.length)try{this.persist();}catch(e){for(const[k,v]of removed)super.set(k,v);throw e;}
 }
 values(){this.prune();return super.values();}
 get size(){this.prune();return super.size;}
}
module.exports={SessionStore,TTL_MS};
