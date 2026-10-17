# Portable GPU + LiteLLM + 1M setup

This is the public counterpart for the GPU inference portion of the deployment repository. It contains sanitized source and a renderer, not a copy of private cluster configuration. No organization endpoints, node names, private registries, credentials, user identities, central-share paths or live workload IDs are required by this bundle. Public upstream image digests and model names remain to identify the qualified software.

## Features and design

```mermaid
flowchart LR
  D[Private DSH runtime] --> L[Authenticated LiteLLM :4000]
  C[Managed Claude Code / TrueForge] --> L
  L --> F[Loopback final-payload guard :4001]
  F --> S[Shared SGLang :8000 / four GPUs]
  L --> P[Private PostgreSQL]
  W[Pre-staged read-only weights] --> S
```

- One shared model copy; user workspace/history isolation belongs to the DSH deployment, not to GPU allocation.
- 1,048,576 total tokens, at most 8,192 output tokens and a 256-token reserve. The final forwarded messages/tools are counted with the backend tokenizer. Input plus requested output plus reserve must fit.
- One request with input plus reserved output above 131,072 is admitted at a time. A second long request waits at most 300 seconds and receives 429. The two configured aliases have no hidden rate-limit retries. Ordinary work remains concurrent; the model running cap is 16, not sixteen full 1M conversations.
- Small prefill chunks (1,024; maximum prefill 2,048), mixed prefill/decode, a pinned scheduler reservation and a single chunk-owner guard preserve memory and short-request opportunities. Before each long warm step, foreground streams may drain for up to eight seconds. This is cooperative scheduling, not preemption or a latency guarantee.
- One gateway replica with Recreate is essential: admission uses a local process-shared file lock. Do not scale replicas/workers without a distributed admission design.
- Only two local aliases are exposed. There is no external fallback. No ingress, public hostname, shared workspace, database password or client API key is embedded. The final-wire listener binds to loopback and is never a Service.

## Setup method

1. Use a new test namespace first. Install the NVIDIA device plugin and an enforcing Kubernetes network-policy implementation through the cluster's approved process. Reserve four compatible GPUs and sufficient host memory; the template requests 256 GiB RAM and permits 512 GiB. Check node capacity before scheduling. No extra node is assumed.
2. Pre-stage the licensed/approved model files on a PVC named `model-weights`, at `/approved` within the volume. Verify the complete weights against the approved upstream manifest, revision and hashes. `config.json` existence is only a startup check, not integrity evidence. Review any model code before allowing `--trust-remote-code`; the cache is read-only and runtime downloads are disabled. The model image is public and digest-pinned. Registry/image availability and model license approval remain operator prerequisites.
3. Provision PostgreSQL with protected durable storage and recovery according to your environment. In this namespace its pods must have `app: llm-database` and listen on 5432. This bundle does not install or migrate a database. An external database requires a separately reviewed narrow egress rule; do not permit all egress to make startup pass.
4. Create two existing Secrets through your private secret-management process: `local-inference-credentials` with `LITELLM_MASTER_KEY` and a random `INTERNAL_ROUTE_KEY`; `local-inference-database` with `DATABASE_URL`. Never commit their values or rendered secret manifests. The master key is for operators; issue restricted model-only per-runtime virtual keys to clients, not the master key. Check management endpoints are denied for those keys.
5. Install Python 3.10+ and PyYAML for rendering. Copy `settings.example.json` to a private settings file outside the repository. Set the namespace/PVC/Secret names and qualified gateway digest. Run:

   ```sh
   python gpu-stack/render.py --settings /private/settings.json --output /private/candidate.yaml
   kubectl -n <test-namespace> apply --dry-run=server -f /private/candidate.yaml
   ```

   The renderer does not create the namespace or contact the cluster. It rejects unexpected setting keys, invalid names, mutable image tags and overwriting an existing candidate. Review the emitted objects before applying. Pin changes to the SGLang image require requalifying both scheduler source hashes; changed source fails closed.
6. Apply only to the reviewed test namespace. Database/Secrets/PVC must already exist. NetworkPolicy allows same-namespace `inference-client: allowed` pods to reach the authenticated gateway, the gateway to reach only the model/database/DNS, and the model no outbound network. There is no direct client access to the unauthenticated model. Namespace label changes and allowed-client labels are operator privileges. DNS examples assume ordinary kube-dns labels: verify against your CNI and NodeLocal DNS implementation. Generic DNS access is not protection against DNS exfiltration; use an internal-only resolver and test it before classifying the whole environment No Internet. Client, execution-worker and database policies are separate required controls.
7. Verify actual readiness, image IDs, mounted source hashes, model identity, token limits and an authenticated exact reply. Check key-management denial, direct model denial, endpoint-override rejection, public TCP/domain/direct-IP/DNS denial and internal service access. Readiness alone is insufficient. Do not replace a working Production service with this portable candidate without these checks.
8. Point managed DSH/CLI profiles at the private gateway Service with restricted keys. Set matching 1M context, output ceiling, long-response timeout and compaction budget. The existing DSH managed transport handles the qualified SDK's character-based output-budget bug; this GPU bundle does not install those client hooks. Follow [client setup and results](../docs/LLM_SETUP_AND_TEST_RESULTS.html) and qualify each installed client/version separately.

## Qualification, performance and rollback

Run progressive 128K, 256K, 512K and near-1M tests with distributed known answers and source citations, plus substantial output and real tool continuation. Verify persisted replies, exact final payload counts, cancellation, over-budget refusal, second-long admission/429, zero hidden retries and cache reuse with normalized tool defaults. During each long test run real short DSH conversations; record time to first text, elapsed time, output length and output rate separately. A direct API burst is not end-to-end DSH or CLI acceptance.

Recorded deployment experience: increasing static allocation to 0.92 left too little temporary attention memory and a roughly 262K request caused OOM. The accepted family of profiles uses 0.90 with bounded prefill. A later cold near-1M DSH request completed in about 19.5 minutes; cached tool continuation was much faster. The most recent scheduling cycle recorded 32/32 ordinary DSH replies while long preparation continued. Paired replies during near-1M preparation took 4.05–8.63 seconds; eight simultaneous replies took 7.66–8.68 seconds. The latest cold SDK test exposed a one-token output clamp; after the client-hook correction the same retained near-1M prompt passed in a 6.08-second **cached** retest. A new cold full-answer retest after that correction was not performed. These are recorded cases, not fresh tests of this generic manifest, an SLA, universal analytical accuracy, or two concurrent 1M requests. See the separate results guide for complete scope and failures.

Before changes, save private manifests, exact images, source ConfigMaps, settings and state-preservation checks. Recreate of the only GPU deployment interrupts inference; prepare a maintenance handover. Keep the last qualified 128K profile, image and source overlay available. Roll back on startup failure, incorrect replies, lost history, regression in ordinary latency or GPU restart. Reconcile newer durable writes before any storage restore; changing inference should not change storage mounts. This bundle does not mount or migrate user data.

## Source maintenance and publication boundary

`runtime/` is a reviewed public derivative of the deployment's forwarding/guard/scheduler source. Deliberate differences: the tokenizer URL is mandatory configuration, unrelated-provider fallback is rejected, synthetic prompt capture is removed, and organization-specific patch marker names are neutralized. Algorithm constants and patch-source hashes are retained. Regenerate/review/test these copies when canonical code changes; do not maintain divergent fixes silently. `SOURCE_MANIFEST.json` binds this publication to source-content hashes without disclosing private repository paths or endpoints.

The new bundle is sanitized. Existing repository documentation/history contains site-specific deployment records; this addition does not redact that earlier material or claim repository-wide sanitization. Private settings, keys, database URLs, infrastructure addresses, storage paths and generated cluster output must stay outside Git. Existing Production remains unchanged by rendering or publishing this bundle.

## CI activation

`ci-example.yml` is a reviewed GitHub Actions example, not an active workflow. The publishing token cannot create/update workflow files, so an authorized repository maintainer must copy it to `.github/workflows/portable-gpu.yml` to enable automatic checks. The Linux qualification was run directly; publishing this example does not claim hosted CI passed. It runs the guard/manifest/privacy checks and rejects canonical forwarding-source drift.
