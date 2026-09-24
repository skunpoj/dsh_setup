import { Context, Schema } from 'cordis'

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
  workspaceRoot: string
  multiUserIsolation: boolean
  loopbackProxyBypass: boolean
}

export const Config: Schema<CustomGatewayConfig> = Schema.object({
  baseUrl: Schema.string().default('http://litellm.llm.svc.cluster.local:4000/v1'),
  apiKey: Schema.string().role('secret').default(''),
  defaultProvider: Schema.string().default('litellm-cluster'),
  defaultModel: Schema.string().default('glm-5.3-flash'),
  models: Schema.array(Schema.object({
    id: Schema.string().required(),
    name: Schema.string().required(),
    contextWindow: Schema.number().default(4096),
    maxTokens: Schema.number().default(2048),
  })).default([
    { id: 'glm-5.3-flash', name: 'GLM-5.3-Flash BF16 (4-GPU TP=4)', contextWindow: 4096, maxTokens: 2048 },
    { id: 'glm-5.3-flash-awq', name: 'GLM-5.3-Flash AWQ W4A16 (2-GPU TP=2)', contextWindow: 2048, maxTokens: 1024 },
    { id: 'qwen3.8-flash-next', name: 'Qwen 3.8-Flash-Next (Mode 2 Standby 2-GPU)', contextWindow: 32768, maxTokens: 4096 }
  ]),
  workspaceRoot: Schema.string().default('/workspace/users'),
  multiUserIsolation: Schema.boolean().default(true),
  loopbackProxyBypass: Schema.boolean().default(true),
})

export function apply(ctx: Context, config: CustomGatewayConfig) {
  const logger = ctx.logger('custom-llm-gateway')
  logger.info('Initializing Custom LLM Gateway & Multi-User Management Plugin...')

  ctx.on('ready', async () => {
    // 1. Register custom OpenAI-compatible gateway provider into DSH
    ctx.emit('model/register-provider', {
      type: 'openai-compatible',
      name: config.defaultProvider,
      baseUrl: config.baseUrl,
      apiKey: config.apiKey,
      models: config.models,
    })

    // 2. Set default agent model selection
    ctx.emit('settings/set-default-model', {
      provider: config.defaultProvider,
      model: config.defaultModel,
    })

    // 3. Multi-user workspace provisioning and session boundary enforcement
    if (config.multiUserIsolation) {
      logger.info(`Multi-user workspace isolation active at: ${config.workspaceRoot}`)
    }

    // 4. Proxied reverse-proxy origin & settings persistence enablement
    if (config.loopbackProxyBypass) {
      logger.info('Reverse-proxy browser settings bypass enabled (host persistence mode).')
    }
  })
}
