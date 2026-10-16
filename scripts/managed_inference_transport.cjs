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

if (process.env.DSH_MANAGED_TRANSPORT === '1') {
  const undici = require(require.resolve('undici', {paths: ['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));
  const origin = process.env.DSH_LLM_TRANSPORT_ORIGIN || 'http://litellm.llm.svc.cluster.local:4000';
  undici.setGlobalDispatcher(createManagedDispatcher(undici.getGlobalDispatcher(), origin));
}
module.exports = {createManagedDispatcher};
