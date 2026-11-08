#!/usr/bin/env bash
# Step 3 (17:36): only after P-3 PASS. NCCL engine must be 0. Scale the DeepEP engine up.
set -eu; K=${K:-kubectl}; NS=llm
"$K" scale deploy/deepinfer-v4-1-flash -n $NS --replicas=0
"$K" scale deploy/deepinfer-v4-1-flash-deepep -n $NS --replicas=1
