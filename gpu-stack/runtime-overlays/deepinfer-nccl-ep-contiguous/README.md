# DeepInfer nccl_ep.py contiguity overlay

This private operational overlay replaces exactly one mounted runtime file:
`/work/runtime/deepinfer/model_executor/parallel_utils/nccl_ep.py`.

**Revised 2026-11-12** per lane 9's review
(`LANE9-CHECK-LANE6-NCCL-EP-OVERLAY-35914744-ROLLBACK-MERGE-KEY`): the
ConfigMap now sets `immutable: true`, and `03-rollback-patch.yaml`'s
`volumeMounts` delete entry keys on `mountPath`, not `name` --
`v1.Container.VolumeMounts`' strategic-merge key is `mountPath`; only
`v1.PodSpec.Volumes` merges by `name`. The first posted revision used `name`
for both and would not have matched the live entry to delete.

## Why

`NcclEPBuffer._all_to_all` called `torch.distributed.all_to_all_single` on a
tensor that is not always contiguous: `dispatch`'s `send[:, :capacity].reshape(...)`
and `combine`'s `partial.to(torch.bfloat16)` (a no-op once the tensor is
already bfloat16, so it preserves whatever layout `partial` already had)
can both hand it a non-contiguous view. On a small/irregular batch
(observed live: `topk_idx.shape == (1, 6)`) this raised `ValueError: Tensors
must be contiguous`, which killed all 4 engine ranks
(`[server] engine rank(s) [0, 1, 2, 3] died`), followed by a `BufferError:
cannot close exported pointers exist` from the multimodal pool's shutdown
cleanup -- a symptom of the abrupt shutdown, not the cause (ledger
`LANE6-CRASHLOOP-ROOTCAUSE-20261112`). The fix adds one `send =
send.contiguous()` call inside `_all_to_all` itself -- the single chokepoint
both call sites go through -- which is a no-op (same tensor, no copy)
whenever the input is already contiguous, so it costs nothing on the
working path.

Pinned identities:

- Predecessor (DeepInfer-sm90-implementation commit): `a06c8ff46d390d462466deac588e24766cd67b97`
- Predecessor `nccl_ep.py` SHA-256: `f1767684b0d4abc50c9b836bc4a7cb9a6ee52c2fe768eb679bdab6a21e03735b`
- Successor `nccl_ep.py` SHA-256: `885c972713d6783862c9cb337ff5b373c095e089d3ec2bb12f5fe780122339df`
- Fix + test patch (against the DeepInfer source repo, not this overlay): `LANE6_NCCL_EP_CONTIGUOUS_FIX_20261112.patch`, SHA-256 `6dd3f04df5a56c42ec03ebf0c604d9a25f65f663d8e828a48ab6a2e8513e4855`

## Tested

A CPU-only Job (no GPU, isolated namespace, image pinned to
`sha256:4a5d132a...`) ran the new regression test
(`tests/distributed/test_nccl_ep_contiguous_all_to_all.py`) plus the
existing `tests/distributed/test_nccl_ep.py` (6 cases), on the unpatched
file and then the patched one (`OPERATOR-ENGINE-FIX-CPU-TEST-JOB-RESULT`):
run A (unpatched) failed with the expected `Tensors must be contiguous`
error with the 6 existing cases still passing; run B (patched) passed, all
7 cases green. This matches the result predicted when the fix and test were
drafted.

## Applying

The successor is mounted from the immutable ConfigMap rather than copied
into the shared PVC. Applying `02-successor-patch.yaml` therefore leaves
the PVC bytes unchanged and makes rollback deterministic.
`03-rollback-patch.yaml` removes only this overlay.

Before applying, verify the predecessor hash against the running pod
(`kubectl logs`'s traceback line numbers already matched this commit
exactly, cross-checked separately against a public-mirror provenance
comparison -- see ledger `LANE6-NCCL-EP-STAGING-PATH-20261112`), confirm no
long request is active or queued, and retain the predecessor bundle.

**Restart required.** Unlike a ConfigMap data change alone, this is a new
volume/volumeMount on the Deployment's pod template, so Kubernetes will
recreate the pod (`strategy: Recreate` on this Deployment: the old pod
terminates fully before the new one starts). Restart only the
`deepinfer-v4-1-flash` Deployment. Do not start the four-GPU SGLang
workload concurrently. Based on today's observed crash-to-Ready timing
(~4 minutes) plus image pull / model and CUDA-graph reload overhead, expect
an outage in the same range the admin UI's own restart control quotes,
about 7-8 minutes, during which every live session on this engine is cut.
The user decides the restart time; this overlay does not schedule one.

## How this gets applied -- read the gap before relying on a pipeline

There is no stage in `azure-pipelines.yml` (or anywhere else searched) that
applies a `gpu-stack/runtime-overlays/*` overlay to the live
`deepinfer-v4-1-flash` Deployment -- confirmed by grep (zero hits) and by
two independent prior ledger findings stating the same thing (one of them,
10 Nov, an operator read of the live Deployment finding no pipeline-managed
record at all: no GitOps sync annotation, only a plain
`kubectl.kubernetes.io/last-applied-configuration` and a
`kubectl restartedAt` annotation). The sibling `deepinfer-tokenizer-privacy`
overlay this file is modelled on was, on the evidence read so far, applied
the same way its own predecessor row describes as a possibility: a direct,
recorded `kubectl apply` + `kubectl rollout restart` -- a deviation from the
normal Azure Pipeline release path that AGENTS.md allows only as a bounded,
user-authorized exception (exact namespace/objects named, scope limited,
readback recorded), not as the default release mechanism. The `1315`
pipeline cannot apply this overlay today; doing so would need either a new
pipeline stage built for it, or the same kind of recorded, user-authorized
kubectl deviation the tokenizer-privacy overlay itself appears to have used.
Which of those two routes to take is the orchestrator's and the user's
decision, not this overlay's.
