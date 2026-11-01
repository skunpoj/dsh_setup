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
code is the separate upstream fork [skunpoj/DeepInfer](https://github.com/skunpoj/DeepInfer/tree/b4df8657412de7ea8bab8b442c2b8c68f5c1068a).
An actual running-source check found 264 matching published files and one
differing file (`serve/prompt_tokenizer.py`); build sources were partly absent.
This is **not** complete source/binary provenance or a guarantee that a clean
checkout of that commit reproduces the running service.

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
