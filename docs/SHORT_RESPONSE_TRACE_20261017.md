# Short-response tracing and scheduling lessons

The historical 38-second DSH answer has application timings but no retained matching server trace. Its exact cause is not retroactively proven. A subsequent controlled experiment reproduced an upstream generation delay during shared long-prefill work and introduced request-ID correlation for future investigations.

## Separate the paths before changing settings

The same synthetic 8,867-token input and exact 80-token output were sent twice through each path in serial order. These are observations under a changing shared load and cache; they are not a randomized benchmark.

| Path | Full elapsed seconds | First-to-last text seconds | Largest observed stream gap |
|---|---:|---:|---:|
| Direct backend, bypassing foreground coordination | 17.71–23.27 | 17.55–18.70 | 1,779–1,793 ms |
| Foreground-coordinated forwarder | 3.05–4.43 | 2.34–2.35 | About 31 ms |
| Authenticated model gateway | 5.55–6.14 | 3.13–5.91 | 754–1,786 ms |

Timestamp-matched backend logs showed five or six long-prefill batches during each direct-backend reply, zero during the two coordinated-forwarder replies and one during each authenticated-gateway reply. This establishes interference in those reproduced samples, without identifying every contributor to the old user's turn or proving that every gateway pause is queueing.

## Scheduling correction

An idle event is only a wake-up notification. A new foreground request can enter before a waiting long preparation resumes. The previous single wait could therefore proceed while foreground work was active. The corrected wait checks active work again, using the original bounded eight-second deadline. The regression reproduction changes from “background passed while foreground active” to “background did not pass.”

Exact tokenization also holds a temporary foreground lease. Ownership is released on success or failure, and the ordinary response holds its lease through stream cleanup. Long work releases the provisional lease before waiting for admission. These changes preserve the 1M budget and ordinary parallelism; they do not preempt an already-running GPU kernel or establish a response SLA.

## What timing records establish

The forwarder emits a content-free `dsh_request_timing` record for requests reaching its cleanup block. It includes a generated request ID; exact input count and output budget; tokenization, admitted wait and preparation durations when completed; upstream-header/first-byte/first-delta arrival; byte/chunk/gap counts; available output usage and total elapsed time. The response ID is retained in DSH's finish metadata so the operator can match the application events to that record.

No prompt, answer, tool arguments, API key, Kerberos ticket or human identity is added to these timing records. Malformed or oversized diagnostic SSE fragments do not alter forwarded bytes. A logging failure cannot prevent lease cleanup. Early validation/tokenizer refusals are not all represented by this record; it is not a complete security audit.

These clocks distinguish arrival at the forwarder from DSH event delivery. They do not measure GPU kernel time or browser paint. A post-handover sample took 10.63 seconds, including about 6.85 seconds until upstream headers; another sample retained a roughly 935 ms upstream gap. Those slower observations remain recorded instead of being removed from the results.

## Acceptance and remaining interpretation limits

The [deployment review](DEPLOYMENT_AND_FUNCTION_REVIEW_20261017.html) records the later complete CPU rollout and fresh 263K/paired/eight-way/sixteen-way actual DSH results. The [LLM guide](LLM_SETUP_AND_TEST_RESULTS.html) retains the historical cold/cached and near-1M tests. One long request is admitted at a time; other long requests can wait and receive the existing busy response. An earlier DSH client retried that response once: a correct eventual answer is not a retry-free admission test.

Use whole-agent activity, not merely a free HTTP lease, to choose maintenance boundaries. Preserve failed records, source epochs and individual retry counts. Dashboard integration of the new timing metadata remains separate from its deployed collection in container logs.
