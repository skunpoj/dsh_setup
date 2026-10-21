'use strict';
// Dedicated synthetic Test issuer only; never part of the Main runtime.
function isolate(req, ownCookie) {
  const cookies=String(req.headers.cookie||'').split(';').map(x=>x.trim()).filter(x=>{
    const name=x.split('=',1)[0];
    return x && (name===ownCookie || (!['dsh_auth','dsh2_auth','dsh3_auth'].includes(name)&&!name.startsWith('dsh-auth-')));
  }).join('; ');
  if(cookies)req.headers.cookie=cookies;else delete req.headers.cookie;
  req.rawHeaders=Object.entries(req.headers).flatMap(([k,v])=>[k,String(v)]);
}
function privateState(root) {
  const fs=require('fs'),path=require('path');
  const directory=p=>{fs.mkdirSync(p,{recursive:true,mode:0o700});const s=fs.lstatSync(p);if(!s.isDirectory()||s.isSymbolicLink()||s.uid!==process.getuid())throw Error('Unexpected Test state directory');fs.chmodSync(p,0o700);};
  directory(root);directory(path.join(root,'browser'));
  const file=path.join(root,'browser/sessions.json');
  try {const s=fs.lstatSync(file);if(!s.isFile()||s.isSymbolicLink()||s.nlink!==1||s.uid!==process.getuid())throw Error('Unexpected Test session file');fs.chmodSync(file,0o600);}catch(e){if(e.code!=='ENOENT')throw e;}
}
function migrateAliases(root, expectedHash) {
  const fs=require('fs'),path=require('path'),crypto=require('crypto'),file=path.join(root,'app-links.json');
  const old=['dsh-app-signin-gated-test','dsh-app-signin-public-test'],names=['app-signin-gated-test','app-signin-public-test'];
  const stat=fs.lstatSync(file);if(!stat.isFile()||stat.isSymbolicLink()||stat.nlink!==1||stat.uid!==process.getuid())throw Error('Unexpected Test registry file');
  const bytes=fs.readFileSync(file);if(bytes.length>65536)throw Error('Unexpected Test registry size');
  const value=JSON.parse(bytes);if(Object.keys(value).length===2&&names.every(n=>Object.hasOwn(value,n))&&!old.some(n=>Object.hasOwn(value,n)))return;
  if(!/^[a-f0-9]{64}$/.test(expectedHash||'')||crypto.createHash('sha256').update(bytes).digest('hex')!==expectedHash||Object.keys(value).length!==2||!old.every(n=>Object.hasOwn(value,n)&&value[n].owner==='appreviewer'))throw Error('Test registry changed; refusing alias migration');
  const backup=path.join(root,'app-links.before-alias-fix-v3.json');
  if(fs.existsSync(backup)){const s=fs.lstatSync(backup);if(!s.isFile()||s.isSymbolicLink()||s.nlink!==1||s.uid!==process.getuid()||!fs.readFileSync(backup).equals(bytes))throw Error('Unexpected Test registry backup');}
  else{const fd=fs.openSync(backup,'wx',0o600);try{fs.writeFileSync(fd,bytes);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}}
  const next=Object.fromEntries(old.map((name,i)=>[names[i],value[name]])),tmp=path.join(root,'.app-links-'+crypto.randomBytes(12).toString('hex'));let fd;
  try{fd=fs.openSync(tmp,'wx',0o600);fs.writeFileSync(fd,JSON.stringify(next));fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;fs.renameSync(tmp,file);const dir=fs.openSync(root,'r');try{fs.fsyncSync(dir);}finally{fs.closeSync(dir);}}
  finally{if(fd!==undefined)fs.closeSync(fd);try{fs.unlinkSync(tmp);}catch(e){if(e.code!=='ENOENT')throw e;}}
}
module.exports={isolate,privateState,migrateAliases};
