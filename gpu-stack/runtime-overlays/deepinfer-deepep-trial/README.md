# DeepEP trial overlay (INACTIVE, replicas 0)
Separate Deployment `llm/deepinfer-v4-1-flash-deepep`, derived from live generation 32. Only delta: `DEEPINFER_EP_COMM_BACKEND` nccl -> deepep (see DIFF_vs_live_gen32.txt).
Not applied by any pipeline stage. Applied on the iommu=pt window in three ordered steps (live Deployment never patched): `apply_overlay.sh` (create at replicas 0) -> `run_p3_check.sh` (one-off 4-GPU DeepEP dispatch/combine check Job while both engines are at 0) -> `scale_up_deepep.sh`. `swap_to_deepep.sh` is superseded. Rollback: `rollback_to_nccl.sh`.
Never run both engines together (shared GPUs, RWO volume). Status: PROPOSED-NOT-EXECUTED until Gate A and correctness receipts pass.
