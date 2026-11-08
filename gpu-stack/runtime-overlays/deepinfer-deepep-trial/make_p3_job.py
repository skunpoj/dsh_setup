"""Derive the one-off P-3 DeepEP dispatch/combine check Job from the LIVE engine Deployment (read-only input).
usage: python -I make_p3_job.py LIVE.json CHECK.py OUT_DIR   -> OUT_DIR/p3-check-configmap.json + p3-check-job.json
Same image, PYTHONPATH, NCCL env, volumes and node as the engine; 4 GPUs; runs torchrun on the check script from a ConfigMap.
Must run only while BOTH engine Deployments are at 0 (GPUs free)."""
import copy, json, sys, os
live = json.load(open(sys.argv[1])); check = open(sys.argv[2], encoding="utf-8").read(); out = sys.argv[3]
ns = live["metadata"]["namespace"]; spec = live["spec"]["template"]["spec"]; c = copy.deepcopy(spec["containers"][0])
cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "p3-deepep-check", "namespace": ns}, "data": {"deepep_dispatch_combine_check.py": check}}
env = [e for e in c["env"] if e["name"] != "DEEPINFER_EP_COMM_BACKEND"] + [{"name": "DEEPINFER_EP_COMM_BACKEND", "value": "deepep"}]
cont = {"name": "p3", "image": c["image"], "env": env, "resources": c["resources"],
        "command": ["sh", "-c", "cd /tmp && exec /opt/sglang/bin/python3 -m torch.distributed.run --standalone --nproc_per_node=4 /check/deepep_dispatch_combine_check.py --rounds 3"],
        "volumeMounts": [m for m in c["volumeMounts"] if m["name"] in ("work", "shm", "tmp", "models")] + [{"name": "check", "mountPath": "/check"}]}
vols = [v for v in spec["volumes"] if v["name"] in ("work", "shm", "tmp", "models")] + [{"name": "check", "configMap": {"name": "p3-deepep-check"}}]
job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "p3-deepep-check", "namespace": ns, "annotations": {"dsh.example/purpose": "one-off DeepEP dispatch/combine correctness check; run only with both engines at 0 replicas"}},
       "spec": {"backoffLimit": 0, "activeDeadlineSeconds": 300, "ttlSecondsAfterFinished": 86400,
                "template": {"metadata": {"labels": {"app": "p3-deepep-check"}}, "spec": {"restartPolicy": "Never", "nodeSelector": spec["nodeSelector"],
                             "automountServiceAccountToken": False, "containers": [cont], "volumes": vols}}}}
json.dump(cm, open(os.path.join(out, "p3-check-configmap.json"), "w"), indent=1); json.dump(job, open(os.path.join(out, "p3-check-job.json"), "w"), indent=1)
print("wrote", out)
