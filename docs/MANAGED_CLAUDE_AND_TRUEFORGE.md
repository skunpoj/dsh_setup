# Managed Claude Code and TrueForge in DSH

## Purpose and scope

Install both tools in the prebuilt DSH Kubernetes image, including No Internet runtimes. No laptop configuration is changed. Installation at image build time avoids requiring Internet access during restart.

Pinned candidates: Claude Code 2.1.301 and official `@truefoundry/trueforge` 0.179.2. Both route to internal LiteLLM and use `deepseek-v4.1-flash`. This is a deployment overlay; it is not a claim that Anthropic supports DeepSeek as a Claude Code backend.

## Existing settings verification

On 16 October 2026, the external ingress accepted Anthropic Messages requests for both `claude-sonnet-4-6` and `deepseek-v4.1-flash`, returning exactly `LEGACY_SETTINGS_OK`. TLS verification remained enabled. The old DSH inference credential instead returned 403 for Messages: it permits Chat Completions but not this API. A successful API request does not establish that every key in the old settings file is understood by every Claude Code version, or validate its claimed 1M compaction behavior.

The managed configuration uses documented provider/model restrictions rather than relying on a display label or alias. It does not copy plaintext API keys, disable TLS verification, or change the Windows user's configuration.

## Configuration enforcement

Claude reads root-owned `/etc/claude-code/managed-settings.json`. Its model allowlist uses exact matching, includes the Default option, and permits only the configured custom endpoint. A credential helper reads the runtime's dedicated Kubernetes Secret. Ordinary runtime UID 10001 cannot rewrite the policy or the installed executable.

TrueForge's pinned standalone model store is replaced with an operator-owned store. It exposes one model on one fixed LiteLLM origin, reads the dedicated credential at startup, and ignores mutable provider rows in its session database. Provider create/update/delete requests return 403. The patch requires the reviewed SHA-256 and unique anchors; a changed upstream package stops the build.

This protects the supplied installations' model identity and endpoint, not every user preference or arbitrary program a user writes. The same model's context-window selection is not a different model. An Internet environment intentionally allows downloads and network access; a user can run an alternative client there. Administrators controlling the host, image, Secrets or cluster can change policy. No claim of absolute immutability is made.

## Isolation and use

Run `claude` from the authenticated DSH terminal. Run `trueforge` to start its private server on port 3000, wait for the server-listening message, then use the existing authenticated [DSH app route](https://dsh-3000.aiportal.bot.or.th). It uses `/state/trueforge` within the current user's selected environment, separate from DSH history. NetworkPolicy permits ingress only from the DSH gateway; the gateway selects the logged-in user's environment/runtime. TrueForge's own standalone login is off because the outer DSH gateway supplies authentication; it is not an independently public service. Start it only when port 3000 is free; other applications may already use that app port.

LiteLLM must set `use_chat_completions_url_for_anthropic_messages: true`. Without it the protected canonical route receives unsupported `/responses` requests and returns 404. The switch was tested first on a separate LiteLLM candidate with the same guard, then applied to the existing gateway. No inference-backend restart is required.

The existing user/environment separation, CIFS workspace mounts, histories, Kerberos tickets, network policies and shared GPU model remain independent of these tool configurations. Claude state uses `/state/claude` through `$HOME/.claude`; TrueForge uses `/state/trueforge`. These new tool stores are private persistent state-volume directories, not an additional shared CIFS workspace. Existing DSH central history locations are unchanged.

TrueForge chat, its API and managed model connection are operational. Its code sandbox is **not enabled or qualified**: the restricted container refuses nested user namespaces (`unshare -Ur`, Operation not permitted), and the optional Linux sandbox dependencies are not installed. No privileged container, host socket or additional datalake access was granted. Claude's existing-pod Bash tool was exercised successfully; that does not validate TrueForge's separate sandbox.

Claude Code's default reports **200,000 context tokens**. `claude --model 'deepseek-v4.1-flash[1m]'` reports **1,000,000** and returned the correct short test answer. An attempted `--model claude-opus-4-6` also resolved to the permitted DeepSeek model, rather than switching to Claude. These are client-selection tests, not near-1M inference, timeout or compaction acceptance. The old `autoCompactWindow: 1000000` example alone does not establish those behaviors. Main DSH's existing 1M profile remains unchanged; TrueForge advertises 1,048,576 from managed model metadata, but no near-1M TrueForge turn was run. Both new tools use the existing gateway's output/budget guard.

The external Ollama embedding example returned 1,024 values with TLS verification enabled. A subsequent loaded-model readback reported `bge-m3:latest` with `size_vram: 0`. It is unnecessary to copy `verify=False` into this working external example. This does not add a new public egress exception to No Internet runtimes.

## Deployment and rollback

Build and inspect the candidate image first. Test inference, configuration-override attempts and a real harness turn before rollout. Preserve each deployment specification and durable markers, then update one private runtime at a time. Do not reapply bootstrap manifests over live private routing. On failure restore the saved image/specification; do not restore older workspace or history content over newer writes.

**Deployed:** all 20 main DSH runtimes use image digest `595452b9d14f79bc5415795145967df713288f49db5f4699db570bcda4c3c5a6`, produced by Azure build **62790**, source `52bf535850c5d5c3991ebcdb3aeece776785803e`. Legacy DSH2/DSH3 were not changed.

| Verification | Observed result |
|---|---|
| Actual production client turns | Claude exact response in 0.853 s; TrueForge exact persisted-session response in 0.454 s; small synthetic samples, not an SLA |
| Claude tools | Actual Bash execution returned `MANAGED_TOOL_OK` without a permission denial |
| Configuration protection | Operator-file writes denied; TrueForge provider POST/PUT/DELETE each returned 403; attempted gateway endpoint override returned 401 |
| Per-runtime rollout | 20 exact inference responses, 20 preserved 1M DSH profiles, 40 durable workspace/attachment markers |
| Existing access | 16 private logins passed; 16 peer legacy-history reads denied; thanatcc still lists 80 legacy histories |
| New-tool persistence | One Claude session file stayed byte-identical, and the TrueForge synthetic history remained available after actual pod replacement |
| App gateway | Anonymous request showed the password login form; authenticated request returned TrueForge's HTML app shell and exact managed model API data |
| Environments | Fresh Secure requests to GitHub/npm were denied; Internet returned HTTP 200; both ran as UID 10001 |
| Shared inference | Same model pod UID and zero restarts; no GPU-server reload or large-context stress run for this installation |

The first image build failed because Claude's native installer had been skipped; it was corrected before deployment. An early restart probe checked the app after a fixed three-second delay and received 502 while TrueForge was starting. Acceptance now waits for actual authenticated app content. These fixture/build failures are distinct from loss of stored histories.

See [live acceptance evidence](context-evidence/managed-harnesses-live-20261016.json). For a newly provisioned runtime, provision a dedicated harness Secret and use `scripts/rollout_managed_harnesses.py --names <runtime> ...`; installing an image alone does not issue credentials. Keep private deployment snapshots for rollback. Existing account passwords and user-supplied API keys are not embedded in Git or images.

Official references: [Claude gateway configuration](https://code.claude.com/docs/en/llm-gateway), [managed settings](https://code.claude.com/docs/en/managed-settings), [model restrictions](https://code.claude.com/docs/en/model-config), [TrueForge repository](https://github.com/truefoundry/trueforge), [TrueForge models](https://github.com/truefoundry/trueforge/blob/main/docs/models.mdx).
