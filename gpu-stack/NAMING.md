# GPU serving names

The shared naming contract is [naming.json](naming.json). These are the live
canonical Service names. Legacy resource names remain only as compatibility
aliases or immutable workload identities.

| Component | Canonical name | Meaning |
|---|---|---|
| DSH gateway Service | `dsh-gateway` | Browser and workspace gateway |
| LiteLLM gateway Service | `litellm-gateway` | Model routing and policy |
| Current model Service | `deepinfer-dspark` | Selects only the active DeepInfer + DSpark workload |
| Rollback model Service | `sglang-dspark` | Selects only the stopped SGLang + DSpark rollback workload |
| Current engine Deployment | `deepinfer-v4-1-flash` | DeepInfer + DSpark |
| Rollback engine Deployment | `vllm-deepseek-v4-1-flash` | Compatibility workload identity; SGLang + DSpark; normally stopped |
| API served-model ID | `deepseek-v4.1-flash` | Model identity; not a Kubernetes resource name |

DNS/Kubernetes names use lower-case kebab case. New routing uses functional
Service names. Profile IDs retain the
engine and transport, such as `deepinfer-dspark-nccl-current`.

## Safe migration order

1. Record live resource UIDs, selectors, EndpointSlices, client routes, current
   image/source overlays and the active operator. Resolve ownership conflicts.
2. Add the canonical model Service with the same ports and the verified active
   engine selector. Inspect actual EndpointSlices and GET-only health/model
   metadata through the new route. Do not send an unapproved inference request.
3. Update the context-forwarder/LiteLLM target, ingress, internal DNS allowlist,
   NetworkPolicies, monitoring, switcher, watcher and recovery scripts in one
   reviewed source change. Verify old and new endpoint dependencies before
   retiring the temporary compatibility alias.
4. Create the correctly named SGLang rollback workload at zero replicas only
   after its source, selector and switch/recovery references are reviewed. Do
   not accidentally allocate the four GPUs to both engines.
5. Existing Deployment selectors cannot be renamed in place. Clean up legacy
   labels only in a coordinated replacement/recovery window; do not delete the
   active engine as a naming shortcut. Keep PVCs, sessions and watchers intact.
6. Match running source/images to the accepted commit, verify routing and
   authorized behavior, then update the current report and architecture video.
   Keep original evidence unchanged and distinguish before/after observations.

The legacy Services `dsh-environment-gateway`, `litellm` and
`vllm-deepseek-v4-flash`, the SGLang Deployment
`vllm-deepseek-v4-1-flash`, and the shared selector value are compatibility
inputs only.
Their names do not mean the active engine is vLLM. The active DeepInfer process
starts `serve/openai_server.py`.

Never globally replace `vllm`: actual upstream package/module names, the
`vllm-project/humming` repository, retained upstream URLs, historical logs and
immutable third-party image references must remain accurate. The portable
renderer currently uses generic `local-model` and `local-inference` names;
that standalone SGLang example is not a declaration that Production was renamed.

Inspect profile output with the canonical target names:

```sh
python gpu-stack/profiles/inspect_profile.py deepinfer-dspark-nccl-current --model-path /models/approved
```

Inspection emits no Kubernetes changes and does not contact the cluster.

## Current runtime contract

The four canonical Services are defined in
[`runtime/canonical-services.yaml`](runtime/canonical-services.yaml). Production
ingress routes use `dsh-gateway`, `litellm-gateway` and `deepinfer-dspark`.
LiteLLM targets `deepinfer-dspark`; provisioned workspace templates use
`litellm-gateway`. `sglang-dspark` intentionally has no endpoints while the
rollback Deployment remains at zero replicas. Legacy Services stay available
temporarily for rollback and for external consumers that have not yet supplied
their migration evidence; they are not names for new configuration.

