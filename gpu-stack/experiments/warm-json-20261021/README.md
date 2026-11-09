# Warm-request JSON experiment

This candidate was rejected for numeric short-request latency regression (median +13.07%, p95 +20.55%); it is not applied by the installer or deployed in Production. It changes only encoding of integer-token warm preparation bodies. Final chat conditioning, exact counting, 1M total budget, admission and foreground yielding stay unchanged.

`candidate.patch` preserves the reviewed portable runtime and regression-test differences. The portable tokenizer URL remains an explicitly required operator value; there is no internal endpoint default. The standard encoder remains the default. Explicit `DSH_WARM_JSON_ENCODER=orjson` requires the installed dependency and fails closed if unavailable or misspelled. The pinned qualification image contained orjson 3.11.6; no Internet installation occurred at startup.

The three added tests cover exact legacy bytes, decoded compact-body equivalence, and invalid/missing encoder refusal. The candidate portable Linux suite passed 78 tests with no skips, including the existing guard and deployment checks. These are overlapping tests, not 78 separate performance runs. The actual installed encoder also round-tripped representative integer payloads exactly.

The native DSH comparison used the same retained-history fork and two continuing ordinary conversations. A fixed fresh prefix per arm prevented cross-arm warm-cache credit without modifying the source history. Stop/drain, native results, full-window GPU diagnostics and restart persistence were checked. See [matched results](../../../docs/LLM_SETUP_AND_TEST_RESULTS.html#matched-preparation-encoding-review-21-october-2026). CPU encoding and transferred bytes are different from GPU computation and complete-turn latency.

Keep this patch in a separate qualification checkout. It is not an instruction to patch a live gateway or bypass the source-manifest integrity gate. Requalify a candidate image, source manifest and actual DSH traffic before any future promotion. No session-append or stateful model-session protocol was deployed.

For a byte-preserving patch check in an isolated checkout, use `git -c core.autocrlf=false apply --unidiff-zero --check gpu-stack/experiments/warm-json-20261021/candidate.patch`. This avoids Windows newline conversion during content-hash verification.
