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

This protects the supplied installations, not arbitrary programs a user writes. An Internet environment intentionally allows downloads and network access; a user can run an alternative client there. Administrators controlling the host, image, Secrets or cluster can change policy. No claim of absolute immutability is made.

## Isolation and use

Run `claude` from the authenticated DSH terminal. Run `trueforge` to start its private server on port 3000, then use the existing authenticated [DSH app route](https://dsh-3000.aiportal.bot.or.th). It uses `/state/trueforge` within the current user's selected environment, separate from DSH history. NetworkPolicy permits ingress only from the DSH gateway; the gateway selects the logged-in user's environment/runtime. There is no new public unauthenticated Ingress. Start it only when port 3000 is free; other applications may already use that app port.

LiteLLM must set `use_chat_completions_url_for_anthropic_messages: true`. Without it the protected canonical route receives unsupported `/responses` requests and returns 404. The switch was tested first on a separate LiteLLM candidate with the same guard, then applied to the existing gateway. No inference-backend restart is required.

The existing user/environment separation, CIFS workspace mounts, histories, Kerberos tickets, network policies and shared GPU model remain independent of these tool configurations. TrueForge local sandbox availability must be tested in the restricted container; no privileged container, host socket or additional datalake access is granted to make it work.

## Deployment and rollback

Build and inspect the candidate image first. Test inference, configuration-override attempts and a real harness turn before rollout. Preserve each deployment specification and durable markers, then update one private runtime at a time. Do not reapply bootstrap manifests over live private routing. On failure restore the saved image/specification; do not restore older workspace or history content over newer writes.

Status: source prepared; image build and live acceptance pending. This status must be replaced with observed results before declaring deployment complete.

Official references: [Claude gateway configuration](https://code.claude.com/docs/en/llm-gateway), [managed settings](https://code.claude.com/docs/en/managed-settings), [model restrictions](https://code.claude.com/docs/en/model-config), [TrueForge repository](https://github.com/truefoundry/trueforge), [TrueForge models](https://github.com/truefoundry/trueforge/blob/main/docs/models.mdx).
