// Node fetch supplies a 300s headers timeout even with a longer SDK deadline.
// Scope the override to the operator-managed inference origin only.
function createManagedDispatcher(base, origin) {
  const allowed = new URL(origin);
  if (!['http:', 'https:'].includes(allowed.protocol) || allowed.username || allowed.password || allowed.pathname !== '/' || allowed.search || allowed.hash) {
    throw new Error('Managed inference transport requires a plain HTTP(S) origin');
  }
  const managedOrigin = allowed.origin;
  return {
    dispatch(options, handler) {
      const selected = new URL(String(options.origin)).origin === managedOrigin;
      return base.dispatch(selected ? {...options, headersTimeout: 3600000, bodyTimeout: 3600000} : options, handler);
    },
    close(...args) { return base.close(...args); },
    destroy(...args) { return base.destroy(...args); },
  };
}


// The SDK's chars/4 estimate must not silently turn a valid managed 1M
// request into max_tokens=1. Exact full-envelope counting remains fail-closed
// in the internal gateway. All other model/provider routes retain SDK guards.
// Reviewed @earendil-works/pi-ai 1.3.0; any dependency drift fails closed.
const SIMPLE_OPTIONS_SHA256 = '9b3cc0ae6daa86fdc050bc0cb0f3f986401e64ccddbde6757183c9f8ad411be2';
function patchManagedBudget(source, origin) {
  const anchor = '    const available = model.contextWindow - estimateContextTokens(context).tokens - CONTEXT_SAFETY_TOKENS;';
  if (require('node:crypto').createHash('sha256').update(source).digest('hex') !== SIMPLE_OPTIONS_SHA256 || source.split(anchor).length !== 2) {
    throw new Error('Managed token budget SDK source changed; qualify before updating');
  }
  const route = JSON.stringify(origin + '/v1');
  return source.replace(anchor, `    if (model.provider === "litellm-cluster" && model.api === "openai-completions"
        && ["deepseek-v4.1-flash", "deepseek-flash"].includes(model.id)
        && model.contextWindow === 1048576 && typeof model.baseUrl === "string"
        && (model.baseUrl === ${route} || model.baseUrl === ${route} + "/")) {
        return Math.max(MIN_MAX_TOKENS, Math.min(maxTokens, model.maxTokens, 8192));
    }
${anchor}`);
}
function registerManagedBudget(origin, sdkPath = '/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@earendil-works/pi-ai/dist/api/simple-options.js') {
  if (origin !== 'http://litellm.llm.svc.cluster.local:4000') return;
  const {pathToFileURL} = require('node:url');
  const target = pathToFileURL(sdkPath).href;
  const {registerHooks} = require('node:module');
  if (typeof registerHooks !== 'function') throw new Error('Managed budget requires qualified Node loader hooks');
  registerHooks({load(url, context, nextLoad) {
    const loaded = nextLoad(url, context);
    if (url !== target) return loaded;
    return {...loaded, source: patchManagedBudget(Buffer.isBuffer(loaded.source) ? loaded.source.toString('utf8') : loaded.source, origin)};
  }});
}

if (process.env.DSH_MANAGED_TRANSPORT === '1') {
  const undici = require(require.resolve('undici', {paths: ['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
  const origin = process.env.DSH_LLM_TRANSPORT_ORIGIN || 'http://litellm.llm.svc.cluster.local:4000';
  registerManagedBudget(origin);
  undici.setGlobalDispatcher(createManagedDispatcher(undici.getGlobalDispatcher(), origin));
}
module.exports = {createManagedDispatcher, patchManagedBudget, registerManagedBudget, SIMPLE_OPTIONS_SHA256};
