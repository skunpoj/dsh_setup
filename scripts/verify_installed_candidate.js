// Qualify actual installed package files. Does not contact an inference service.
const fs=require('fs'),path=require('path'),assert=require('assert'),{spawnSync}=require('child_process');
const root=process.env.DSH_PACKAGE_DIR || '/usr/local/lib/node_modules/@deepseek-ai/dsh';
const expected=process.argv[2];
const pkg=JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8'));
assert(expected && pkg.version===expected,'Installed package version differs from candidate');
const base=path.join(root,'node_modules/@deepseek-ai');
const required=[
 ['dsh-api-session-controller/lib/index.js',['async function buildModelCatalog(', 'routableProviders: ["litellm-cluster"]']],
 ['dsh-client-ui-model-selection/lib/client.js',['ModelCatalogDirectory = class','routableProviders: ["litellm-cluster"]']],
 ['dsh-compaction-basic/lib/index.js',['function resolveCompactSpec(', 'const headroomTokens = config.headroomTokens ?? 65536;']],
];
for(const [relative,markers] of required){
 const file=path.join(base,relative),text=fs.readFileSync(file,'utf8');
 for(const marker of markers)assert(text.includes(marker),'Installed compatibility contract changed: '+relative+' / '+marker);
 const syntax=spawnSync(process.execPath,['--check',file],{encoding:'utf8'});
 assert.equal(syntax.status,0,'Installed module syntax rejected: '+relative);
}
const home=process.env.DSH_HOME || path.join(process.env.HOME,'.dsh');
const profile=fs.readFileSync(path.join(home,'profiles/web/cordis.patch.yml'),'utf8');
assert(profile.includes('contextWindow: 1048576') && profile.includes('maxTokens: 8192'),'Candidate web budget missing');
assert(profile.includes('thresholdRatio: 0.875'),'Candidate compaction policy missing');
const dump=spawnSync('dsh',['--profile','web','--dump-config'],{encoding:'utf8',timeout:30000});
assert.equal(dump.status,0,'Actual upstream web profile composition failed');
assert(dump.stdout.includes('litellm-cluster') && dump.stdout.includes('contextWindow: 1048576'),'Composed internal model route missing');
console.log(JSON.stringify({installedVersion:pkg.version,actualModulesChecked:required.length,syntax:true,webComposition:true,scope:'Installed package checks; no inference, user history or Production access'}));
