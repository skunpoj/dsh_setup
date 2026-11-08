#!/usr/bin/env bash
# Step 2 (17:34): run P-3 as a one-off 4-GPU Job while BOTH engines are at 0. Exit 0 only on PASS.
set -eu; K=${K:-kubectl}; NS=llm; D="$(dirname "$0")"
n=$("$K" get pods -n $NS -l engine=deepinfer --no-headers | wc -l); [ "$n" = 0 ] || { echo "engine pods present ($n): abort"; exit 1; }
"$K" delete job p3-deepep-check -n $NS --ignore-not-found
"$K" apply -f "$D/p3-check-job.json"
"$K" wait --for=condition=complete job/p3-deepep-check -n $NS --timeout=240s || { "$K" logs job/p3-deepep-check -n $NS --tail=80; exit 1; }
"$K" logs job/p3-deepep-check -n $NS | tee "$D/p3_result.json" | tail -40
grep -q '"verdict": "PASS"' "$D/p3_result.json"
