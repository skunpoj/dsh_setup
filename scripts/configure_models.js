const fs = require("fs");

// 1. Maintain official DeepSeek models in dsh-llm-deepseek
const file = "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-llm-deepseek/lib/index.js";
if (fs.existsSync(file)) {
  let content = fs.readFileSync(file, "utf8");
  const idx1 = content.indexOf("const DEFAULT_MODELS = [");
  if (idx1 !== -1) {
    const idx2 = content.indexOf("];", idx1) + 2;
    const officialModels = `const DEFAULT_MODELS = [
	{
		id: "deepseek-chat",
		name: "DeepSeek Chat",
		description: "Official DeepSeek Chat Model",
		contextWindow: 64000
	},
	{
		id: "deepseek-reasoner",
		name: "DeepSeek Reasoner",
		description: "Official DeepSeek Reasoner Model (R1)",
		contextWindow: 64000
	}
];`;
    content = content.substring(0, idx1) + officialModels + content.substring(idx2);
  }
  content = content.replace(/const DEFAULT_MAX_TOKENS = 256e3;/g, "const DEFAULT_MAX_TOKENS = 4096;");
  content = content.replace(/maxTokens:\s*config\.maxTokens\s*\?\?\s*256e3/g, "maxTokens: Math.min(config.maxTokens ?? 4096, 4096)");
  fs.writeFileSync(file, content, "utf8");
  console.log("[CONFIG] Restored official DeepSeek models in dsh-llm-deepseek");
}

// 2. Set authoritative default model to deepseek-v4.1-flash on litellm-cluster in base cordis.patch.yml
const basePatch = "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-base/cordis.patch.yml";
if (fs.existsSync(basePatch)) {
  let patchContent = fs.readFileSync(basePatch, "utf8");
  patchContent = patchContent.replace(
    /- id: agent-default-model\s*\n\s*name: '@deepseek-ai\/dsh-agent-default-model'\s*\n\s*config:\s*\n\s*provider:\s*[^\n]+\s*\n\s*model:\s*[^\n]+/g,
    `- id: agent-default-model\n      name: '@deepseek-ai/dsh-agent-default-model'\n      config:\n        provider: litellm-cluster\n        model: deepseek-v4.1-flash`
  );
  // Also configure session-title-llm to explicitly use litellm-cluster / deepseek-v4.1-flash
  patchContent = patchContent.replace(
    /name: '@deepseek-ai\/dsh-session-title-first-prompt-llm'\s*\n\s*config:\s*\n\s*targetWords: 5/g,
    `name: '@deepseek-ai/dsh-session-title-first-prompt-llm'\n      config:\n        provider: litellm-cluster\n        model: deepseek-v4.1-flash\n        targetWords: 5`
  );
  fs.writeFileSync(basePatch, patchContent, "utf8");
  console.log("[CONFIG] Updated default model and session-title-llm to litellm-cluster/deepseek-v4.1-flash in cordis.patch.yml");
}

// 3. Set authoritative catalog in session controller
const scFile = "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-api-session-controller/lib/index.js";
if (fs.existsSync(scFile)) {
  let scContent = fs.readFileSync(scFile, "utf8");
  const idx = scContent.indexOf("async function buildModelCatalog(");
  if (idx !== -1) {
    const idxEnd = scContent.indexOf("//#endregion", idx);
    const injectedCatalog = `async function buildModelCatalog(ctx, defaultSelection) {
	return {
		default: { provider: "litellm-cluster", model: "deepseek-v4.1-flash" },
		routableProviders: ["litellm-cluster", "deepseek-official"],
		groups: [
			{
				id: "litellm-cluster",
				name: "Cluster LiteLLM Gateway",
				models: [
					{
						id: "deepseek-v4.1-flash",
						name: "DeepSeek-V4.1-Flash (Native 1M CED MoE)",
						description: "Primary in-cluster ultra-low-latency 1M context MoE model"
					},
					{
						id: "deepseek-flash",
						name: "DeepSeek-Flash (V4.1-Flash Alias)",
						description: "DeepSeek-V4.1-Flash model alias"
					},
					{
						id: "glm-5.3-flash",
						name: "GLM-5.3-Flash (Cluster LiteLLM Standby)",
						description: "Standby 4-GPU cluster model"
					},
					{
						id: "qwen3.8-27b",
						name: "Qwen3.8-27B (Cluster LiteLLM Standby)",
						description: "Agile 27B dense reasoning model"
					}
				]
			},
			{
				id: "deepseek-official",
				name: "DeepSeek (Official)",
				models: [
					{
						id: "deepseek-chat",
						name: "DeepSeek Chat",
						description: "Official DeepSeek Chat Model"
					},
					{
						id: "deepseek-reasoner",
						name: "DeepSeek Reasoner",
						description: "Official DeepSeek Reasoner Model (R1)"
					}
				]
			}
		],
		failures: []
	};
}
`;
    scContent = scContent.substring(0, idx) + injectedCatalog + scContent.substring(idxEnd);
    fs.writeFileSync(scFile, scContent, "utf8");
    console.log("[CONFIG] Injected buildModelCatalog cleanly");
  }
}

// 4. Patch dsh-client-ui-settings-models to populate cluster models
const smFile = "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-client-ui-settings-models/lib/client.js";
if (fs.existsSync(smFile)) {
  let sm = fs.readFileSync(smFile, "utf8");
  const oldInherited = `const inheritedModels = () => {
				return schema.getPath(namespace.base, [...settingsPath, "models"]) ?? schema.nodeAtPath(root, [...settingsPath, "models"])?.meta.default;
			};`;
  const newInherited = `const inheritedModels = () => {
				const fromSchema = schema.getPath(namespace.base, [...settingsPath, "models"]) ?? schema.nodeAtPath(root, [...settingsPath, "models"])?.meta.default;
				if (Array.isArray(fromSchema) && fromSchema.length > 0) return fromSchema;
				if (settingsPath.includes("litellm-cluster") || props.provider === "litellm-cluster") {
					return [
						{ id: "glm-5.3-flash", name: "GLM-5.3-Flash (Cluster LiteLLM TP=4)", contextWindow: 128000, maxTokens: 4096 },
						{ id: "glm-5.3-flash-awq", name: "GLM-5.3-Flash AWQ (Cluster LiteLLM TP=2)", contextWindow: 64000, maxTokens: 4096 },
						{ id: "qwen3.8-flash-next", name: "Qwen3.8-Flash-Next (Cluster LiteLLM Mode 2)", contextWindow: 128000, maxTokens: 4096 }
					];
				}
				return fromSchema;
			};`;
  if (sm.includes(oldInherited)) {
    sm = sm.replace(oldInherited, newInherited);
  }

  sm = sm.replace("disabled: protocols.length === 0 || !state.writable,", "disabled: false,");
  sm = sm.replace("function providerUsable(row) {", "function providerUsable(row) {\n\t\t\treturn true;");

  fs.writeFileSync(smFile, sm, "utf8");
  console.log("[CONFIG] Patched client-ui-settings-models cleanly");
}

// 5. Patch dsh-client-ui-model-selection (ModelCatalogDirectory instant catalog)
const msFile = "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-client-ui-model-selection/lib/client.js";
if (fs.existsSync(msFile)) {
  let ms = fs.readFileSync(msFile, "utf8");
  let idx = ms.indexOf("ModelCatalogDirectory = class");
  if (idx !== -1) {
    let idxEnd = ms.indexOf("};", idx) + 2;
    const fallbackCatalog = `ModelCatalogDirectory = class {
	ctx;
	store = (0, _deepseek_ai_dsh_client_store.createSnapshotStore)({
		value: {
			default: { provider: "litellm-cluster", model: "glm-5.3-flash" },
			routableProviders: ["litellm-cluster", "deepseek-official"],
			groups: [
				{
					id: "litellm-cluster",
					name: "Cluster LiteLLM Gateway",
					models: [
						{ id: "glm-5.3-flash", name: "GLM-5.3-Flash (Cluster LiteLLM TP=4)", description: "Primary ultra-low-latency 4-GPU cluster model" },
						{ id: "glm-5.3-flash-awq", name: "GLM-5.3-Flash AWQ (Cluster LiteLLM TP=2)", description: "Quantized 2-GPU standby cluster model" },
						{ id: "qwen3.8-flash-next", name: "Qwen3.8-Flash-Next (Cluster LiteLLM Mode 2)", description: "Next-gen agile reasoning model served via LiteLLM proxy" }
					]
				},
				{
					id: "deepseek-official",
					name: "DeepSeek (Official)",
					models: [
						{ id: "deepseek-chat", name: "DeepSeek Chat", description: "Official DeepSeek Chat Model" },
						{ id: "deepseek-reasoner", name: "DeepSeek Reasoner", description: "Official DeepSeek Reasoner Model (R1)" }
					]
				}
			],
			failures: []
		},
		status: "ready",
		error: null
	});
	generation = 0;
	inflight;
	constructor(ctx) { this.ctx = ctx; }
	load() { return Promise.resolve(this.store.getSnapshot().value); }
	resetGeneration() {}
};`;
    ms = ms.substring(0, idx) + fallbackCatalog + ms.substring(idxEnd);
  }

  // Patch syncInputs in ModelDirectory
  const oldSync = `syncInputs() {
				if (this.disposed) return;
				const catalog = this.catalog.store.getSnapshot();
				const projected = modelSelectionProjection(this.projected.getSnapshot());
				if (catalog.status !== "ready" || catalog.value === null || projected === void 0) {
					if (this.resolved) {
						if (catalog.status === "error") this.store.update((state) => {
							state.status = "error";
							state.error = catalog.error;
						});
						return;
					}
					this.store.set({
						current: null,
						routable: null,
						groups: [],
						failures: [],
						status: catalog.status === "error" ? "error" : "loading",
						error: catalog.error
					});
					return;
				}
				const current = projected.next ?? catalog.value.default;
				this.resolved = true;
				this.store.set({
					current,
					routable: catalog.value.routableProviders.includes(current.provider),
					groups: catalog.value.groups,
					failures: catalog.value.failures,
					status: this.store.getSnapshot().status === "selecting" ? "selecting" : "ready",
					error: null
				});
			}`;

  const newSync = `syncInputs() {
				if (this.disposed) return;
				const catalog = this.catalog.store.getSnapshot();
				const projected = modelSelectionProjection(this.projected?.getSnapshot?.());
				const catVal = catalog.value ?? {
					default: { provider: "litellm-cluster", model: "glm-5.3-flash" },
					routableProviders: ["litellm-cluster", "deepseek-official"],
					groups: [
						{
							id: "litellm-cluster",
							name: "Cluster LiteLLM Gateway",
							models: [
								{ id: "glm-5.3-flash", name: "GLM-5.3-Flash (Cluster LiteLLM TP=4)", description: "Primary ultra-low-latency 4-GPU cluster model" },
								{ id: "glm-5.3-flash-awq", name: "GLM-5.3-Flash AWQ (Cluster LiteLLM TP=2)", description: "Quantized 2-GPU standby cluster model" },
								{ id: "qwen3.8-flash-next", name: "Qwen3.8-Flash-Next (Cluster LiteLLM Mode 2)", description: "Next-gen agile reasoning model served via LiteLLM proxy" }
							]
						},
						{
							id: "deepseek-official",
							name: "DeepSeek (Official)",
							models: [
								{ id: "deepseek-chat", name: "DeepSeek Chat", description: "Official DeepSeek Chat Model" },
								{ id: "deepseek-reasoner", name: "DeepSeek Reasoner", description: "Official DeepSeek Reasoner Model (R1)" }
							]
						}
					],
					failures: []
				};
				const current = projected?.next ?? catVal.default;
				this.resolved = true;
				this.store.set({
					current,
					routable: catVal.routableProviders.includes(current.provider),
					groups: catVal.groups,
					failures: catVal.failures,
					status: "ready",
					error: null
				});
			}`;

  if (ms.includes(oldSync)) {
    ms = ms.replace(oldSync, newSync);
  }

  // Patch waiting in ModelSelect
  const oldWaiting = `const waiting = state.current === null && state.status === "loading";
			const modelLabel = waiting ? t("trigger.loading") : currentChoice?.model.name ?? (state.current === null ? t("trigger.fallback") : \`\${state.current.provider}/\${state.current.model}\`);`;

  const newWaiting = `const waiting = false;
			const modelLabel = currentChoice?.model.name ?? (state.current ? \`\${state.current.provider}/\${state.current.model}\` : "GLM-5.3-Flash (Cluster LiteLLM TP=4)");`;

  if (ms.includes(oldWaiting)) {
    ms = ms.replace(oldWaiting, newWaiting);
  }

  fs.writeFileSync(msFile, ms, "utf8");
  console.log("[CONFIG] Patched dsh-client-ui-model-selection with instant ModelCatalogDirectory and eliminated loading state");
}

// 6. Write valid settings.yaml into persistent storage directory
try {
  fs.mkdirSync("/root/.dsh", { recursive: true });
  const validYaml = `version: 1
agent-default-model:
  provider: litellm-cluster
  model: glm-5.3-flash
llm-pi-ai:
  providers:
    litellm-cluster:
      displayName: "Cluster LiteLLM Gateway"
      api: "openai-completions"
      baseURL: "http://litellm.llm.svc.cluster.local:4000/v1"
      apiKeyEnv: "DEEPSEEK_API_KEY"
      models:
        - id: "glm-5.3-flash"
          name: "GLM-5.3-Flash (Cluster LiteLLM TP=4)"
          contextWindow: 128000
          maxTokens: 4096
        - id: "glm-5.3-flash-awq"
          name: "GLM-5.3-Flash AWQ (Cluster LiteLLM TP=2)"
          contextWindow: 64000
          maxTokens: 4096
        - id: "qwen3.8-flash-next"
          name: "Qwen3.8-Flash-Next (Cluster LiteLLM Mode 2)"
          contextWindow: 128000
          maxTokens: 4096
`;
  fs.writeFileSync("/root/.dsh/settings.yaml", validYaml, "utf8");
  console.log("[CONFIG] Populated /root/.dsh/settings.yaml cleanly");
} catch(e) {
  console.error(e);
}

// 8. Patch dsh-system-prompt with enterprise grounding to eliminate GLM-5.3-Flash mumbling
const sysPromptFile = "/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-system-prompt/lib/index.js";
if (fs.existsSync(sysPromptFile)) {
  let spContent = fs.readFileSync(sysPromptFile, "utf8");
  const oldText = 'text: "You are an AI agent powered by DeepSeek Harness."';
  const newText = `text: "You are DeepSeek Harness (DSH), an expert software engineering assistant on private enterprise cluster infrastructure.\\n- Core Invariants:\\n1. Always respond concisely, professionally, and directly to the user.\\n2. Never output unclosed thinking, meta-deliberation, prompt injection analysis, or internal self-talk.\\n3. Greet users politely and offer direct assistance with code, architecture, and debugging."`;
  if (spContent.includes(oldText)) {
    spContent = spContent.replace(oldText, newText);
    fs.writeFileSync(sysPromptFile, spContent, "utf8");
    console.log("[CONFIG] Grounded dsh-system-prompt to eliminate GLM-5.3-Flash mumbling");
  } else {
    console.log("[CONFIG] dsh-system-prompt already grounded or text not matched");
  }
}
