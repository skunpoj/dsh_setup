# Three serving profiles, one setup repository

Canonical resource names and the coordinated migration are defined in the
[shared naming contract](../NAMING.md). Inspection output includes target names
and explicitly marks runtime migration pending; it does not rename live resources.

| Profile | Role | Status |
|---|---|---|
| [SGLang + DSpark](sglang-dspark-rollback.json) | Four-GPU TP4 rollback | Retained short-benchmark reference; not a second simultaneous server |
| [DeepInfer + DSpark / NCCL](deepinfer-dspark-nccl-current.json) | Current four-rank DP4/EP4 reference | Host-UVA Engram, NCCL expert exchange, NVL peer limit |
| [DeepInfer + DSpark / DeepEP](deepinfer-dspark-deepep-proposed.json) | Controlled trial after host integrity checks | **Proposed, not deployed or qualified** |

These are non-secret argument/environment references, not complete cluster exports.
The current DeepInfer process is `serve/openai_server.py`, not vLLM. The old
Service/deployment naming and the SGLang base image do not select the inference
engine. Both engine alternatives expose compatible HTTP APIs to LiteLLM.

The SGLang [Kubernetes reference](../templates/model.yaml) retains scheduler/indexer
patches and validation gates. [The portable renderer](../render.py) covers that
SGLang-compatible bundle; it is not a DeepInfer renderer. The DeepInfer engine
code is the separate upstream fork [skunpoj/DeepInfer](https://github.com/skunpoj/DeepInfer/tree/c1b8cc6da34ac17c1f2522baa1ddf98a5a1d49ca).
A fresh comparison of all 293 mounted Python paths against that exact public
successor found 17 byte-identical files, 274 line-ending-only differences, two
content differences and no missing path. The two content differences are newer
public fixes—strict boolean parsing and an explicit kernel-filename regex—not yet
present in the known-working runtime. The previously staged offline controls are
now committed in the public successor. A prior private release verified its own
293-file mounted-source manifest and passed one authenticated, non-sensitive
DSH-to-LiteLLM-to-DeepInfer smoke request without retry; that receipt proves the
earlier private release, not equality with this newer public successor. Compiled
artifacts, vendor submodules, the base image and a reproducible public-to-runtime
build remain separate qualification boundaries. DeepEP remains proposed and
unqualified.

Inspect a plan without running it:

```sh
python gpu-stack/profiles/inspect_profile.py deepinfer-dspark-nccl-current --model-path /models/approved
python gpu-stack/profiles/inspect_profile.py sglang-dspark-rollback --model-path /models/approved
python gpu-stack/profiles/inspect_profile.py deepinfer-dspark-deepep-proposed --model-path /models/approved --review-proposed
python -m unittest discover -s gpu-stack/profiles -p 'test_profiles.py'
```

The inspector never executes a process, applies Kubernetes resources, loads
weights or authorizes a change. The proposed delta changes only expert exchange
from `nccl` to `deepep`; CP stays `nccl`, GIN stays disabled, and Engram stays
host-UVA. Do not turn on unrelated cache/transport changes at the same time.

Follow [the administrator and recovery runbook](../runbooks/gpu-peer-access.md)
and [the current report](../../docs/gpu-platform/GPU_PLATFORM_REVIEW.pdf).
Site-specific addresses, identities, credentials, storage bindings and evidence
remain private. The existing internal Azure operational repository/pipeline has
not yet completed its cutover to this public setup repository.
