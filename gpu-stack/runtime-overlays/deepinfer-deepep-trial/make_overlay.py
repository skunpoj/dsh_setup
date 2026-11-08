"""Derive the inactive DeepEP Deployment from the LIVE Deployment (read-only input).
usage: python -I make_overlay.py LIVE.json OUT.json
Only delta vs live: name, replicas 0, one pod label, DEEPINFER_EP_COMM_BACKEND nccl->deepep. Everything else (image digest,
tokenizer-privacy overlay+annotations, args, PVCs, probes, resources, nodeSelector) is copied byte-for-byte from live."""
import copy, json, sys
live = json.load(open(sys.argv[1]))
NEW = "deepinfer-v4-1-flash-deepep"
d = {"apiVersion": "apps/v1", "kind": "Deployment"}
m = live["metadata"]
d["metadata"] = {"name": NEW, "namespace": m["namespace"],
  "labels": {**m.get("labels", {}), "variant": "deepep"},
  "annotations": {"dsh.example/purpose": "iommu=pt trial: DEEPINFER_EP_COMM_BACKEND=deepep. INACTIVE (replicas 0). Never run together with deepinfer-v4-1-flash (shared GPUs, RWO PVC).",
                  "dsh.example/derived-from-generation": str(m.get("generation"))}}
spec = copy.deepcopy(live["spec"])
for k in ("progressDeadlineSeconds",):
    pass
spec["replicas"] = 0
spec["selector"]["matchLabels"]["variant"] = "deepep"
spec["template"]["metadata"]["labels"]["variant"] = "deepep"
spec["template"]["metadata"].pop("creationTimestamp", None)
envs = spec["template"]["spec"]["containers"][0]["env"]
hit = [e for e in envs if e["name"] == "DEEPINFER_EP_COMM_BACKEND"]
assert len(hit) == 1 and hit[0]["value"] == "nccl", hit
hit[0]["value"] = "deepep"
d["spec"] = spec
json.dump(d, open(sys.argv[2], "w"), indent=2)
print("wrote", sys.argv[2])
