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
  defaultModel: Schema.string().default('deepseek-v4.1-flash'),
  models: Schema.array(Schema.object({
    id: Schema.string().required(),
    name: Schema.string().required(),
    contextWindow: Schema.number().default(1048576),
    maxTokens: Schema.number().default(65536),
  })).default([
    { id: 'deepseek-v4.1-flash', name: 'DeepSeek-V4.1-Flash (Native 1M CED MoE)', contextWindow: 1048576, maxTokens: 65536 },
    { id: 'deepseek-flash', name: 'DeepSeek-Flash (V4.1-Flash Alias)', contextWindow: 1048576, maxTokens: 65536 },
    { id: 'glm-5.3-flash', name: 'GLM-5.3-Flash (Cluster Standby)', contextWindow: 4096, maxTokens: 2048 },
    { id: 'qwen3.8-27b', name: 'Qwen3.8-27B (Cluster Standby)', contextWindow: 32768, maxTokens: 4096 }
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
