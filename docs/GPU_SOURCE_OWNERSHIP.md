# GPU source ownership and release map

This page defines the public, portable source boundary. It deliberately omits
private domains, registries, node names, namespaces, identities, credentials,
storage bindings and live workload IDs.

## Canonical public locations

| Concern | Canonical public location | What it proves |
|---|---|---|
| DSH, LiteLLM and portable installation source | [`skunpoj/dsh_setup`](https://github.com/skunpoj/dsh_setup) | Sanitized source, examples, tests and a fresh-install renderer |
| Current DeepInfer + DSpark/NCCL launch contract | [`gpu-stack/profiles/deepinfer-dspark-nccl-current.json`](../gpu-stack/profiles/deepinfer-dspark-nccl-current.json) | Reviewed arguments and non-secret environment settings; not a full cluster export |
| SGLang + DSpark rollback reference | [`gpu-stack/profiles/sglang-dspark-rollback.json`](../gpu-stack/profiles/sglang-dspark-rollback.json) and [`gpu-stack/templates/model.yaml`](../gpu-stack/templates/model.yaml) | Portable rollback arguments, overlays and gates |
| Proposed DeepEP trial | [`gpu-stack/profiles/deepinfer-dspark-deepep-proposed.json`](../gpu-stack/profiles/deepinfer-dspark-deepep-proposed.json) | Review-only delta; not deployed or qualified |
| Functional Service names | [`gpu-stack/runtime/canonical-services.yaml`](../gpu-stack/runtime/canonical-services.yaml) and [`gpu-stack/NAMING.md`](../gpu-stack/NAMING.md) | Sanitized routing contract; site overlays choose the namespace and compatibility aliases |
| Host change, peer-copy qualification and rollback | [`gpu-stack/runbooks/gpu-peer-access.md`](../gpu-stack/runbooks/gpu-peer-access.md) | Ordered administrator procedure and fail/rollback gates |
| Measurements and administrator report | [`docs/gpu-platform/GPU_PLATFORM_REVIEW.pdf`](gpu-platform/GPU_PLATFORM_REVIEW.pdf) | Bounded measured evidence and conditional scenarios with explicit limitations |
| DeepInfer engine source | [`skunpoj/DeepInfer`](https://github.com/skunpoj/DeepInfer) | Public engine fork; a source comparison is not a reproducible running-image proof |

## Private operational boundary

An existing installation still requires a private site-deployment repository or
equivalent controlled release system for domains, certificates, registry
destinations, storage, identities, Secrets, image promotion, cluster overlays,
monitoring and rollback receipts. Those values must not be copied into this
public repository.

The public profiles are intentionally inspect-only. They do not create Secrets,
load weights, contact Kubernetes, or authorize a rollout. The portable renderer
builds the SGLang-compatible reference; it is not a renderer for the current
DeepInfer workload. A complete DeepInfer release additionally needs a pinned
engine commit, dependency/submodule pins, a reproducible image recipe and digest,
the site overlay, and source-to-running-workload evidence.

## Media and documentation rule

The PDF above is the current GPU evidence document. Earlier GPU PowerPoint,
HTML and video editions are historical unless their manifest explicitly pins
the current report, public source commit and engine commit. The Current library
must not silently reuse an older GPU recording. Updating source or the PDF does
not update spoken media.

## Release acceptance

For an existing installation, acceptance requires all of the following:

1. public portable source and private overlay are mapped path by path;
2. the build records the exact source commits and immutable image digests;
3. the running workload is read back and matched to those digests and mounted
   source/configuration;
4. routing, authenticated behavior, model correctness, recovery and rollback
   are tested in the authorized environment;
5. the current PDF, HTML, slides, captions, video and public discussion text are
   checked against that same accepted release.

CI success, file presence, readiness or a Service name alone does not satisfy
these gates.
