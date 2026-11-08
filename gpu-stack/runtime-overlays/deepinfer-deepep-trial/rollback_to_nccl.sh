#!/usr/bin/env bash
# Rollback (optional per user): scale B to 0, wait for pods gone, scale A to 1. A is never modified, so rollback = scale swap.
set -eu
K=${K:-kubectl}; NS=llm; A=deepinfer-v4-1-flash; B=deepinfer-v4-1-flash-deepep
"$K" scale deploy/$B -n $NS --replicas=0
"$K" wait --for=delete pod -l engine=deepinfer,variant=deepep -n $NS --timeout=300s || true
[ "$("$K" get pods -n $NS -l engine=deepinfer --no-headers | wc -l)" = 0 ] || { echo "pods still present; abort"; exit 1; }
"$K" scale deploy/$A -n $NS --replicas=1
