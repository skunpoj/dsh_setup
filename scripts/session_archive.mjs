// Operator-only, version-aware history export/import. Archives contain private data.
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL,fileURLToPath} from 'node:url';
export const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const MAX_FILE=64*1024*1024,MAX_TOTAL=1024*1024*1024,MAX_EVENTS=1000000;
function within(p,base){const r=path.relative(base,p);return r!==''&&!r.startsWith('..')&&!path.isAbsolute(r);}
function separate(a,b){a=path.resolve(a);b=path.resolve(b);if(a===b||within(a,b)||within(b,a))throw Error('Source/archive/target roots must not overlap');}
function noLinkAncestors(root){let p=path.resolve(root);while(true){if(fs.existsSync(p)&&fs.lstatSync(p).isSymbolicLink())throw Error('Symlink/junction in archive path');const parent=path.dirname(p);if(parent===p)break;p=parent;}}
function bounded(root,base){const p=path.resolve(root);if(!within(p,base))throw Error('Private path must be beneath explicit private base');let q=p;while(q!==path.dirname(q)){if(fs.existsSync(q)&&fs.lstatSync(q).isSymbolicLink())throw Error('Symlink in private path');q=path.dirname(q);}return p;}
export async function files(root){
 const rows=[];let total=0;
 async function walk(dir){for(const e of await fsp.readdir(dir,{withFileTypes:true})){
  const p=path.join(dir,e.name);if(e.isSymbolicLink())throw Error('Archive roots must not contain symlinks');
  if(e.isDirectory()){rows.push({path:path.relative(root,p).split(path.sep).join('/'),directory:true});await walk(p);}
  else if(e.isFile()){const before=await fsp.stat(p);if(before.size>MAX_FILE||(total+=before.size)>MAX_TOTAL)throw Error('Archive byte bound exceeded');const b=await fsp.readFile(p);const after=await fsp.stat(p);if(before.size!==after.size||before.mtimeMs!==after.mtimeMs)throw Error('Source changed while exporting');rows.push({path:path.relative(root,p).split(path.sep).join('/'),bytes:b.length,sha256:sha(b)});}
  else throw Error('Nonregular source entry');
 }}
 await walk(root);return rows.sort((a,b)=>a.path.localeCompare(b.path));
}
async function copyFiles(source,target,rows){
 await fsp.mkdir(target,{recursive:true,mode:0o700});
 for(const r of rows){const dest=path.join(target,...r.path.split('/'));if(!within(dest,target))throw Error('Unsafe archive member');if(r.directory){await fsp.mkdir(dest,{recursive:true,mode:0o700});continue;}await fsp.mkdir(path.dirname(dest),{recursive:true,mode:0o700});const b=await fsp.readFile(path.join(source,...r.path.split('/')));if(b.length!==r.bytes||sha(b)!==r.sha256)throw Error('Source fingerprint changed');await fsp.writeFile(dest,b,{flag:'wx',mode:0o600});}
}
export async function openStore(modules,root,compression){
 const load=n=>import(pathToFileURL(path.join(modules,n,'lib/index.js')).href);
 const {Context}=await load('cordis');const plugin=await load('dsh-session-persistence-jsonl');const ctx=new Context();
 const fiber=ctx.plugin(plugin.apply?plugin:plugin.default,{root,compression});await fiber.await();
 return {store:ctx.sessionPersistence,close:()=>fiber.dispose()};
}
export async function readSession(store,id){
 const h=await store.open(id,'read');try{const events=[];let offset=0;
  while(true){const slice=await h.read(offset,4096);for(const e of slice.events){if(e.seq!==offset++)throw Error('Noncontiguous events');events.push(e);if(events.length>MAX_EVENTS)throw Error('Event bound exceeded');}if(slice.events.length<4096)break;}
  return {header:h.header,inheritedEventCount:h.inheritedEventCount,events};
 }finally{await h.close();}
}
export function digestSession(s){return {idSHA256:sha(s.header.id),headerSHA256:sha(JSON.stringify(s.header)),eventsSHA256:sha(s.events.map(e=>JSON.stringify(e)+'\n').join('')),events:s.events.length,inheritedEventCount:s.inheritedEventCount};}
async function publishManifest(root,manifest){
 const temp=path.join(root,'.manifest-writing');const handle=await fsp.open(temp,'wx',0o600);try{await handle.writeFile(JSON.stringify(manifest,null,2)+'\n');await handle.sync();}finally{await handle.close();}
 if(fs.existsSync(path.join(root,'manifest.json')))throw Error('Publication already exists');await fsp.rename(temp,path.join(root,'manifest.json'));
}
export async function exportHistory({modules,source,archive,attachments,quarantine,compression='zstd',failAfter=0}){
 for(const p of [source,archive,attachments,quarantine])if(p)noLinkAncestors(p);
 separate(source,archive);for(const p of [attachments,quarantine])if(p)separate(p,archive);
 // mkdir is an exclusive reservation. Failed/incomplete exports are retained,
 // never mistaken for a complete archive (manifest.json is the commit marker).
 await fsp.mkdir(archive,{mode:0o700});const before=await files(source);const api=await openStore(modules,source,compression);let count=0;
 try{
  const listed=await api.store.list();const physical=new Set(before.filter(r=>!r.directory&&/^session(?:\.v[1-9][0-9]*)?\.jsonl(?:\.zstd)?$/.test(path.basename(r.path))).map(r=>path.dirname(r.path)));
  if(physical.size!==listed.length)throw Error('Physical sessions do not reconcile with readable sessions');
  const entries=[],seen=new Set();await fsp.mkdir(path.join(archive,'logical'),{mode:0o700});
  for(const row of listed){if(seen.has(row.header.id))throw Error('Duplicate session ID');seen.add(row.header.id);const s=await readSession(api.store,row.header.id);
   // Explicitly preserve the cut. Current retained corpus has cut zero; a
   // nonzero cut needs separately qualified parent-aware restoration.
   if(s.inheritedEventCount!==0)throw Error('Inherited-prefix restoration is not qualified; original retained');
   const data=Buffer.from(JSON.stringify(s)+'\n'),file='logical/'+sha(s.header.id)+'.json';await fsp.writeFile(path.join(archive,file),data,{flag:'wx',mode:0o600});entries.push({file,bytes:data.length,sha256:sha(data),...digestSession(s)});
   if(failAfter&&++count===failAfter)throw Error('Injected interruption before publication');
  }
  await copyFiles(source,path.join(archive,'original-generations'),before);
  const sets={};for(const [name,root]of Object.entries({attachments,quarantine})){if(root){const rows=await files(root);await copyFiles(root,path.join(archive,name),rows);sets[name]=rows;}else sets[name]=null;}
  const after=await files(source);if(JSON.stringify(before)!==JSON.stringify(after))throw Error('Source changed during export; archive not published');
  const manifest={schema:'dsh-lossless-history-archive/v1',createdUTC:new Date().toISOString(),sourceReaderVersion:JSON.parse(await fsp.readFile(path.join(modules,'dsh-session-persistence-jsonl/package.json'),'utf8')).version,compression,sourceFiles:before,sessions:entries,attachments:sets.attachments,quarantine:sets.quarantine,sourceUnchanged:true};
  await publishManifest(archive,manifest);return {sessions:entries.length,events:entries.reduce((n,r)=>n+r.events,0),sourceUnchanged:true,manifestSHA256:sha(await fsp.readFile(path.join(archive,'manifest.json')))};
 }finally{await api.close();}
}
async function readArchive(archive){
 const fingerprint=await files(archive);const manifestFile=path.join(archive,'manifest.json');if((await fsp.stat(manifestFile)).size>8*1024*1024)throw Error('Manifest byte bound exceeded');
 const m=JSON.parse(await fsp.readFile(manifestFile,'utf8'));if(m.schema!=='dsh-lossless-history-archive/v1'||!Array.isArray(m.sessions)||m.sessions.length>10000)throw Error('Unsupported archive');
 if(JSON.stringify(await files(path.join(archive,'original-generations')))!==JSON.stringify(m.sourceFiles))throw Error('Original generation archive is corrupt');
 const all=[],ids=new Set(),paths=new Set();for(const r of m.sessions){if(!/^logical\/[a-f0-9]{64}\.json$/.test(r.file)||paths.has(r.file))throw Error('Unsafe/duplicate archive member');paths.add(r.file);const file=path.join(archive,r.file);if(fs.lstatSync(file).isSymbolicLink())throw Error('Symlink member');const b=await fsp.readFile(file);if(b.length!==r.bytes||b.length>MAX_FILE||sha(b)!==r.sha256)throw Error('Archive member is corrupt');const s=JSON.parse(b);if(ids.has(s.header.id))throw Error('Duplicate session ID');ids.add(s.header.id);if(JSON.stringify(digestSession(s))!==JSON.stringify(Object.fromEntries(Object.keys(digestSession(s)).map(k=>[k,r[k]]))))throw Error('Logical digest mismatch');if(s.inheritedEventCount!==0)throw Error('Unqualified inherited prefix');all.push(s);}
 return {manifest:m,sessions:all,fingerprint};
}
export async function importHistory({modules,archive,target,compression='zstd',failAfter=0}){
 for(const p of [archive,target])noLinkAncestors(p);
 separate(archive,target);
 const {manifest,sessions,fingerprint}=await readArchive(archive);await fsp.mkdir(target,{mode:0o700});
 const stage=path.join(target,'.importing-'+crypto.randomUUID());await fsp.mkdir(stage,{mode:0o700});const api=await openStore(modules,stage,compression);let count=0;
 try{
  for(const s of sessions){const h=await api.store.create(s.header,{inheritedEventCount:s.inheritedEventCount});try{for(let i=0;i<s.events.length;i+=4096)await h.append(s.events.slice(i,i+4096));await h.flush();}finally{await h.close();}
   const restored=await readSession(api.store,s.header.id);if(JSON.stringify(digestSession(restored))!==JSON.stringify(digestSession(s)))throw Error('Restored logical state differs');
   if(failAfter&&++count===failAfter)throw Error('Injected interruption before publication');
  }
 }finally{await api.close();}
 // Reopen in another store instance before exposing the store directory.
 const check=await openStore(modules,stage,compression);try{const listed=await check.store.list();if(listed.length!==sessions.length)throw Error('Restored inventory differs');for(const s of sessions)if(JSON.stringify(digestSession(await readSession(check.store,s.header.id)))!==JSON.stringify(digestSession(s)))throw Error('Reopened state differs');}finally{await check.close();}
 for(const name of ['attachments','quarantine'])if(manifest[name]!==null){const actual=await files(path.join(archive,name));if(JSON.stringify(actual)!==JSON.stringify(manifest[name]))throw Error('Corrupt '+name);await copyFiles(path.join(archive,name),path.join(target,name),manifest[name]);}
 if(JSON.stringify(await files(archive))!==JSON.stringify(fingerprint))throw Error('Archive changed during restoration');
 const published=path.join(target,'sessions');if(fs.existsSync(published))throw Error('Refuse existing destination');await fsp.rename(stage,published);
 await publishManifest(target,{schema:'dsh-history-restore/v1',sourceArchiveSHA256:sha(await fsp.readFile(path.join(archive,'manifest.json'))),sessions:manifest.sessions.map(r=>({idSHA256:r.idSHA256,headerSHA256:r.headerSHA256,eventsSHA256:r.eventsSHA256,events:r.events,inheritedEventCount:r.inheritedEventCount})),verified:true});
 return {sessions:sessions.length,events:sessions.reduce((n,s)=>n+s.events.length,0),verified:true,published:true,existingDestinationOverwritten:false};
}
async function cli(){
 const args=Object.fromEntries(process.argv.slice(2).map(v=>{const i=v.indexOf('=');if(!v.startsWith('--')||i<0)throw Error('Use --name=value');return [v.slice(2,i),v.slice(i+1)];}));
 if(!args['private-base']||!args.modules||!['export','import'].includes(args.action))throw Error('Explicit action, modules and private-base required');const base=fs.realpathSync(args['private-base']);
 const input={modules:path.resolve(args.modules),archive:bounded(args.archive,base),compression:args.compression||'zstd',failAfter:Number(args['fail-after']||0)};
 if(!['none','zstd'].includes(input.compression))throw Error('Unsupported compression');
 let result;if(args.action==='export'){input.source=bounded(args.source,base);for(const name of ['attachments','quarantine'])if(args[name])input[name]=bounded(args[name],base);result=await exportHistory(input);}else{input.target=bounded(args.target,base);result=await importHistory(input);}
 console.log(JSON.stringify({status:'passed',action:args.action,...result}));
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))cli().catch(e=>{console.error(JSON.stringify({status:'failed',errorType:e.name,message:e.message}));process.exitCode=1;});
