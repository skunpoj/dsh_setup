# DeepEP trial overlay (INACTIVE, replicas 0)
Separate Deployment `llm/deepinfer-v4-1-flash-deepep`, derived from live generation 32. Only delta: `DEEPINFER_EP_COMM_BACKEND` nccl -> deepep (see DIFF_vs_live_gen32.txt).
Not applied by any pipeline stage. Applied once on the iommu=pt window by `swap_to_deepep.sh` (scale swap; live Deployment never patched). Rollback: `rollback_to_nccl.sh`.
Never run both engines together (shared GPUs, RWO volume). Status: PROPOSED-NOT-EXECUTED until Gate A and correctness receipts pass.

Public mirror note: the internal node hostname is replaced by `<GPU_NODE_HOSTNAME>` and the annotation key domain by `dsh.example/`. The authoritative, byte-exact manifest lives in the project's Azure DevOps GPU_server repository (commit 4e98e04). Set the real hostname before use.
