// Execute the configurator against isolated package fixtures; inspect emitted
// server and client catalog values, rather than only searching its source.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const base = '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai';
const files = new Map([
  [`${base}/dsh-api-session-controller/lib/index.js`, 'async function buildModelCatalog(ctx, defaultSelection) {}\n//#endregion'],
  [`${base}/dsh-client-ui-model-selection/lib/client.js`, 'ModelCatalogDirectory = class {};'],
]);
const fakeFs = {
  existsSync: p => files.has(p) || p === '/usr/local/lib/node_modules/@deepseek-ai/dsh',
  readFileSync: p => { if(p.endsWith('upstream_patch_contract.json'))return JSON.stringify({targets:[]});if(p.endsWith('dsh-attachment-local/lib/index.js'))return '';assert(files.has(p), `unexpected read ${p}`); return files.get(p); },
  writeFileSync: (p, value) => files.set(p, value),
  mkdirSync: () => {},
};
const source = fs.readFileSync(path.join(__dirname, '../scripts/configure_models.js'), 'utf8');
vm.runInNewContext(source, {
  // This fixture isolates catalog transformation; real preflight is tested against
  // original registry artifacts and by test_upstream_contract.js.
  __dirname: path.join(__dirname,'../scripts'),
  require: name => { if(name==='fs')return fakeFs;if(name==='./verify_upstream_contract')return {verify:()=>[]};return require(name); },
  process: { env: { HOME: '/fixture', DSH_HOME: '/fixture/.dsh' } },
  console: { log() {}, error(error) { throw error; } }, Buffer,
});
// The former fake server/client catalog replacements are intentionally gone.
assert.equal(files.get(`${base}/dsh-api-session-controller/lib/index.js`),'async function buildModelCatalog(ctx, defaultSelection) {}\n//#endregion');
assert.equal(files.get(`${base}/dsh-client-ui-model-selection/lib/client.js`),'ModelCatalogDirectory = class {};');
const profile=files.get('/fixture/.dsh/profiles/web/cordis.patch.yml');
assert(profile.includes('- id: llm-deepseek\n  disabled: true'));
assert(profile.includes('- id: llm-deepseek-account\n  disabled: true'));
assert(profile.includes('personaPrefix:') && profile.includes('configured 1M context'));
assert(profile.includes('provider: litellm-cluster') && profile.includes('contextWindow: 1048576'));
assert(profile.includes('headroomTokens: 65536') && profile.includes('thresholdRatio: 0.875'));
const settings=files.get('/fixture/.dsh/settings.yaml');
assert(settings.includes('baseURL: "http://litellm.llm.svc.cluster.local:4000/v1"'));
console.log('Managed catalog/persona/compaction emitted as configuration; upstream server/client code preserved.');
