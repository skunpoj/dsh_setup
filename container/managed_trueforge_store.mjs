import { readFileSync } from 'node:fs';

const name = 'internal-litellm';
const model = 'deepseek-v4.1-flash';
const properties = {context_length: 1048576, max_output_tokens: 8192};

export function managedStore() {
  const api_key = readFileSync('/harness-credentials/api-key', 'utf8').trim();
  if (!api_key) throw new Error('Managed inference credential is missing');
  function record(input) {
    return {tenant_id: input.tenant_id, name, created_at: '2026-10-16T00:00:00Z',
      updated_at: '2026-10-16T00:00:00Z', manifest: {type: 'custom', name,
        base_url: 'http://litellm.llm.svc.cluster.local:4000/v1', auth: {api_key},
        models: [{name: model, model_id: model, properties}]}};
  }
  const denied = async () => { throw new Error('Model configuration is operator managed'); };
  return Object.freeze({
    listProviders: async input => [record(input)],
    getProvider: async input => input.name === name && input.model_name === model ? record(input) : undefined,
    getProviderForUpdate: async input => input.name === name ? record(input) : undefined,
    createProvider: denied, upsertProvider: denied, deleteProvider: denied,
    listModels: async () => [{name: `${name}/${model}`, model_id: model, provider: {name}, properties}],
    resolveInvokeHeaders: async () => ({})
  });
}
