# DSH GPU candidate M: qualification not accepted

Review edition only. Historical K/L evidence and accepted live documentation remain preserved. No live publication is implied.

## Evidence and limits

M was rejected during near-1M preparation: each GPU added one allocation retry. The scoped 128K/384K GPU gates passed, but near-1M and compaction did not complete. The original serving specification, source and image were restored and actual native replies verified. This is a rejected candidate with verified recovery, not a completed allocator fix.

## Actual gate outcomes

- **startup — passed**: Candidate startup captured; subsequent qualification failed. Startup is not full acceptance.
- **allocator — failed**: During near-1M preparation each of all four GPU ranks added one allocation retry; terminal num_ooms remained zero.
- **near1m — failed**: Near-1M gate rejected by allocator retries; latest prepared prefix reported by operator was 819,200 tokens. This is not a completed near-1M turn.
- **content — failed**: 128K/384K core-fact checks passed their scoped gates. Strict three-fact-only/source adherence did not pass; the 384K addendum identifies an unsupported shared-base-environment statement.
- **compaction — not-tested**: Not reached after near-1M allocator rejection
- **stopDrainResume — not-tested**: Not reached after near-1M allocator rejection
- **recallAndTool — not-tested**: Not reached after near-1M allocator rejection
- **persistence — not-tested**: Not reached after near-1M allocator rejection
- **canonicalPolicyParity — not-tested**: Canonical long-context policy parity was not run; private fixture threshold differs from canonical proxy.
- **baselineRecovery — passed**: Exact original specification, application source and image restored; actual READY in 3.6815 seconds and exact 1–40 output in 1.4913 seconds, zero retries. Human workspaces and original files preserved; the kernel probe is limited and is not proof about every process.
- **cleanup — passed**: Original fixture files exact; added histories retained. Owned alias revoked and Secret absent; stopped original workload specifications read back. Reservation released; holder exited with a zombie awaiting reap, not claimed PID absent. Initial cleanup missing-prerequisite attention retained; reconciliation resumed recovery without M source changes.

## Latest M allocation failure

M requested 1,748 MiB with 1,683.75 MiB free: a 64.25 MiB immediate shortfall on every GPU. About 0.55 seconds earlier, the guard reclaimed 2,891,972,608 bytes (2.693 GiB) while active allocated bytes stayed unchanged. These aggregate observations do not identify the tensor/callsite or prove both records belong to the same forward. The guard ran but was insufficient for the observed later peak.

## Historical allocation finding

L recorded four failed native CUDA allocations requesting 169,869,312 bytes (162 MiB), with 142,344,192 bytes (135.75 MiB) free. Each GPU added one allocator retry; num_ooms remained zero. Zero terminal OOM counters do not imply no failed allocations. The precise tensor/pool origin remains unestablished.

## Candidate mechanism and limits

The opt-in pressure guard runs only on pinned EXTEND, MIXED and SPLIT_PREFILL modes. Its 2,048 MiB free-memory floor is a bounded heuristic, not an established optimum. Unused-cache reclamation does not delete active model/KV tensors. Actual pressure events, allocator deltas and latency gates must be read together.

## Canonical policy parity

The private M fixture warms a 2,048-token tail after 131,072 tokens; the canonical proxy uses the same algorithm after 524,288 tokens. Private-fixture success does not establish canonical long-context service parity. This is an explicit independent acceptance gate.

## Runtime and allocator source

Actual runtime: PyTorch 2.13.0+cu130, git cf30153c4c131c8164ee7798e5022d810682e2cb (operator-verified). Official pinned source explains code semantics: https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/c10/cuda/CUDACachingAllocator.cpp . The L allocation sizes/free memory are separately measured saved-log evidence, not values derived from this source.

## Qualification scope and timing limits

A full 1M-input capacity/functional test is not a general long-context retrieval-accuracy benchmark. Requested A/B/C facts overlap the platform system context. Actual cached-preparation and warmed-token evidence plus final usage establish capacity; compaction reference/recall is a separate gate. Core-fact checks do not establish flawless answer accuracy or strict source adherence.

Whole-turn elapsed time includes progressive cache warming and foreground-fairness yields. Text-generation stream rate is calculated separately. Neither should be represented as model decode throughput without those limits.

A default FP8 kernel-configuration fallback was observed at startup. It was unchanged and untuned in this candidate.

The 384K append-only content addendum flags an unsupported claim about a shared base environment; strict source adherence must not be labelled passed from the core-fact checks alone. The final operator disposition and bound addendum evidence remain authoritative.

## Timing derivations

- 128K: 603 output tokens / 58.225648 whole-turn seconds = 10.3563 tokens/sec. Separately, 603 / 8.145000 text-stream seconds = 74.0331 tokens/sec.
- 384K: 583 output tokens / 313.833243 whole-turn seconds = 1.8577 tokens/sec. Separately, 583 / 7.686000 text-stream seconds = 75.8522 tokens/sec.

## Append-only context clarifications

- The prior blanket claim that L invented the No Internet default was too broad: captured system context explicitly supplied it. Strict three-fact adherence and ambiguous approval/recovery wording remain separate caveats.
- M saved-log diagnosis: four native allocation failures requested 1,832,910,848 bytes (1,748 MiB), with 1,765,539,840 bytes (1,683.75 MiB) free, a 64.25 MiB shortfall. A successful guard reclaim about 0.55 seconds earlier does not prove the exact intervening tensor/callsite. Prepared bounded diagnostic helper passed 19 CPU tests only and was not activated; it is not an actual GPU fix.


## Evidence provenance

Private saved receipts remain with the operator. This portable summary omits infrastructure IDs and local paths.
