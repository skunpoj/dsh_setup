#!/usr/bin/env bash
# Step 2 (17:34): run P-3 as a one-off 4-GPU Job while BOTH engines are at 0. Exit 0 only on PASS.
# Polls for Complete OR Failed (a failing job must not wait out the full timeout).
set -eu; K=${K:-kubectl}; NS=llm; D="$(dirname "$0")"
n=$("$K" get pods -n $NS -l engine=deepinfer --no-headers | wc -l); [ "$n" = 0 ] || { echo "engine pods present ($n): abort"; exit 1; }
"$K" delete job p3-deepep-check -n $NS --ignore-not-found
"$K" apply -f "$D/p3-check-job.json"
t0=$(date +%s); state=""
while [ $(( $(date +%s) - t0 )) -lt 300 ]; do
  c=$("$K" get job p3-deepep-check -n $NS -o jsonpath='{.status.conditions[?(@.status=="True")].type}' 2>/dev/null || true)
  case "$c" in *Complete*) state=complete; break;; *Failed*) state=failed; break;; esac
  sleep 5
done
echo "P3 job state: ${state:-timeout} after $(( $(date +%s) - t0 )) s"
"$K" logs job/p3-deepep-check -n $NS --tail=200 2>&1 | tee "$D/p3_result.json" | tail -60
[ "$state" = complete ] && grep -q '"verdict": "PASS"' "$D/p3_result.json"
