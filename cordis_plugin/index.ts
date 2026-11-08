/**
 * Illustrative sketch for upstream_rfc/RFC_ENTERPRISE_CORDIS_PLUGIN_AND_GATEWAY.md.
 * Nothing in DSH loads this file.
 *
 * Checked against the @deepseek-ai/dsh 0.2.1-rc.3 packages (not compiled here):
 *   - DSH vendors its own cordis, @deepseek-ai/cordis ~4.0.5, and schemas come from
 *     @deepseek-ai/schemastery; the plain `cordis` package is not what DSH runs.
 *   - Provider and default-model registration events named below do NOT exist in
 *     those packages. They are PROPOSED extension points. Today DSH takes providers
 *     from settings.yaml (llm-pi-ai.providers) and the default model from the
 *     dsh-agent-default-model config entry; see scripts/configure_models.js.
 *   - Teardown follows DSH's own pattern: register inside ctx.effect(() => dispose).
 * Defaults are site values: set them in the plugin config, not in code.
 */
import { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'

export interface CustomGatewayModel {
  id: string
  name: string
  contextWindow: number
  maxTokens: number
}

export interface CustomGatewayConfig {
  baseUrl: string
  apiKey?: string
  defaultProvider: string
  defaultModel: string
  models: CustomGatewayModel[]
}

export const Config = z.object({
  baseUrl: z.string().default(process.env.DSH_LLM_BASE_URL ?? 'http://litellm.example.invalid:4000/v1'),
  apiKey: z.string().role('secret').default(''),
  defaultProvider: z.string().default('litellm-cluster'),
  defaultModel: z.string().default('deepseek-v4.1-flash'),
  models: z.array(z.object({
    id: z.string().required(),
    name: z.string().required(),
    contextWindow: z.number().default(1048576),
    maxTokens: z.number().default(8192),
  })).default([
    { id: 'deepseek-v4.1-flash', name: 'DeepSeek-V4.1-Flash (1M context)', contextWindow: 1048576, maxTokens: 8192 },
  ]),
})

// Proposed extension points; they do not exist in DSH 0.2.1-rc.x.
interface ProposedGatewayEvents {
  'model/register-provider'(provider: {
    type: 'openai-compatible'
    name: string
    baseUrl: string
    apiKey?: string
    models: CustomGatewayModel[]
  }): () => void
  'settings/set-default-model'(selection: { provider: string; model: string }): () => void
}

export function apply(ctx: Context, config: CustomGatewayConfig) {
  const logger = ctx.logger('custom-llm-gateway')
  const bus = ctx as unknown as { emit: <K extends keyof ProposedGatewayEvents>(name: K, ...args: Parameters<ProposedGatewayEvents[K]>) => ReturnType<ProposedGatewayEvents[K]> }

  // One effect, so provider and default model are removed together, in reverse order,
  // when the plugin is reloaded or disposed. Registering twice on reload is what
  // an effect-less registration would cause.
  ctx.effect(() => {
    const unregisterProvider = bus.emit('model/register-provider', {
      type: 'openai-compatible',
      name: config.defaultProvider,
      baseUrl: config.baseUrl,
      apiKey: config.apiKey,
      models: config.models,
    })
    const unsetDefault = bus.emit('settings/set-default-model', {
      provider: config.defaultProvider,
      model: config.defaultModel,
    })
    logger.info(`Gateway provider ${config.defaultProvider} registered (${config.models.length} model(s))`)
    return () => {
      unsetDefault()
      unregisterProvider()
    }
  })
}
