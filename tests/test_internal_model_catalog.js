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
function check(catalog) {
  assert.deepEqual(Array.from(catalog.routableProviders), ['litellm-cluster']);
  assert.deepEqual(Array.from(catalog.groups, group => group.id), ['litellm-cluster']);
  assert.equal(catalog.default.provider, 'litellm-cluster');
  assert(catalog.groups[0].models.some(model => model.id === 'deepseek-v4.1-flash'));
}
(async () => {
  const server = {};
  vm.runInNewContext(files.get(`${base}/dsh-api-session-controller/lib/index.js`), server);
  check(await server.buildModelCatalog());
  const client = { _deepseek_ai_dsh_client_store: {
    createSnapshotStore: snapshot => ({ getSnapshot: () => snapshot }),
  } };
  vm.runInNewContext(files.get(`${base}/dsh-client-ui-model-selection/lib/client.js`), client);
  check(await new client.ModelCatalogDirectory({}).load());
  const settings = files.get('/fixture/.dsh/settings.yaml');
  assert(settings.includes('baseURL: "http://litellm.llm.svc.cluster.local:4000/v1"'));
  for (const [filename, content] of files) {
    assert(!content.includes('deepseek-official'), `external catalog in ${filename}`);
  }
  console.log('Generated server/client catalogs expose only internal LiteLLM; default inference retained.');
})().catch(error => { console.error(error); process.exitCode = 1; });
