#!/usr/bin/env bash
# Step 1 (17:33): create the DeepEP Deployment at replicas 0 and the P-3 ConfigMap/Job definition files; starts NO pod.
set -eu; K=${K:-kubectl}; D="$(dirname "$0")"
"$K" apply -f "$D/deepinfer-v4-1-flash-deepep.json"
"$K" apply -f "$D/p3-check-configmap.json"
