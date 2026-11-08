#!/usr/bin/env bash
# Wednesday: swap the NCCL engine for the DeepEP variant. Run ONLY after Gate A PASS and handover acceptance, and only with the
# user's typed OK in the operator session. Scale-to-0 first: the PVC is RWO and the 4 GPUs are shared.
set -eu
K=${K:-kubectl}; NS=llm; A=deepinfer-v4-1-flash; B=deepinfer-v4-1-flash-deepep
"$K" apply -f "$(dirname "$0")/$B.json"                 # creates B at replicas 0 (idempotent)
"$K" scale deploy/$A -n $NS --replicas=0
"$K" wait --for=delete pod -l app=vllm-deepseek-v4-1-flash,engine=deepinfer,'!variant' -n $NS --timeout=300s || true
[ "$("$K" get pods -n $NS -l engine=deepinfer --no-headers | wc -l)" = 0 ] || { echo "engine pods still present; abort"; exit 1; }
"$K" scale deploy/$B -n $NS --replicas=1
echo "DeepEP variant starting; Ready = pod 1/1 (startupProbe). Run: K=... bash t15_run.sh deepep YYYYMMDD"
