# 1M context, concurrency and compaction — 23 October 2026

## Latest completed result — candidate L

**L was rejected during the 384K stage.** It passed startup capacity, four overlapping native DSH requests and the 128K workload. Each GPU then recorded **one additional allocator retry and zero OOMs**. The predefined memory gate stopped the run before the 384K answer completed. **Near-1M generation and compaction did not run.** The saved serving profile was restored and verified with actual DSH replies.

L retained the full **1,048,576-token context** and loaded a **1,064,960-slot pool**. It used static memory fraction 0.922, decode graph maximum four, eight running requests and prefill chunk/maximum 1,024/1,024. Its allocator-setting change from K was earlier native garbage collection, **0.95 → 0.92**. Startup completed in approximately 675 seconds with no unexpected restart at that gate. Earlier reclamation did not eliminate the allocation retry; this candidate was not adopted.

| L workload | Actual input / output | Native whole turn | Other timing |
|---|---|---|---|
| Four overlapping DSH conversations | 11,905 / 120 each | 3.546–3.991 seconds each | 4.092-second combined client wall |
| Completed 128K answer | 124,074 / 617 | 57.588 seconds | First text 49.223s; streaming 8.362s |
| Attempted 384K | No completed usage | Stopped by allocator gate | Near-1M/compaction not reached |

Four native turns achieved **117.30 output tokens/sec combined**, or **30.07–33.84 per conversation including whole-turn time**. Stream-window rates were 58.45–93.90 tokens/sec per conversation. The sampled GPU log observed maximum decode batch 1; native turn overlap is not proof of GPU batch four. The inherited test label says 119 tokens, while actual usage reports 120 per answer. This report uses actual usage.

For the 128K answer, whole-turn output rate was **10.71 tokens/sec**, and stream-window rate **73.79**. Short DSH replies completed within **6.352 seconds** before rejection. These are bounded samples, not sustained near-1M fairness or 100+ tokens/sec for each conversation.

The full 128K answer retained the three required facts and correctly distinguished durable files from in-memory kernel state. It also added unsupported default/approval details and an ambiguous assertion about approvals across environments. Capacity/timing and narrative source fidelity have separate outcomes. Startup additionally reported a default FP8 kernel configuration with a possible performance cost; kernel settings were unchanged in this allocator trial.

The fresh failure receipt and latest snapshot both recorded failure before the gate raised. Peak reserved memory was **91.424 GiB** per rank and peak live allocation **85.579 GiB**. An allocator retry reclaims cached allocations and attempts allocation again; it is different from a fatal OOM. The test controller cancelled and restored the profile because of the predefined zero-additional-retry policy, rather than an observed model crash. The available counters do not identify the exact allocation or memory pool that caused the retry. Installed allocator source limits garbage collection to eligible unused blocks; active allocations and retained graph pools are not automatically free memory. This does not prove 1M impossible or show which pool blocked reclamation; it means this candidate did not satisfy the strict acceptance policy.

### Post-L recovery and preservation

The restored serving profile is context **1,048,576**, static fraction **0.922**, running cap **8**, prefill **1,024 / 1,024**, shared pool **1,091,840** and decode graph maximum **8**. Actual canonical DSH returned READY in **3.333 seconds** and an exact 80-output-token reply in **1.501 seconds**, with zero retries. These are sequential recovery checks, not a new concurrent or near-1M benchmark.

Preservation checks compare original history/attachment bytes and retain newly created files. Workload/account invariants are reviewed separately. Keep organization-specific inventories private; hashes are not independent backups.

The isolated qualification store retained all 582 original files and 291 original histories, retaining 307 histories including test additions. Original profile/transport and stopped workload specifications were restored; the temporary key and owned Secret were removed with identity checks. The shared model was reloaded under controlled test authorization; human execution workspaces were not restarted by these trials.

## Earlier completed result — candidate K

Candidate **K was rejected during the 384K stage**. It passed startup capacity, four overlapping native DSH requests and the 128K workload. All four GPU ranks then recorded **one allocator retry and zero OOMs**. The strict memory gate stopped the run before 384K completed. **Near-1M generation and compaction did not run.**

The preceding candidate J reached Ready after 656 seconds but failed its minimum-pool check before workload tests began. Its exact rejected pool value was not saved and is unavailable; the numerical shortage must not be invented. Its required minimum was 1,064,960 slots.

## Actual DSH measurements from K

| Case | Input / output tokens | Native whole turn | Other measured timing |
|---|---|---|---|
| Four overlapping conversations | 11,905 / 120 each | 3.550–3.988 seconds each | 4.096-second combined client wall window |
| Completed 128K stage | 124,075 / 641 | 57.680 seconds | First text 48.915 seconds; streaming 8.703 seconds |
| Attempted 384K stage | No completed usage result | Stopped by allocator gate | No completed 384K answer |

The four conversations achieved **117.19 output tokens/sec combined**, or **30.09–33.81 per conversation including whole-turn time**. Their stream-window rates were **59.00–94.19 tokens/sec per conversation**. Four native turns overlapped; the largest observed GPU decode batch was three. These are different measurements, and none establishes 100+ tokens/sec for each conversation.

For the 128K guide, the stream-window rate was **73.65 output tokens/sec** and the whole-turn rate was **11.11**. Whole-turn time includes preparation and generation. Stream-window rate divides the reported output-token count by the recorded text-stream interval; it is an application timing estimate, not an isolated GPU decoding benchmark. The client wall window also includes polling and transport.

Short replies in the last saved progress snapshot stayed within the test bound before rejection, with a 6.351-second maximum native turn and zero retries. The incomplete larger stage does not establish responsiveness throughout a successful near-1M run. These probes used bounded total conversation context; a briefly typed question in an already long conversation may still be a large inference request.

The 128K guide was substantial, with 641 output tokens and 527 words, but did not fully meet source-fidelity review. It added an unsupported/ambiguous statement about prior notebook outputs: saved notebook cell outputs may remain even when kernel variables are lost. Some extra workspace assertions also exceeded the three supplied facts. Capacity and timing passed; perfect narrative/citation accuracy did not. The requested length was 400–500 words.

## Earlier memory finding and L hypothesis

K actually loaded a **1,048,576-token context window** and an effective **1,064,960-slot pool**, with static memory fraction 0.922, eight running requests and decode graph maximum batch four. The pool cap preserves the full window plus 16,384 shared slots; those extra slots are not an additional per-request output allowance.

The saved failure counters show a peak reserved allocation of **91.422 GiB** and peak live allocation of **85.600 GiB** per rank. An allocation retry is different from an OOM: the runtime recycled cached allocations and retried. It still failed the predefined zero-additional-retry gate. The last passing counter file was stale after the gate raised; the full failure log takes precedence over that old pass snapshot.

L later tested this hypothesis and was rejected during 384K, as detailed above. Its 128 safety and 85 harness CPU checks established preparation only.

The L harness records failing counters before raising an error and saves startup readbacks before validating them. It retained the capacity, allocator, latency and preservation gates. An explicit cap limits effective allocation to the smaller of the profiled capacity and the configured cap; it cannot force an undersized runtime to provide more memory. No freed-byte amount or speed improvement is established by prepared settings.

## Compaction and remaining acceptance

| Check | Current result | Required runtime observation |
|---|---|---|
| Substantial near-1M response | Not completed in J/K/L | Persisted answer, exact input/output usage and content review |
| Short requests during near-1M work | Not qualified by J/K/L | Native timing samples throughout successful preparation and generation |
| Automatic compaction | Not run in J/K/L | Normal threshold triggers, committed summary and reduced subsequent input |
| Stop / drain / resume | Not run in J/K/L | Active compaction stops, backend/admission work drains, then resume succeeds |
| Recall and file tools | Not run in J/K/L | Correct retained facts and a tool reads a fresh value absent from prompt/history |
| Disposable runtime replacement | Not run after compaction | Summary/history/files survive and native recall works after replacement |

The qualification profile uses a 1M window, a 0.875 pressure threshold (917,504 tokens) and 65,536-token headroom. These are configured policy values, not a completed compaction result. The eight-running-request ceiling does not demonstrate eight maximum-context conversations or two independent simultaneous 1M requests.

The prepared near-1M corpus repeats an approximately 81,036-token repository/document base 13 times, re-encoded to 989,988 raw tokens before the DSH template and explicit facts. It was not executed as a completed near-1M workload in J/K/L. It tests physical context capacity and controlled source facts, not analysis over a million unique tokens.

The private qualification route begins smaller preparation steps at 131,072 tokens; the canonical route previously switches at 524,288. Full canonical acceptance must verify that policy difference. A small recovery reply cannot establish canonical long-context or compaction parity. The private queue-full HTTP 429, cancellation/reuse and small-request bypass checks passed; they are not a second completed 1M conversation or a full 300-second wait test.

## Earlier post-K restoration and preservation

After K, the saved serving profile was restored: context **1,048,576**, static fraction **0.922**, running cap **8**, prefill **1,024 / 1,024**, pool **1,091,840** and decode graph maximum **8**. Actual canonical DSH recovery returned READY in **3.313 seconds** and an exact 80-output-token reply in **1.499 seconds**, with zero retries. These sequential checks verify recovery; they are not a new concurrent or near-1M benchmark.

For deployment qualification, retain before/after hashes of existing histories and attachments, preserve any newly created files, and verify workload identity and account/settings invariants. Use separate disposable state for restart tests. Keep organization-specific user inventories and recovery evidence in the private operational record.

The isolated qualification store retained all 550 pre-test files and all 275 original histories, growing to 291 histories from its own checks. The original profile/transport and stopped workload states were restored; the temporary key and owned Secret were removed with identity checks. Human workspaces were not restarted by these trials.

Historical measurements remain in [the earlier H report](GPU_TRIAL_STATUS_20261023.html). They belong to their dated profiles. Numeric short replies used exact-string checks; prose short probes used word-range and keyword checks. Broad analytical accuracy is a separate qualification.


## Allocator references

[PyTorch counter definitions](https://docs.pytorch.org/docs/2.14/generated/torch.cuda.memory.memory_stats.html) distinguish allocation retries from thrown OOM errors. [Allocator source pinned to the installed Torch revision](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/c10/cuda/CUDACachingAllocator.cpp) explains reclaimable blocks and graph-private allocation lifetimes. The documentation describes the counters; the pinned source supplies version-specific mechanism details. Neither identifies the exact allocation behind this trial’s retry.
