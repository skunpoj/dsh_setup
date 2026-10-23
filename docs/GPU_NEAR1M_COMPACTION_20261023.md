# 1M context, concurrency and compaction — 23 October 2026

## Latest completed result

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

## Memory finding and prepared successor

K actually loaded a **1,048,576-token context window** and an effective **1,064,960-slot pool**, with static memory fraction 0.922, eight running requests and decode graph maximum batch four. The pool cap preserves the full window plus 16,384 shared slots; those extra slots are not an additional per-request output allowance.

The saved failure counters show a peak reserved allocation of **91.422 GiB** and peak live allocation of **85.600 GiB** per rank. An allocation retry is different from an OOM: the runtime recycled cached allocations and retried. It still failed the predefined zero-additional-retry gate. The last passing counter file was stale after the gate raised; the full failure log takes precedence over that old pass snapshot.

Successor **L is prepared**, with the same context, 1,064,960-slot cap, static fraction 0.922, graph maximum four and concurrency cap eight. Its proposed change is earlier native allocator garbage collection, **0.95 → 0.92**. Preparation passed 128 safety CPU checks and 85 harness CPU checks. **There is no accepted L runtime result in this snapshot.** CPU checks do not establish GPU stability or throughput.

The successor records failing counters before raising an error and saves startup readbacks before validating them. It must retain the capacity, allocator, latency and preservation gates. An explicit cap limits effective allocation to the smaller of the profiled capacity and the configured cap; it cannot force an undersized runtime to provide more memory. No freed-byte amount or speed improvement is established by prepared settings.

## Compaction and remaining acceptance

| Check | Current result | Required runtime observation |
|---|---|---|
| Substantial near-1M response | Not completed in J/K | Persisted answer, exact input/output usage and content review |
| Short requests during near-1M work | Not qualified by J/K | Native timing samples throughout successful preparation and generation |
| Automatic compaction | Not run in J/K | Normal threshold triggers, committed summary and reduced subsequent input |
| Stop / drain / resume | Not run in J/K | Active compaction stops, backend/admission work drains, then resume succeeds |
| Recall and file tools | Not run in J/K | Correct retained facts and a tool reads a fresh value absent from prompt/history |
| Disposable runtime replacement | Not run after compaction | Summary/history/files survive and native recall works after replacement |

The qualification profile uses a 1M window, a 0.875 pressure threshold (917,504 tokens) and 65,536-token headroom. These are configured policy values, not a completed compaction result. The eight-running-request ceiling does not demonstrate eight maximum-context conversations or two independent simultaneous 1M requests.

The prepared near-1M corpus repeats an approximately 81,036-token repository/document base 13 times, re-encoded to 989,988 raw tokens before the DSH template and explicit facts. It was not executed as a completed near-1M workload in J/K. It tests physical context capacity and controlled source facts, not analysis over a million unique tokens.

The private qualification route begins smaller preparation steps at 131,072 tokens; the canonical route previously switches at 524,288. Full canonical acceptance must verify that policy difference. A small recovery reply cannot establish canonical long-context or compaction parity. The private queue-full HTTP 429, cancellation/reuse and small-request bypass checks passed; they are not a second completed 1M conversation or a full 300-second wait test.

## Verified restoration and preservation

After K, the saved serving profile was restored: context **1,048,576**, static fraction **0.922**, running cap **8**, prefill **1,024 / 1,024**, pool **1,091,840** and decode graph maximum **8**. Actual canonical DSH recovery returned READY in **3.313 seconds** and an exact 80-output-token reply in **1.499 seconds**, with zero retries. These sequential checks verify recovery; they are not a new concurrent or near-1M benchmark.

For deployment qualification, retain before/after hashes of existing histories and attachments, preserve any newly created files, and verify workload identity and account/settings invariants. Use separate disposable state for restart tests. Keep organization-specific user inventories and recovery evidence in the private operational record.

The isolated qualification store retained all 550 pre-test files and all 275 original histories, growing to 291 histories from its own checks. The original profile/transport and stopped workload states were restored; the temporary key and owned Secret were removed with identity checks. Human workspaces were not restarted by these trials.

Historical measurements remain in [the earlier H report](GPU_TRIAL_STATUS_20261023.html). They belong to their dated profiles. Numeric short replies used exact-string checks; prose short probes used word-range and keyword checks. Broad analytical accuracy is a separate qualification.
