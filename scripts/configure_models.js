const fs = require("fs");
const dshHome = process.env.DSH_HOME || `${process.env.HOME || "/root"}/.dsh`;

const dshPkgDir = process.env.DSH_PACKAGE_DIR || [
  "/usr/local/lib/node_modules/@deepseek-ai/dsh",
  "/usr/lib/node_modules/@deepseek-ai/dsh"
].find(d => fs.existsSync(d)) || "/usr/local/lib/node_modules/@deepseek-ai/dsh";
const baseModulesDir = `${dshPkgDir}/node_modules/@deepseek-ai`;
// Always validate all pristine inputs before any package/profile write.
const path = require('path'), crypto = require('crypto');
const {verify} = require('./verify_upstream_contract');
const contract = JSON.parse(fs.readFileSync(path.join(__dirname,'upstream_patch_contract.json'),'utf8'));
const mismatches = verify(dshPkgDir,contract);
if(mismatches.length) throw new Error('Unreviewed upstream package; refusing all configuration writes: '+JSON.stringify(mismatches));



// Preflight managed compaction and existing operator instructions before any writes.
const managedCompactionQuality = require('./managed_compaction_quality.cjs');
const compactionFile = `${baseModulesDir}/dsh-compaction-basic/lib/index.js`;
const compactionBefore = fs.readFileSync(compactionFile, 'utf8');
const compactionAfter = managedCompactionQuality.transformSource(compactionBefore);
const managedAgentsPaths = [`${dshHome}/AGENTS.md`, '/workspace/AGENTS.md'];
for (const agentsPath of managedAgentsPaths) {
  if (fs.existsSync(agentsPath)) managedCompactionQuality.appendPolicy(fs.readFileSync(agentsPath, 'utf8'));
}

// Use configuration for catalog/UI/persona; preserve upstream access guards.
if (compactionAfter !== compactionBefore) fs.writeFileSync(compactionFile, compactionAfter, 'utf8');
const dshHost = process.env.DSH_TRUSTED_HOST || 'dsh.example.com';
if (!/^[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?$/.test(dshHost)) throw new Error('Invalid trusted host');
function replaceOnce(source, before, after) {
 if (source.split(before).length !== 2) throw new Error('Reviewed patch anchor is not unique');
 return source.replace(before, after);
}
// 6. Write valid settings.yaml into persistent storage directory
try {
  fs.mkdirSync(dshHome, { recursive: true });
  const validYaml = `version: 1
agent-default-model:
  provider: litellm-cluster
  model: deepseek-v4.1-flash
llm-pi-ai:
  providers:
    litellm-cluster:
      displayName: "Cluster LiteLLM Gateway"
      api: "openai-completions"
      baseURL: "http://litellm.dsh.svc.cluster.local:4000/v1"
      apiKeyEnv: "DEEPSEEK_API_KEY"
      defaultInput:
        - text
        - image
      models:
        - id: "deepseek-v4.1-flash"
          name: "DeepSeek-V4.1-Flash (1M CED MoE)"
          contextWindow: 1048576
          maxTokens: 8192
          input:
            - text
            - image
`;
  fs.writeFileSync(`${dshHome}/settings.yaml`, validYaml, "utf8");
  console.log(`[CONFIG] Populated ${dshHome}/settings.yaml with DeepSeek-V4.1-Flash default`);
} catch(e) {
  console.error(e);
  throw e;
}

// 9. Auto-populate /root/.dsh/AGENTS.md and /workspace/AGENTS.md with dynamic gateway capabilities
try {
  const dshHost = process.env.DSH_TRUSTED_HOST || 'dsh.example.com';
  const tenantPrefix = (dshHost.split('.')[0] || 'dsh').trim();
  const baseDomain = dshHost.includes('.') ? dshHost.substring(dshHost.indexOf('.') + 1) : 'local';

  const agentsMdContent = `# DSH Agent Guidelines & Platform Capabilities

You are running inside a DeepSeek Harness (DSH) container on private enterprise Kubernetes infrastructure.

## 1. Dynamic Application Reverse Proxy Gateway (Web & Port Access)
When you build, develop, or run web applications, APIs, dashboards, or preview servers (e.g., Streamlit, FastAPI, Flask, Vite, Next.js, Node.js, Gradio) on ANY container port \`<port>\`:
- ❌ **NEVER** instruct the user to visit \`http://localhost:<port>\` or \`http://127.0.0.1:<port>\`. Localhost is strictly container-internal and unreachable from the user's browser.
- ✅ **ALWAYS** provide the live external HTTPS gateway URLs to the user:
  - **Option 1 (Subdomain / Recommended for SPAs & Dashboards)**:
    \`https://${tenantPrefix}-<port>.${baseDomain}\` (e.g., \`https://${tenantPrefix}-8501.${baseDomain}\` for Streamlit, \`https://${tenantPrefix}-8000.${baseDomain}\` for FastAPI)
  - **Option 2 (Path Proxy / Direct Access)**:
    \`https://${dshHost}/proxy/<port>/\` (e.g., \`https://${dshHost}/proxy/8501/\`)
- **WebSocket Protocols**: WebSockets are fully supported out-of-the-box for Streamlit, Vite HMR, Next.js Fast Refresh, and real-time streaming sockets.
- **Custom Port Aliases**: You can define friendly names in \`/workspace/.ports.json\` (e.g., \`{"dashboard": 8501, "api": 8000}\`) to enable \`https://${tenantPrefix}-dashboard.${baseDomain}\` or \`https://${dshHost}/proxy/dashboard/\`.

## 2. Storage & File System Persistence
- \`/workspace\`: Persistent enterprise storage backed by Kubernetes volumes. Always place user repositories, scripts, datasets, and projects under \`/workspace\` so they persist across restarts.
- Do not store permanent project data in container-ephemeral root directories.

## 3. High-Performance Cluster Inference
- LiteLLM Gateway is available at \`http://litellm.dsh.svc.cluster.local:4000/v1\`.
- Primary cluster model: \`deepseek-v4.1-flash\` (configured 1M context window).

## 4. Built-in Interactive Web Terminal
- An interactive bash web terminal (powered by ttyd) runs natively on port 7681 (alias \`terminal\` or \`ttyd\`).
- Users can access the web terminal directly via:
  - **Subdomain**: \`https://${tenantPrefix}-7681.${baseDomain}\` or \`https://${tenantPrefix}-terminal.${baseDomain}\`
  - **Path Proxy**: \`https://${dshHost}/proxy/terminal/\` (or shortcut \`https://${dshHost}/terminal\`)
- Web terminal authentication is unified with the DSH Enterprise login session.
`;

  fs.mkdirSync(dshHome, { recursive: true });
  // Preserve existing operator/user instructions; add the managed efficiency block once.
  const quickPolicy = "<!-- DSH:BOUNDED-QUICK-REQUESTS:v1 -->\n## Scope and response efficiency\nFor a simple status, location, or factual question, answer the question directly and briefly. Use the current conversation to identify the relevant target. If the target is ambiguous, state what is known and ask one focused question rather than exploring unrelated systems.\nVerify only the affected facts needed for that question. Batch independent read-only checks in one tool invocation where practical. Once the answer is established, stop investigating and give the result with any material limitation. Do not create or rewrite reports, scripts, dashboards, or other artifacts merely to answer a status/path question unless the user requests them.\nFor these simple questions, normally use a short paragraph or up to five concise bullets. Do not restate a long investigation log. This is a response-efficiency default, not a tool cap: complete broader work and provide detail when requested. Preserve all existing safety, verification, permissions and user instructions; never shorten by guessing, deleting context, or skipping necessary checks.\n<!-- /DSH:BOUNDED-QUICK-REQUESTS:v1 -->\n";
  for (const agentsPath of [`${dshHome}/AGENTS.md`, ...(fs.existsSync("/workspace") ? ["/workspace/AGENTS.md"] : [])]) {
    const existing = fs.existsSync(agentsPath) ? fs.readFileSync(agentsPath, "utf8") : agentsMdContent;
    const next = managedCompactionQuality.appendPolicy(existing.includes("<!-- DSH:BOUNDED-QUICK-REQUESTS:v1 -->") ? existing : existing + "\n\n" + quickPolicy);
    if (!fs.existsSync(agentsPath) || next !== existing) fs.writeFileSync(agentsPath, next, "utf8");
  }
  console.log("[CONFIG] Populated AGENTS.md instructions for DSH agent engine");
} catch(e) {
  console.error("[CONFIG] Failed to write AGENTS.md:", e.message);
  throw e;
}

// 10. Resilient Attachment Handling in dsh-llm-pi-ai (Prevents "Attachment object is missing" fatal turn failure)
const piAiFile = `${baseModulesDir}/dsh-llm-pi-ai/lib/index.js`;
if (fs.existsSync(piAiFile)) {
  let piContent = fs.readFileSync(piAiFile, "utf8");

  // 10a. Patch prepareRequestImages: catch missing/unreadable historical attachments gracefully
  const oldPrepare = `async function prepareRequestImages(messages, attachments, budget, signal) {
	const refs = /* @__PURE__ */ new Map();
	for (const message of messages) collectImageRefs(message.content, refs);
	const orderedRefs = [...refs.values()];
	const prepared = await Promise.all(orderedRefs.map((ref) => attachments.readImageRequest(ref, requestImageTarget(ref, budget), signal)));
	const versions = /* @__PURE__ */ new Map();
	for (const [index, ref] of orderedRefs.entries()) versions.set(ref.attachmentId, prepared[index]);
	return versions;
}`;

  const newPrepare = `async function prepareRequestImages(messages, attachments, budget, signal) {
	const refs = /* @__PURE__ */ new Map();
	for (const message of messages) collectImageRefs(message.content, refs);
	const orderedRefs = [...refs.values()];
	const prepared = await Promise.all(orderedRefs.map(async (ref) => {
		try {
			return await attachments.readImageRequest(ref, requestImageTarget(ref, budget), signal);
		} catch (error) {
			if (signal?.aborted || error?.code !== "ATTACHMENT_NOT_FOUND") throw error;
			return null;
		}
	}));
	const versions = /* @__PURE__ */ new Map();
	for (const [index, ref] of orderedRefs.entries()) {
		if (prepared[index]) versions.set(ref.attachmentId, prepared[index]);
	}
	return versions;
}`;

  {
    piContent = replaceOnce(piContent, oldPrepare, newPrepare);
  }

  // 10b. Patch userContent: handle omitted/missing image gracefully
  const oldUserContent = `		case "image": {
			const version = requestImages.get(block.attachment.attachmentId);
			content.push({
				type: "text",
				text: requestImageHandleText(block.attachment, version, resolveImageAccess(block.attachment))
			});
			content.push({
				type: "image",
				data: Buffer.from(version.data).toString("base64"),
				mimeType: version.mediaType
			});
			break;
		}`;

  const newUserContent = `		case "image": {
			const version = requestImages.get(block.attachment.attachmentId);
			if (!version) {
				content.push({
					type: "text",
					text: \`[image omitted: attachment \${block.attachment?.name || block.attachment?.attachmentId} not found on host]\`
				});
				break;
			}
			content.push({
				type: "text",
				text: requestImageHandleText(block.attachment, version, resolveImageAccess(block.attachment))
			});
			content.push({
				type: "image",
				data: Buffer.from(version.data).toString("base64"),
				mimeType: version.mediaType
			});
			break;
		}`;

  {
    piContent = replaceOnce(piContent, oldUserContent, newUserContent);
  }

  // 10c. Safe access in requiredImageOffload
  const oldOffload = `(block) => requestImages.get(block.attachment.attachmentId).bytes`;
  const newOffload = `(block) => requestImages.get(block.attachment.attachmentId)?.bytes ?? 0`;
  {
    piContent = replaceOnce(piContent, oldOffload, newOffload);
  }

  fs.writeFileSync(piAiFile, piContent, "utf8");
  console.log("[CONFIG] Patched dsh-llm-pi-ai with resilient image attachment handling");
}

// 11. Report missing originals explicitly; never fabricate replacement image evidence.
const alFile = `${baseModulesDir}/dsh-attachment-local/lib/index.js`;
if (fs.existsSync(alFile)) {
  let alContent = fs.readFileSync(alFile, "utf8");
  const oldReadImage = `		if (error instanceof Error && "code" in error && error.code === "ENOENT") throw new AttachmentError("Attachment object is missing.", "ATTACHMENT_NOT_FOUND");
		throw new AttachmentError("Unable to read image attachment.", "ATTACHMENT_READ_FAILED", { cause: error });
	}`;
  const newReadImage = `		if (error instanceof Error && "code" in error && error.code === "ENOENT") throw new AttachmentError("Original image is unavailable; no replacement image was generated.", "ATTACHMENT_NOT_FOUND");
		throw new AttachmentError("Unable to read image attachment.", "ATTACHMENT_READ_FAILED", { cause: error });
	}`;

  {
    alContent = replaceOnce(alContent, oldReadImage, newReadImage);
    fs.writeFileSync(alFile, alContent, "utf8");
    console.log("[CONFIG] Patched dsh-attachment-local to report unavailable originals explicitly");
  }
}

// 11b. Show the real prompt-admission cause (secrets redacted); the client error code is unchanged.
const {rewritePromptAdmission} = require('./prompt_admission_diagnostics.cjs');
for (const file of [`${baseModulesDir}/dsh-api-session-controller/lib/index.js`, `${baseModulesDir}/dsh-api-session-controller/lib/types/commands.js`]) {
  const result = rewritePromptAdmission(fs.readFileSync(file, "utf8"));
  if (result.changed) fs.writeFileSync(file, result.source, "utf8");
}
console.log("[CONFIG] Patched dsh-api-session-controller to report the real prompt-admission cause");

// 12. Enforce Web Profile cordis.patch.yml with Compaction and 1M Context Window
try {
  const profileDir = `${dshHome}/profiles/web`;
  fs.mkdirSync(profileDir, { recursive: true });
  const patchYmlPath = `${profileDir}/cordis.patch.yml`;
  const dshHost = process.env.DSH_TRUSTED_HOST || 'dsh.example.com';
  const tenantPrefix = dshHost.split('.')[0], baseDomain = dshHost.substring(dshHost.indexOf('.') + 1);
  const persona = `Private enterprise deployment. Managed model: deepseek-v4.1-flash (configured 1M context). Respond directly and concisely. For container apps provide https://${dshHost}/proxy/<port>/ or https://${tenantPrefix}-<port>.${baseDomain}; localhost is container-internal. Port aliases are in /workspace/.ports.json. Preserve upstream safety, tool, working-directory and access policies.`;
  const cordisContent = `# Enterprise Cordis Profile Configuration for DSH Web UI
- id: agent-default-model
  config:
    provider: litellm-cluster
    model: deepseek-v4.1-flash
- id: session-title-llm
  config:
    provider: litellm-cluster
    model: deepseek-v4.1-flash
- id: llm-deepseek
  disabled: true
- id: llm-deepseek-account
  disabled: true
- id: system-prompt
  config:
    personaPrefix: ${JSON.stringify(persona)}
- id: ui-settings-account
  disabled: true
- id: workspace-controller
  name: "@deepseek-ai/dsh-api-workspace-controller"
  config:
    documentsDirectory: /workspace
- id: llm-pi-ai
  name: "@deepseek-ai/dsh-llm-pi-ai"
  config:
    providers:
      litellm-cluster:
        displayName: Cluster LiteLLM Gateway
        api: openai-completions
        baseURL: http://litellm.dsh.svc.cluster.local:4000/v1
        apiKeyEnv: DEEPSEEK_API_KEY
        defaultInput:
          - text
          - image
        models:
          - id: deepseek-v4.1-flash
            name: DeepSeek-V4.1-Flash (1M CED MoE)
            contextWindow: 1048576
            maxTokens: 8192
            input:
              - text
              - image

- id: compaction-basic
  disabled: false
  config:
    auto: true
    thresholdRatio: 0.875
    headroomTokens: 65536
    maxTokens: 8192

- id: command-compact
  disabled: false

- id: tool-result-pruner
  disabled: false

- id: ui-settings-general
  name: "@deepseek-ai/dsh-client-ui-settings-general"
  config:
    welcomeNoticeVersion: 2026-09-28.1
`;
  fs.writeFileSync(patchYmlPath, cordisContent, "utf8");
  console.log("[CONFIG] Enforced cordis.patch.yml with auto-compaction and configured 1M context window");
} catch (e) {
  console.error("[CONFIG] Failed to write cordis.patch.yml:", e.message);
  throw e;
}



// Read back every patched and intentionally preserved upstream input.
const {spawnSync} = require('child_process');
const applied = contract.targets.map(entry => {
 const target=path.join(baseModulesDir,entry.path),source=fs.readFileSync(target);
 const sha256=crypto.createHash('sha256').update(source).digest('hex');
 if(entry.patched !== false && sha256===entry.sha256) throw new Error('Expected patch did not change target: '+entry.path);
 if(entry.patched === false && sha256!==entry.sha256) throw new Error('Protected upstream target was changed: '+entry.path);
 if(target.endsWith('.js')){const syntax=spawnSync(process.execPath,['--check',target],{encoding:'utf8'});if(syntax.status!==0)throw new Error('Patched target syntax rejected: '+entry.path+' '+syntax.stderr);}
 return {path:entry.path,patched:entry.patched!==false,upstreamSHA256:entry.sha256,patchedSHA256:sha256};
});
if(fs.readFileSync(alFile,'utf8').includes('fallbackPng'))throw new Error('Synthetic missing-image fallback is forbidden');
console.log(JSON.stringify({reviewedUpstreamVersion:contract.baselineVersion,appliedPatches:applied,scope:'Build-time compatibility overlay; no Production deployment'}));
