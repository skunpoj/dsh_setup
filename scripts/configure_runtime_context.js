// Explicit runtime policy; leaves credentials, sessions and workspace paths alone.
const fs = require('fs');
const path = require('path');
const aliases = ['deepseek-v4.1-flash', 'deepseek-flash'];

function configure(document, context) {
  if (![131072, 1048576].includes(context)) throw new Error('Unsupported context policy');
  if (!Array.isArray(document)) throw new Error('Web profile must be an array');
  const llm = document.find(x => x.id === 'llm-pi-ai');
  const provider = llm?.config?.providers?.['litellm-cluster'];
  if (!provider || !Array.isArray(provider.models)) throw new Error('Internal provider absent');
  provider.models = provider.models.filter(model => aliases.includes(model.id));
  for (const id of aliases) {
    const model = provider.models.find(x => x.id === id);
    if (!model) throw new Error('Expected internal model absent: '+id);
    model.contextWindow = context;
    model.maxTokens = 8192;
    model.name = id === aliases[0] ? `DeepSeek-V4.1-Flash (${context === 1048576 ? '1M' : '128K'} context)` : 'DeepSeek-Flash (V4.1-Flash Alias)';
  }
  if (context === 1048576) {
    provider.timeoutMs = 3600000;
    provider.streamIdleTimeoutMs = 3600000;
  }
  const compaction = document.find(x => x.id === 'compaction-basic');
  if (!compaction) throw new Error('Compaction plugin absent');
  compaction.disabled = false;
  compaction.config ??= {};
  compaction.config.auto = true;
  const previous = compaction.config.modelPolicies ?? [];
  compaction.config.modelPolicies = previous.filter(x => !(x.provider === 'litellm-cluster' && aliases.includes(x.model)));
  for (const model of aliases) compaction.config.modelPolicies.push({
    provider: 'litellm-cluster', model, thresholdRatio: context === 1048576 ? 0.875 : 0.75,
    headroomTokens: 65536, maxTokens: 8192,
  });
  return document;
}

if (require.main === module) {
  const YAML = require(require.resolve('yaml', {paths: ['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
  const home = process.argv[2];
  const context = Number(process.argv[3]);
  const file = path.join(home, 'profiles/web/cordis.patch.yml');
  const original = fs.readFileSync(file, 'utf8');
  const next = YAML.stringify(configure(YAML.parse(original), context));
  if (next !== original) {
    const rollback = path.join(home, '.context-policy-rollback', new Date().toISOString().replace(/[:.]/g, '-'));
    fs.mkdirSync(rollback, {recursive: true, mode: 0o700});
    fs.writeFileSync(path.join(rollback, 'web-profile.yml'), original, {mode: 0o600, flag: 'wx'});
    const temporary = file+'.context-'+process.pid;
    fs.writeFileSync(temporary, next, {mode: 0o600, flag: 'wx'});
    fs.renameSync(temporary, file);
  }
  const readback = YAML.parse(fs.readFileSync(file, 'utf8'));
  const models = readback.find(x => x.id === 'llm-pi-ai').config.providers['litellm-cluster'].models;
  if (aliases.some(id => models.find(x => x.id === id)?.contextWindow !== context)) throw new Error('Context readback failed');
  console.log(JSON.stringify({runtimeContextPolicy: context, outputCeiling: 8192, profilesReadBack: true}));
}
module.exports = {configure};
