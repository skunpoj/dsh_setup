// Run on Linux to exercise FIFOs and descriptor flags used in production.
const fs=require('fs'),os=require('os'),path=require('path'),assert=require('assert/strict'),vm=require('vm'),cp=require('child_process');
const source=fs.readFileSync(path.join(__dirname,'../scripts/auth_proxy.js'),'utf8');
const helper=source.slice(source.indexOf('function readServiceStatus('),source.indexOf('function serviceInventory('));
const read=vm.runInNewContext(helper+';readServiceStatus',{fs,Buffer,Error,JSON});
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-status-'));let checks=[];
try{
 const f=path.join(root,'status.json');fs.writeFileSync(f,'{"observedAt":1,"services":[]}');assert.equal(read(f).observedAt,1);checks.push('valid regular JSON');
 fs.writeFileSync(f,'x'.repeat(65537));assert.throws(()=>read(f));checks.push('oversize refused');
 fs.writeFileSync(f,'invalid');assert.throws(()=>read(f));checks.push('invalid JSON refused');
 fs.unlinkSync(f);fs.mkdirSync(f);assert.throws(()=>read(f));fs.rmdirSync(f);checks.push('directory refused');
 if(process.platform==='linux'){
  const target=path.join(root,'private.json');fs.writeFileSync(target,'{"secret":"synthetic"}');fs.symlinkSync(target,f);assert.throws(()=>read(f));fs.unlinkSync(f);checks.push('symlink refused');
  cp.execFileSync('mkfifo',[f]);const start=Date.now();assert.throws(()=>read(f));assert(Date.now()-start<1000);fs.unlinkSync(f);checks.push('FIFO refused without blocking');
 }
 const original=fs.fstatSync;fs.writeFileSync(f,'{"observedAt":2}');
 fs.fstatSync=fd=>{const st=original(fd);fs.unlinkSync(f);fs.writeFileSync(f,'{"observedAt":999}');return st;};
 try{assert.equal(read(f).observedAt,2);}finally{fs.fstatSync=original;}checks.push('pathname replacement reads original descriptor');
 const originalRead=fs.readSync;fs.writeFileSync(f,'{}');let called=false;
 fs.readSync=(fd,b,offset,length,position)=>{if(!called){called=true;fs.appendFileSync(f,'x'.repeat(65537));}return originalRead(fd,b,offset,length,position);};
 try{assert.throws(()=>read(f));}finally{fs.readSync=originalRead;}checks.push('growth after fstat bounded and refused');
 console.log(JSON.stringify({status:'passed',platform:process.platform,checks}));
}finally{fs.rmSync(root,{recursive:true,force:true});}
