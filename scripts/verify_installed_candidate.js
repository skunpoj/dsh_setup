// Qualify actual installed package files. Does not contact an inference service.
const fs=require('fs'),path=require('path'),assert=require('assert'),{spawnSync}=require('child_process');
const root=process.env.DSH_PACKAGE_DIR || '/usr/local/lib/node_modules/@deepseek-ai/dsh';
const expected=process.argv[2];
const pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
assert(expected && pkg.version===expected,'Installed package version differs from candidate');
const base=path.join(root,'node_modules/@deepseek-ai');
const required=[
 ['dsh-api-session-controller/lib/index.js',['async function buildModelCatalog(', 'ctx.llm.listProviders()', 'ctx.remoteAccess.allows(']],
 ['dsh-client-ui-model-selection/lib/client.js',['ModelCatalogDirectory = class','modelCatalog']],
 ['dsh-compaction-basic/lib/index.js',['function resolveCompactSpec(', 'const headroomTokens = config.headroomTokens ?? 65536;']],
];
for(const [relative,markers] of required){
 const file=path.join(base,relative),text=fs.readFileSync(file,'utf8');
 for(const marker of markers)assert(text.includes(marker),'Installed compatibility contract changed: '+relative+' / '+marker);
 const syntax=spawnSync(process.execPath,['--check',file],{encoding:'utf8'});
 assert.equal(syntax.status,0,'Installed module syntax rejected: '+relative);
}
// Unmodified access/UI/prompt files must still match the reviewed official bytes.
const crypto=require('crypto');
const contract=JSON.parse(fs.readFileSync(path.join(__dirname,'upstream_patch_contract.json'),'utf8'));
for(const entry of contract.targets.filter(x=>x.patched===false)) {
 const actual=crypto.createHash('sha256').update(fs.readFileSync(path.join(base,entry.path))).digest('hex');
 assert.equal(actual,entry.sha256,'Protected installed upstream file changed: '+entry.path);
}
const home=process.env.DSH_HOME || path.join(process.env.HOME,'.dsh');
const profile=fs.readFileSync(path.join(home,'profiles/web/cordis.patch.yml'),'utf8');
assert(profile.includes('contextWindow: 1048576') && profile.includes('maxTokens: 8192'),'Candidate web budget missing');
assert(profile.includes('thresholdRatio: 0.875'),'Candidate compaction policy missing');
assert(profile.includes('personaPrefix:') && profile.includes('- id: llm-deepseek\n  disabled: true'),'Configured persona/internal routing policy missing');
const dump=spawnSync('dsh',['--profile','web','--dump-config'],{encoding:'utf8',timeout:30000});
assert.equal(dump.status,0,'Actual upstream web profile composition failed');
assert(dump.stdout.includes('litellm-cluster') && dump.stdout.includes('contextWindow: 1048576'),'Composed internal model route missing');
// Execute actual installed catalog/image pure functions with synthetic providers.
const port=spawnSync(process.execPath,[path.join(__dirname,'../tests/test_upstream_port.js')],{encoding:'utf8',env:{...process.env,DSH_PACKAGE_DIR:root}});
assert.equal(port.status,0,'Installed catalog/image semantic checks failed: '+port.stderr);
// Exercise the installed storage function, not just a source marker. Missing
// historical images must never turn into fabricated pixels/evidence.
(async()=>{
 const {pathToFileURL}=require('url'),os=require('os');
 const attachment=await import(pathToFileURL(path.join(base,'dsh-attachment-local/lib/index.js')).href);
 const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-missing-image-'));
 try{
  await assert.rejects(attachment.readImageFile(temporary,{attachmentId:'sha256:'+'a'.repeat(64)},new AbortController().signal),error=>error.code==='ATTACHMENT_NOT_FOUND'&&error.message.includes('no replacement image'));
 }finally{fs.rmSync(temporary,{recursive:true,force:true});}
 console.log(JSON.stringify({installedVersion:pkg.version,actualModulesChecked:required.length,syntax:true,webComposition:true,missingImageExplicitlyRejected:true,scope:'Installed package checks; no inference, user history or Production access'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
