# Runbook: 200+ tok/s and DeepInfer on 4× H100 NVL

> **Outdated (30 Oct 2026, UTC): kept for history.** DeepInfer + DSpark has served production on this node since 29 Oct over the NCCL expert-exchange fallback. Current configuration and measured numbers: [Current production](README.md#current-production-30-oct-2026-utc) and [DeepInfer#221](https://github.com/deepseek-ai/DeepInfer/discussions/221#discussioncomment-19270514).

Companion to [README.md](README.md). Steps run in the order given. Every step names its owner role, whether it needs a GPU window, its commands, and the condition that ends it.

## 0. Roles, rules and variables

| Role | Does |
| --- | --- |
| **Runtime executor** (exactly one agent) | Everything that reads or changes the running engine, every GPU window, switch and restore |
| **Backend agent** | Code, builds, CPU tests, kernel ports, memory admission |
| **Recovery agent** | Snapshot and restore scripts, rehearsal of the restore path |
| **Reviewers** (two, independent) | Review every change before a window and every result before it is published |
| **Owner** | Approves each window and each publication |

Rules:

1. One change per window. Measure before and after with the same matrix. Keep or roll back; write down which.
2. A window starts with a snapshot of the live deployment and ends with the service restored and probes passing.
3. Never print or commit tokens, keys, kubeconfigs, internal hostnames, addresses or user data. Label every number measured or projected.
4. Stop and write a question when a value is missing. Do not guess.

Variables used below (set them in your shell; none are committed):

```bash
export BASE_URL=http://127.0.0.1:30000/v1         # engine endpoint, e.g. through kubectl port-forward
export METRICS_URL=http://127.0.0.1:30000/metrics # SGLang Prometheus metrics (start with --enable-metrics)
export MODEL=deepseek-ai/DeepSeek-V4.1-Flash      # served model name
export MODEL_DIR=/path/to/snapshots/1bae0e1088993b9b82de08f59de5be5a34e42170
export R=$PWD/results                             # results folder
# Only if the engine runs in Kubernetes:
export NS=<namespace> POD=<engine pod> CONTAINER=<engine container>
export ENGINE_LOG_CMD='kubectl logs -n "$NS" "$POD" -c "$CONTAINER" --since-time=$T0'
```

## Path A: 200+ aggregate on SGLang (highest chance for aggregate; scheduled into path C's SGLang restarts)

### A1. Per-workload matrix, natural stopping (runtime executor, no window, about 1 hour)

```bash
OUT_DIR=$R/a1 LABEL=sglang_dspark CONCURRENCY="1 4 8" \
  WORKLOADS="code json maths chat_en chat_th" scripts/v41_h100/run_matrix.sh | tee $R/a1/A1_table.md
```

The table prints per-user p50/p10, aggregate, TTFT and the queue state before each run. If `num_running_reqs` was above 0 before a run, someone else was using the service: re-run that row.

`engine_summary.txt` gives accept length and step time per batch size (`est_step_ms = batch × accept_len / gen_throughput`). If the parser finds nothing, it prints one raw `Decode batch` line; adjust the three regexes at the top of `parse_decode_log.py`.

**Done when:** `A1_table.md` and `engine_summary.txt` exist with every row measured on an idle server.

### A2. Memory plan for higher caps (backend agent, no window, 1–2 days)

`--max-running-requests` does not grow the KV pool; it lets more requests share it. What does cost memory is CUDA-graph capture for larger decode batches and the per-request buffers. On a long-context profile with little free GPU memory, measure the margin first.

```bash
# Current pool size, graph capture and free memory, from the startup log and live GPUs
kubectl logs -n "$NS" "$POD" -c "$CONTAINER" | grep -iE 'max_total_num_tokens|KV cache|capture|cuda graph|avail mem' | tail -30 > $R/a2/startup.txt
kubectl exec -n "$NS" "$POD" -c "$CONTAINER" -- nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader > $R/a2/gpu_mem.txt
# Which knobs this build has
kubectl exec -n "$NS" "$POD" -c "$CONTAINER" -- python3 -m sglang.launch_server --help > $R/a2/help.txt
grep -nE 'max-running-requests|cuda-graph-(max-bs|bs)|mem-fraction|speculative|max-total-tokens|context-length' $R/a2/help.txt
```

Write `$R/a2/MEMORY_PLAN.md` with:

1. Free memory per GPU now, at the qualified long-context profile.
2. Expected extra memory for graphs at batch 16 and 32. Measure it: the startup log reports memory before and after capture.
3. What gives way if it does not fit, in this order: capture graphs only up to 16 (`--cuda-graph-bs 1 2 4 8 12 16`, if the build has it); lower `--mem-fraction-static` by 0.005 steps; a separate shorter-context profile for high concurrency.
4. Rollback: the snapshot from step A3.

**Done when:** reviewers sign the plan.

### A3. Raise the caps (runtime executor, window, about 45 minutes each)

| Step | `--max-running-requests` | `--cuda-graph-max-bs-decode` | Measure |
| --- | --- | --- | --- |
| A3.a | 16 | 16 | concurrency 8, 16 |
| A3.b | 32 | 32 | concurrency 16, 32 |

```bash
# Snapshot, then change exactly the two values (Kubernetes example)
TS=$(date -u +%Y%m%dT%H%M%SZ); mkdir -p $R/a3
kubectl get deploy -n "$NS" <engine-deployment> -o yaml > $R/a3/before-$TS.yaml
cp $R/a3/before-$TS.yaml $R/a3/a3a.yaml
sed -i -E 's/(--max-running-requests[" ,=]+)8\b/\116/; s/(--cuda-graph-max-bs-decode[" ,=]+)8\b/\116/' $R/a3/a3a.yaml
kubectl diff -f $R/a3/a3a.yaml                   # must show exactly these two changes
kubectl apply --dry-run=server -f $R/a3/a3a.yaml
kubectl apply -f $R/a3/a3a.yaml && kubectl rollout status -n "$NS" deploy/<engine-deployment> --timeout=30m
# Measure
OUT_DIR=$R/a3/a CONCURRENCY="8 16" WORKLOADS="code chat_en" LABEL=caps16_dspark scripts/v41_h100/run_matrix.sh
# Roll back if worse, OOM or TTFT p95 > 5 s:
kubectl apply -f $R/a3/before-$TS.yaml
```

Projected (not measured): with speculation on, each verify step processes batch × 5 draft tokens, so aggregate may grow only modestly with caps alone. That is why A4 exists.

### A4. Speculation on vs off at high concurrency (runtime executor, window)

At the best cap from A3, remove only `--speculative-algorithm DSPARK --speculative-dspark-block-size 5`:

```bash
OUT_DIR=$R/a4/off CONCURRENCY="1 16 32" WORKLOADS="code chat_en" LABEL=caps_nospec scripts/v41_h100/run_matrix.sh
```

Before choosing, check whether this SGLang build can turn speculation off above a batch size (`grep -n speculative $R/a2/help.txt`). If it can, one profile serves both: fast single users and high capacity. If it cannot, the owner chooses between speculation on (68 tok/s single user, lower capacity) and off (higher capacity, slower single user).

**T1 passes when** aggregate ≥ 200 tok/s with TTFT p95 ≤ 5 s on both workloads, natural stopping, idle server before the run.

## Path B: profile, then port one SM90 kernel from DeepInfer (E8)

### B1. One-step profile (runtime executor, in the same restart as A3)

Start the engine with `SGLANG_TORCH_PROFILER_DIR=<dir>` added, then:

```bash
curl -s -X POST ${BASE_URL%/v1}/start_profile
python3 scripts/v41_h100/stream_bench.py --prompts scripts/v41_h100/workloads/code.jsonl -c 1 -n 2 --max-tokens 256 --tag b1_prof --out-dir $R/b1
curl -s -X POST ${BASE_URL%/v1}/stop_profile
# copy the trace out, then (steps = emitted tokens / accept_len from engine_summary.txt)
python3 scripts/v41_h100/bucket_trace.py <rank0 trace .json.gz> --steps <N> | tee $R/b1/buckets.txt
```

All-reduce floor, only when all GPUs are free (end of a window):

```bash
torchrun --nproc_per_node=4 scripts/v41_h100/allreduce_lat.py | tee $R/b1/allreduce.txt
```

How to read `buckets.txt`:

| Largest share | Next step |
| --- | --- |
| `indexer` | B2: port the SM90 indexer from DeepInfer #92/#148 |
| `allreduce/comm` | Try NCCL small-message settings (`NCCL_PROTO=LL`/`LL128`), check whether custom all-reduce is disabled because not all GPUs share NVLink |
| `engram/host copy` | Compare Engram host-table layouts `shared` and `per_rank`; huge pages |
| GPU idle above about 40% | CUDA-graph coverage of draft and verify, `--prefill-decode-interval`, overlap scheduling |
| `moe` | Weight-read bound; MoE kernel work comes last |

### B2. Port the dominant operation (backend agent, no window, 1–2 weeks)

For the indexer:

```bash
git clone https://github.com/deepseek-ai/DeepInfer.git && cd DeepInfer
git fetch origin pull/92/head:pr92 pull/148/head:pr148
git grep -nE 'def .*(index|mqa_logits|topk)' pr92 -- 'deepinfer/**/*.py' | head -40
# In the SGLang tree: find where SM90 falls back to the torch indexer
grep -rn "_is_sm100_or_newer" $(python3 -c "import sglang,os;print(os.path.dirname(sglang.__file__))") | head
```

1. Copy the Triton indexer kernels from #92 into an SGLang patch, keeping the licence headers and a credit line to the PR.
2. Gate them behind an environment flag, off by default (for example `SGLANG_DSV41_SM90_PORTED_INDEXER=1`), at the `_is_sm100_or_newer()` fallback sites.
3. Parity test: random inputs at decode and prefill shapes, ported kernel vs the torch fallback, max abs error and top-k index agreement 100%.
4. Greedy output compare on 20 prompts: identical tokens, or a documented, explained difference.

### B3. A/B in a window (runtime executor)

Same deployment and flags, only the flag toggled. Run A1's matrix (code, chat_en; concurrency 1 and 4) both ways plus a B1 profile. Report: indexer ms per step before → after, per-user tok/s before → after, with commit hashes.

## Path C: DeepInfer on 4× H100 NVL (E6) — chosen primary path

Why each setting is needed, the decision tree and the estimated chances are in [PATH_C.md](PATH_C.md). Summary: #92 (Hopper port) merged with #200 (UVA host Engram fetch); `DEEPINFER_ENGRAM_UVA_FETCH=1` because the container has no RDMA NIC; `EP_DISABLE_GIN=1` so DeepEP uses only load/store (NVLink or PCIe P2P) paths; all four GPUs must be peer-accessible.

### C0. Fail-fast: CUDA P2P across the two pairs (runtime executor, no window, minutes)

Read-only; safe while SGLang runs.

```bash
nvidia-smi topo -m        # NV12 inside each pair, SYS between pairs is expected
nvidia-smi topo -p2p r    # peer-to-peer read support for every GPU pair
nvidia-smi topo -p2p w    # peer-to-peer write support
```

- **All pairs OK:** route C-direct; continue with C1.
- **GPU0/1 ↔ GPU2/3 not OK** (for example `NS`): DeepEP cannot form one load/store domain and has no NIC to bridge the pairs. Choose route C-NCCL (PATH_C.md section 3) or stop. Post the result to #221 either way.

### C1. Fetch, build, collect: G1 (backend agent, no window, 2–4 days)

```bash
scripts/v41_h100/deepinfer_sm90.sh facts      # driver, topology, P2P matrix, RDMA devices, huge pages, host memory
scripts/v41_h100/deepinfer_sm90.sh fetch      # branch h100 = #92 + #200 (merges cleanly); #147, #148 fetched too
scripts/v41_h100/deepinfer_sm90.sh build      # CUDA 13.0-13.2, Python 3.12, torch 2.13, sm90, humming-kernels 0.1.13
scripts/v41_h100/deepinfer_sm90.sh collect    # #92 collects 179 tests
```

**G1 passes when** the build imports, collection has no errors, and the driver is R590, or R570 with the CUDA 13 forward-compat `libcuda` first on `LD_LIBRARY_PATH`.

### C2. Memory admission and the trial pod (backend agent; reviewers; no window, 3–5 days)

```bash
cd deepinfer-sm90
git grep -nE 'redundant|ep_size|expert.*shard|replicat|attn_dp' h100 -- deepinfer/model_executor | head -40 > $R/e6/placement_rules.txt
git grep -nE 'mtp|nextn|dspark' h100 -- deepinfer/model_executor/models | head -40 >> $R/e6/placement_rules.txt
git grep -nE 'get_buffer_size_hint|num_max_tokens_per_rank|EPBuffer\(' h100 -- deepinfer | head -20 > $R/e6/deepep_buffers.txt
git grep -nE 'gpu_memory_utilization|kv.*(fraction|budget|blocks)|max_num_seqs|MAX_NUM' h100 -- deepinfer | head -30 > $R/e6/kv_config.txt
cd ..
python3 scripts/v41_h100/ckpt_admission.py "$MODEL_DIR" --gpus 4 | tee $R/e6/admission.txt   # headers only
```

Write `$R/e6/G2.md`: per GPU, routed experts (about 69 GiB at EP4) + replicated weights (about 10 GiB) + drafter + `EPBuffer` size + KV + CUDA context + load-time repack peak, against 93.6 GiB. **G2 passes on paper when** steady state and load peak each leave ≥ 3 GiB per GPU; shrink the KV budget and maximum tokens first if not.

Trial pod spec (reviewed before the first window), in addition to the SGLang pod's security context:

- all four GPUs, the model volume read-only;
- `/dev/shm` as a memory-backed volume of at least 200 GiB (#200 writes the full Engram tables there);
- host memory limit of at least about 450 GiB (#200 peaks at about 380 GB during load);
- environment: `DEEPINFER_ENGRAM_UVA_FETCH=1`, `EP_DISABLE_GIN=1`, `NCCL_NVLS_ENABLE=0`, `DEEPINFER_CP_COMM_BACKEND=nccl`, `DEEPINFER_SM90_MOE_BACKEND=humming`.

### C3. Window 1 (about 60 minutes): probes and kernel tests, no model load

```bash
scripts/v41_h100/deepinfer_sm90.sh probes     # p2p matrix + copy GB/s; NCCL LSA size (expect nvl_ranks=4); pin 8 GiB
PIN_GIB=200 python3 scripts/v41_h100/sm90_probes.py pin --gib 200   # the full Engram size, if 8 GiB passed
scripts/v41_h100/deepinfer_sm90.sh gpu-tests  # #92 SM90 suite; DeepEP tests/ep/test_ep.py on 4 GPUs without GIN; #200 UVA test
```

**Pass:** `nvl_ranks=4`; both pin probes return status 0; DeepEP EP4 test passes; #92's suite matches H20-3e test by test (162 passed / 1 skipped there); #200's UVA test passes. Publishable whatever the outcome. Then restore SGLang and use the restart for one path-A change (PATH_C.md section 6).

### C4. Window 2 (about 90 minutes): first load and offline generation

```bash
scripts/v41_h100/deepinfer_sm90.sh offline    # DSpark off (NEXTN=0), then on (NEXTN=5); GPU and host memory timelines
```

Record: whether loading finishes; peak and steady GPU memory per GPU (`mem_timeline.csv`); host memory (`host_mem_timeline.txt`); whether output is coherent; DSpark acceptance; every kernel error, verbatim. An out-of-memory error at load is a G2 result: record the peak and retry once with a smaller KV budget.

### C5. Window 3 (90–120 minutes): correctness and matched benchmark

1. GSM8K, 200 questions, greedy, on DeepInfer and on SGLang: scores within about ±2 points.
2. Merge #147 (`git merge --no-ff pr147`), start its OpenAI-compatible server, then run the identical matrix against three backends: SGLang speculation off, SGLang DSpark on, DeepInfer DSpark on.

```bash
for L in sglang_nospec sglang_dspark deepinfer_dspark; do
  # point BASE_URL at the backend under test before each run
  OUT_DIR=$R/c5/$L LABEL=$L CONCURRENCY="1 2 4 8 16" WORKLOADS="code json chat_en" scripts/v41_h100/run_matrix.sh
done
```

Publish the table with every commit hash, including the rows where DeepInfer loses.

### C-NCCL. Only if C0 or C3 shows the pairs cannot share one load/store domain (backend agent, 2–4 weeks)

Write an `EPBuffer`-compatible dispatch/combine on `torch.distributed.all_to_all_single` over NCCL (NCCL bridges the pairs over PCIe or host memory), selected by an environment flag at the two call sites in `deepinfer/model_executor/models/v4_modules/mlp.py`. Parity test it against DeepEP on one NVLink pair (EP2, synthetic experts) before any model load, then repeat C3 and C4. Offer it upstream with the measurements.

## Publishing a result

```bash
python3 scripts/scan_public.py .
python3 scripts/check_public_release.py . --private-terms /path/outside/repo/private_terms.txt
```

Then post to [#221](https://github.com/deepseek-ai/DeepInfer/discussions/221): what changed, the measured table, method, commits, and what did not work.
