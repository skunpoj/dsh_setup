# RFC: Modular LLM Gateway & Multi-User Workspace Session Management Plugin Architecture for DeepSeek Harness (DSH)

**Discussion Category**: Architecture & Plugins  
**Target Repository**: `deepseek-ai/deepseek-harness`  
**Community Plugin**: `cordis-plugin-custom-llm-gateway` (sketch)  
**Licence**: MIT, as the rest of dsh_setup  

---

## 1. Executive Summary

As DeepSeek Harness (DSH) evolves into an extensible agentic workbench, teams running DSH in containerized environments (Kubernetes, Docker) frequently connect through custom OpenAI-compatible gateways (such as LiteLLM, vLLM, and Ollama) with multi-user workspace isolation and reverse-proxy authentication gates.

This RFC outlines field-tested architectural patterns and proposes a modular **Cordis Plugin Architecture** (`cordis-plugin-custom-llm-gateway`) to cleanly decouple custom gateways, model routers, and multi-user environments without requiring core modifications to the upstream DSH codebase.

---

## 2. Key Architectural Considerations & Solutions

### A. Reverse-Proxy Token Exchange & Origin Validation
- **Observation**: DSH Web utilizes `TOKEN_QUERY` (`?token=...`) to authenticate the browser, issuing an `HTTP 303 See Other` to strip the token from the URL bar once the session cookie is set. When placed behind standard reverse proxies, naive URL rewriting that appends `?token=...` triggers an infinite redirect loop (`ERR_TOO_MANY_REDIRECTS`). Furthermore, DSH client RPC validation enforces origin-matching (`isTrustedApiRequest`), returning HTTP 403 if the incoming `Host` header does not match the external `Origin`.
- **Solution**: Implement an internal one-time token redemption handshake in the proxy layer that mints and caches the `dsh-auth-${sha256(authority)}` session cookie, preserving public host headers (`X-Forwarded-Host` / `Host`) and injecting the authenticated session transparently on upstream requests to `/`.

### B. Node.js HMR Runtime Configuration (`--expose-internals`)
- **Observation**: Under certain containerized runtimes (Alpine/Debian), `@deepseek-ai/cordis-plugin-hmr` requires Node.js internals to be exposed.
- **Solution**: Container launcher environments specify `--expose-internals` in their Node process arguments.

### C. Custom In-Cluster Model Routing & Token Bounding
- **Observation**: Deployments routing through private OpenAI-compatible endpoints running locally hosted open-weight models need consistent model discovery and proper `maxTokens` bounding to align with backend KV-cache constraints.
- **Solution**: Provide a plugin configuration hook that registers custom models into DSH's settings catalog and enforces `maxTokens` bounding dynamically.

### D. Multi-User Workspace Isolation & Persistence Mode
- **Observation**: When running DSH as a shared team workbench behind ingress, user workspaces need per-user directory sandboxing (`/workspace/users/<user_id>`) and remote browser access requires host persistence for provider directory settings.
- **Solution**: Provide declarative workspace mapping and host-level settings persistence mirrors for reverse-proxied domains.

---

## 3. Cordis Plugin Specification

Instead of modifying core packages, gateway and multi-tenancy logic is packaged as a Cordis plugin (`cordis_plugin/index.ts`). **Status: a sketch.** It uses DSH's vendored `@deepseek-ai/cordis` ~4.0.5 and schemastery, and DSH's `ctx.effect` teardown pattern, but it was not compiled or run against a DSH release, and the two registration events are proposed extension points, not existing APIs. The multi-user and reverse-proxy toggles of an earlier draft only wrote log lines and were removed from the sketch; the requirements above still describe what a real plugin would have to provide:

```typescript
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
```

---

## 4. Production Verification & Compatibility Matrix

| Capability | Local Standalone DSH | Containerized DSH + Plugin |
| :--- | :--- | :--- |
| **Custom OpenAI Gateway** | Manual YAML / UI config | Proposed: registered by the plugin through a new extension point |
| **Model Discovery** | Static loopback defaults | Dynamic cluster / custom discovery |
| **Multi-Tenancy** | Single-user loopback | Isolated user folders & auth gateway |
| **Reverse-Proxy Support**| Localhost only | Fully compatible behind NGINX / K8s Ingress |
| **Zero Core Fork** | Upstream code unchanged | Plugin-only change (proposal; not verified against a DSH release) |

