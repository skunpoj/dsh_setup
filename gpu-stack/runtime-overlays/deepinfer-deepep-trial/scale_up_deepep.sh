#!/usr/bin/env bash
# Step 3 (17:36): only after P-3 PASS. Never leaves two engines on the 4 GPUs: NCCL to 0 and WAIT until its pods are gone, then DeepEP to 1.
set -eu; K=${K:-kubectl}; NS=llm
"$K" scale deploy/deepinfer-v4-1-flash -n $NS --replicas=0
for i in $(seq 1 120); do
  n=$("$K" get pods -n $NS -l engine=deepinfer --no-headers 2>/dev/null | wc -l)
  [ "$n" = 0 ] && break; sleep 5
done
[ "$n" = 0 ] || { echo "engine pods still present after 10 min ($n): NOT scaling DeepEP up"; exit 1; }
"$K" scale deploy/deepinfer-v4-1-flash-deepep -n $NS --replicas=1
