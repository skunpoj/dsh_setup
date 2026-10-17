# Long-request admission and short-request responsiveness

## Why the previous run retried

The earlier near-million-token run completed correctly but encountered two busy responses. The gateway admitted only one long request and stopped waiting after 300 seconds; DSH then retried. Its final successful attempt still spent another 243.67 seconds waiting for admission. Those are queue waits, separate from the 1,227.76 seconds spent preparing context. The competing request's historical ownership was not conclusively established. A correct final answer did not satisfy the zero-retry acceptance criterion.

## What changed

The final forwarding boundary retains one active long request, adds one bounded FIFO waiting position, and allows that waiter up to 1,500 seconds to acquire the slot. Additional long requests receive an immediate capacity error rather than accumulating an unbounded backlog. The legacy callback's default five-minute policy is unchanged; the explicit longer budget applies to the final-wire DSH route. This is a single-replica, single-forwarder-process design, not a distributed queue.

Ordinary requests bypass the long admission lock. Tokenization and short streams retain their foreground lane, while long preparation continues in bounded prefix steps. The model's 1,048,576-token ceiling, 8,192-token output ceiling, 256-token reserve, GPU allocation, scheduler and running-request limit are unchanged. Waiting uses no additional model copy or GPU allocation. A bounded queue cannot remove the compute time of a cold million-token prompt or promise zero waiting during overload.

For streaming clients, HTTP streaming now begins before admission and context preparation. Content-free SSE comments keep the response open while no model output is available. This lets cancellation propagate through the proxy while preparation is running. These comments are not model tokens, generated answers or time-to-first-text measurements. Cancellation closes the preparation task and releases only that request's lease; a bounded in-flight warm step may finish separately. Nonstreaming callers retain a normal JSON response or HTTP error.

Admission start events now include the server-generated request ID and numeric token count. Completed timing records distinguish admission, preparation and answer streaming. They contain no prompt text, passwords or API keys. Once streaming headers have been sent, admission failures are returned as SSE errors; callers must inspect the stream rather than treat HTTP 200 alone as success.

## Verification

The controlled occupied-slot retest passed: **1,007,704 input tokens**, **119 output tokens**, the full correct 1–40 answer and persisted prompt, with **0 retries**. Total DSH time was **1551.75 seconds**, including **315.74 seconds waiting for admission** and **1226.79 seconds preparing context**. The answer streamed in **3.53 seconds**, approximately **33.42 output tokens/second**. This rate excludes queueing and preparation.

**46/46 overlapping ordinary DSH replies** were exact with zero retries, taking **4.05–9.12 seconds** (median 5.59). A third long nonstreaming request to the loopback final-wire guard received HTTP 429 in **0.34 seconds** while the active and waiting positions were occupied. Of these, 38 probes started after the hold released, during the real long-request work; that subset took 5.07–9.12 seconds. The intentional 320-second hold is test overhead, not a GPU throughput measurement.

Actual DSH cancellation of a 147,674-token active request freed admission in **1.48 seconds after cancellation**. A separate 147,673-token waiting request was cancelled and cleaned up while the main near1M request retained its own lease. The GPU pod identity/image stayed unchanged with **zero restarts**. CUDA allocator memory-mapping OOM warnings were observed near the final prefix steps, but the request completed and ordinary replies continued. This verifies the recorded admission/cancellation case, not additional GPU memory headroom or two full-1M requests. Mounted middleware bytes match the tested source. All **68 targeted Linux tests** and **42 portable-bundle tests** passed without skips.

[Sanitized measurement record](context-evidence/admission-responsiveness-20261017.json). Earlier retry-bearing and invalid-fixture records remain preserved; this result does not retroactively make them passes.

## Safe rollout and lessons

The gateway changes use immutable configuration snapshots with the previous deployment retained for rollback. Main and legacy DSH agent turns were checked for idleness before replacement. The GPU process and user storage are preserved. A free long-request lock alone is insufficient evidence that every agent turn has finished: tool continuations also matter.

The first hold-fixture attempt was invalid. A readiness substring check matched the marker inside an error traceback and started two synthetic turns without the intended held lease. Both were identified and cancelled; their records are retained and are not acceptance evidence. The fixture now requires an exact standalone readiness line. Accepted DSH cancellation initially left pre-header preparation active; the early streaming change was tested against actual DSH cancellation before repeating the capacity test. Only the identified disposable tests were cleared during that controlled gateway handover.

The controlled occupied-slot test is a queue fixture, not two simultaneous million-token GPU workloads. Its real near-million-token continuation and overlapping short requests provide separate inference evidence. Neither these samples nor the running-request cap establish a latency SLA, sixteen maximum-length requests, two simultaneous full-million contexts or every analytical task's correctness. Owner passwords, user histories, network policy and accepted remote-execution scope are unchanged.
