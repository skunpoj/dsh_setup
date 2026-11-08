// The 0.2.2-rc.1 session controller reads a durable image from the supplied reference
// without checking the Session log. This test pins what still protects that path in
// the attachment store: only a well-formed sha256 content id maps to a file, the file
// stays under <root>/objects/<xx>/<hash>, and a missing, corrupt or mismatching object
// is refused. Synthetic data only; runs the installed package's own functions.
const fs=require('fs'),os=require('os'),path=require('path'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const pkg=process.env.DSH_PACKAGE_DIR||'/usr/local/lib/node_modules/@deepseek-ai/dsh';
const src=fs.readFileSync(path.join(pkg,'node_modules/@deepseek-ai/dsh-attachment-local/lib/index.js'),'utf8');
function slice(from,to){const a=src.indexOf(from),b=src.indexOf(to,a);assert(a>=0&&b>a,'anchor missing: '+from);return src.slice(a,b);}
class AttachmentError extends Error{constructor(m,code){super(m);this.code=code;}}
const sandbox={AttachmentError,Error,Uint8Array,String,Buffer,join:path.join,createHash:crypto.createHash,
 readFile:fs.promises.readFile,probeImage:async()=>({mediaType:'image/png',width:1,height:1})};
vm.createContext(sandbox);
vm.runInContext(
 'const ID_PATTERN = /^sha256:([a-f0-9]{64})$/;\n'+
 slice('function digest$1(','function displayName(')+
 slice('function ensureReference(','async function inspectMetadata(')+
 slice('async function readImageFile(','//#endregion')+
 ';globalThis.api={ensureReference,normalizedImagePath,readImageFile};',sandbox);
const {ensureReference,normalizedImagePath,readImageFile}=sandbox.api;
(async()=>{
 const good='a'.repeat(64);
 for(const bad of ['','sha256:','sha256:'+good.slice(1),'sha256:'+good+'0','sha256:'+'A'.repeat(64),'sha256:../../../../etc/passwd',
   'sha256:'+good+'/../x','../'+good,'sha256:'+good+'\n','md5:'+good,'sha256:'+'g'.repeat(64)]){
  assert.throws(()=>ensureReference({attachmentId:bad}),e=>e.code==='INVALID_ATTACHMENT_REF',JSON.stringify(bad));
 }
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'attach-ref-'));
 try{
  const p=normalizedImagePath(root,{attachmentId:'sha256:'+good});
  assert.equal(p,path.join(root,'objects','aa',good));
  assert(path.relative(root,p).split(path.sep)[0]==='objects');
  // A well-formed id for an object this store never wrote is refused, not guessed.
  const bytes=Buffer.from('not-really-an-image');
  const hash=crypto.createHash('sha256').update(bytes).digest('hex');
  const ref={attachmentId:'sha256:'+hash,mediaType:'image/png',bytes:bytes.length,width:1,height:1};
  await assert.rejects(readImageFile(root,ref),e=>e.code==='ATTACHMENT_NOT_FOUND');
  // An object whose bytes do not hash to its id is refused as corrupt.
  const dir=path.join(root,'objects',hash.slice(0,2));fs.mkdirSync(dir,{recursive:true});
  fs.writeFileSync(path.join(dir,hash),Buffer.from('tampered'));
  await assert.rejects(readImageFile(root,ref),e=>e.code==='ATTACHMENT_CORRUPT');
  // Intact bytes but a reference whose metadata does not match the stored object are refused.
  fs.writeFileSync(path.join(dir,hash),bytes);
  await assert.rejects(readImageFile(root,{...ref,bytes:bytes.length+1}),()=>true);
  await assert.rejects(readImageFile(root,{...ref,width:2}),()=>true);
  const ok=await readImageFile(root,ref);
  assert.equal(Buffer.from(ok.data).toString(),'not-really-an-image');
  console.log(JSON.stringify({passed:true,attachmentReferenceRefusal:true}));
 }finally{fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exit(1);});
