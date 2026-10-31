# Upstream patch inventory and maintenance boundaries

`dsh_setup` builds on the official npm package; it is a deployment/compatibility repository rather than a source fork. Never merge the upstream monorepo wholesale into this repository. Track its published release, review relevant source changes and qualify the resulting package with the local overlays.

## Official DSH module modifications

The pristine input contract is `scripts/upstream_patch_contract.json`. The reproducible review export is `patches/dsh-0.2.0-rc.2/`; its neutral hostname is an example, not a Production setting. `scripts/configure_models.js` is the single application engine.

| Module | Local purpose | Regression boundary |
|---|---|---|
| dsh-api-session-controller | Internal model catalog and default route | Actual model-catalog RPC exposes only the managed provider |
| dsh-base | Internal default/title model configuration | Actual web-profile composition |
| dsh-client-connection | Enterprise ingress client helper compatibility | Server Host/auth refusal remains independently enforced; this UI helper is not the server access boundary |
| dsh-client-ui-settings | Persist the managed settings through the host | Private state mounts and authorization remain the storage boundary |
| dsh-client-ui-settings-models | Provider settings/loading compatibility | Managed credentials, server routing and network policy remain authoritative |
| dsh-client-ui-model-selection | Internal catalog and truthful availability/loading state | Catalog fixtures plus real runtime RPC |
| dsh-llm-deepseek | Reviewed default provider catalog/token limits | Internal default is selected; other providers do not gain network access |
| dsh-system-prompt | Enterprise gateway and durable-workspace guidance | Prompt text conveys behavior; it grants no permission |
| dsh-llm-pi-ai | Explicit omission of unavailable historical images | Missing evidence must stay visibly unavailable |
| dsh-attachment-local | Explicit unavailable-original error | Actual missing-image function refuses; no synthetic replacement pixels |

Every target is checked before any package/profile mutation. Root/module package identity and version must also match. Expected changes must not be silently skipped and JavaScript output must parse. Altered/missing upstream targets and repeated application to an already patched installation are refused. Changes are applied to fresh candidate assemblies, never by guessing the state of a running installation.

## Components outside the official DSH patch set

| Component | Repository customization | Update treatment |
|---|---|---|
| Gateway/authentication/dashboard | Independent local source, tests and Kubernetes overlays | Retain routing, password, audit and browser regression checks |
| Storage/environment isolation | Kubernetes mounts, private routing and network policies | Preserve state; qualify actual identity, persistence and network boundaries |
| LiteLLM/context forwarding | Local middleware and mirrored GPU-stack runtime | Separate model/proxy acceptance; a DSH package update does not automatically validate these changes |
| Managed SDK budget loader | Hash-guarded loader hook in managed_inference_transport.cjs | Review the SDK source hash and budget/abort/other-origin tests |
| Claude Code and TrueForge | Pinned packages, managed policy and guarded TrueForge compatibility edit | Independent package contracts and actual client checks |
| SGLang scheduling | GPU-runtime patches under gpu-stack | Independent runtime/source contracts and capacity/fairness tests |

## Release procedure

Use the scheduled/manual upstream-candidate workflow to detect published changes. The default follows npm latest; previews require explicit selection. Changed targets stop the candidate. Review whether upstream already supplies a local fix, remove redundant patches, adapt remaining changes and tests, then regenerate the export. Do not auto-update trusted hashes.

Source tests and installed-package smoke tests precede copied-state, browser/WebSocket, attachment/tool, compaction, network/user boundary and rollback acceptance. A passing CI build is not a Production upgrade. Package/profile generation must run only against fresh candidate state; it is not a migration tool for mounted user histories.
