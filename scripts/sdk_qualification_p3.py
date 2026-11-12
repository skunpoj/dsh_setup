"""P3 helper of the OpenShell lane: the pure, local parts of one native qualification run. It NEVER decides to run anything.

The PowerShell runner (RUN_P3.ps1, hash-pinned by the execution contract) does every cluster action, one step at a time, on a typed order. This module
only (1) writes the reviewed objects to disk, (2) checks live read-backs the runner saved against the admitted spec, and (3) at the delivery step mints the
two late-bound files from those read-backs and installs them with the allow-listed exec commands, lease first and server admission last, inside the window.
The only process it can start is the kubectl path the runner gives it, and only with argument lists built by sdk_qualification_delivery.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import make_a2a_factory_lease as lease_minter  # noqa: E402
from scripts import make_official_sdk_server_admission as server_minter  # noqa: E402
from scripts import sdk_qualification_delivery as delivery  # noqa: E402
from scripts import sdk_qualification_k8s as q  # noqa: E402

STAGE_NAMESPACE = ("namespace", "limitrange", "resourcequota")
STAGE_OBJECTS = ("serviceaccount", "networkpolicy-default-deny", "networkpolicy-broker", "networkpolicy-worker", "configmap-sdk-wheel", "configmap-package-admission",
                 "configmap-workspace-policy", "persistentvolumeclaim-workspace", "role-observer", "role-worker-controller", "clusterrole-read-namespace",
                 "rolebinding-observer", "rolebinding-worker-controller", "clusterrolebinding-read-namespace")
STAGE_CLIENT = ("networkpolicy-client", "configmap-client-script", "pod-client")   # only when the run carries the A2A lane's pinned driver files
STAGE_JOB = ("job",)
STAGES = (("namespace", STAGE_NAMESPACE), ("objects", STAGE_OBJECTS), ("job", STAGE_JOB))


def _stages(client):
    return (("namespace", STAGE_NAMESPACE), ("objects", STAGE_OBJECTS + (STAGE_CLIENT if client else ())), ("job", STAGE_JOB))
DELIVERY_SAFETY_SECONDS = 15   # each exec must start at least this long before the shared expiry
EXEC_TIMEOUT_SECONDS = 60


class P3Refused(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise P3Refused(code)


def _write_exclusive(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(raw)
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _load(path):
    return json.loads(Path(path).read_bytes())


# ---------------------------------------------------------------------------------------------------------------------------------------------------
def prepare(run_dir, spec, wheel_raw, package_admission_raw, client_files=None):
    """Write inputs/ and objects/ for one run (exclusive creation). Returns {file: sha256} for the contract."""
    objects = q.build_objects(spec, wheel_raw=wheel_raw, package_admission_raw=package_admission_raw, client_files=client_files)
    q.check_objects(objects, spec, wheel_raw=wheel_raw, package_admission_raw=package_admission_raw, client_files=client_files)
    stages = _stages(client_files is not None)
    listed = [key for _, keys in stages for key in keys]
    _require(sorted(listed) == sorted(objects) and len(set(listed)) == len(listed), "STAGES_DO_NOT_COVER_THE_GENERATED_OBJECTS")
    run = Path(run_dir)
    hashes = {}
    hashes["inputs/spec.json"] = _write_exclusive(run / "inputs" / "spec.json", _json_bytes(spec))
    hashes["inputs/sdk-wheel.whl"] = _write_exclusive(run / "inputs" / "sdk-wheel.whl", wheel_raw)
    hashes["inputs/official-sdk-package.json"] = _write_exclusive(run / "inputs" / "official-sdk-package.json", package_admission_raw)
    for name, raw in sorted((client_files or {}).items()):
        hashes["inputs/client/" + name] = _write_exclusive(run / "inputs" / "client" / name, raw)
    order = []
    for number, (stage, keys) in enumerate(stages):
        for index, key in enumerate(keys):
            name = "%d%02d-%s.json" % (number, index, key)
            hashes["objects/" + name] = _write_exclusive(run / "objects" / name, _json_bytes(objects[key]))
            order.append({"stage": stage, "key": key, "file": name})
    hashes["ORDER.json"] = _write_exclusive(run / "ORDER.json", _json_bytes(order))
    return hashes


def _client_files(run_dir):
    folder = Path(run_dir) / "inputs" / "client"
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.is_dir() else None


def _inputs(run_dir):
    run = Path(run_dir)
    spec = _load(run / "inputs" / "spec.json")
    wheel = (run / "inputs" / "sdk-wheel.whl").read_bytes()
    package = (run / "inputs" / "official-sdk-package.json").read_bytes()
    return spec, wheel, package


def check_live(run_dir, readback_dir, stages=None):
    """The saved `kubectl get -f ... -o json` read-backs (one file per key, <key>.json) must hold everything the admitted spec generates.
    `stages` (default: all) names the stages that exist so far; the keys of later stages are taken from the generated objects, so they cannot fail yet."""
    spec, wheel, package = _inputs(run_dir)
    client = _client_files(run_dir)
    generated = q.build_objects(spec, wheel_raw=wheel, package_admission_raw=package, client_files=client)
    known = {name for name, _ in STAGES}
    _require(stages is None or (stages and set(stages) <= known), "UNKNOWN_STAGE")
    live = {}
    for entry in _load(Path(run_dir) / "ORDER.json"):
        if stages is not None and entry["stage"] not in stages:
            live[entry["key"]] = generated[entry["key"]]
            continue
        path = Path(readback_dir) / (entry["key"] + ".json")
        _require(path.is_file(), "READBACK_MISSING:" + entry["key"])
        live[entry["key"]] = _load(path)
    return q.check_objects(live, spec, wheel_raw=wheel, package_admission_raw=package, client_files=client)


def check_pod(run_dir, readback_dir):
    """The broker Pod: created by THIS Job, scheduled, running, in the admitted image, with the admitted Pod spec. Returns (pod name, node, binding UIDs)."""
    spec, wheel, package = _inputs(run_dir)
    objects = q.build_objects(spec, wheel_raw=wheel, package_admission_raw=package, client_files=_client_files(run_dir))
    read = Path(readback_dir)
    job, pod, namespace = _load(read / "job.json"), _load(read / "pod.json"), _load(read / "namespace.json")
    _require(pod.get("kind") == "Pod" and job.get("kind") == "Job" and namespace.get("kind") == "Namespace", "READBACK_KINDS")
    uids = {"namespaceUID": namespace["metadata"]["uid"], "workloadUID": job["metadata"]["uid"], "podUID": pod["metadata"]["uid"]}
    owners = pod["metadata"].get("ownerReferences") or []
    _require(len(owners) == 1 and owners[0].get("kind") == "Job" and owners[0].get("uid") == uids["workloadUID"] and owners[0].get("name") == spec["jobName"], "POD_NOT_OWNED_BY_THIS_JOB")
    _require(pod["metadata"]["namespace"] == spec["namespace"], "POD_NAMESPACE")
    _require(pod.get("status", {}).get("phase") == "Running", "POD_NOT_RUNNING")
    statuses = pod["status"].get("containerStatuses") or []
    _require(len(statuses) == 1 and statuses[0].get("name") == spec["containerName"] and "running" in (statuses[0].get("state") or {}), "CONTAINER_NOT_RUNNING")
    digest = spec["image"].rsplit("@", 1)[1]
    _require(str(statuses[0].get("imageID", "")).endswith(digest), "RUNNING_IMAGE_IS_NOT_THE_ADMITTED_DIGEST")
    template_spec = copy.deepcopy(objects["job"]["spec"]["template"]["spec"])
    q.contains(pod["spec"], template_spec, "$.pod.spec")
    node = lease_minter.node_from_pod(pod, excluded_nodes=spec["excludedNodes"])
    return {"podName": pod["metadata"]["name"], "nodeName": node, "binding": dict(uids, namespace=spec["namespace"])}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
def default_exec(argv, stdin_bytes):
    done = subprocess.run(argv, input=stdin_bytes, capture_output=True, timeout=EXEC_TIMEOUT_SECONDS, check=False)   # noqa: S603 (allow-listed argv)
    return done.returncode, done.stdout, done.stderr


def deliver(run_dir, readback_dir, *, kubectl, read_source, source_commit, subject, generation, now_fn=time.time, run=default_exec, rollback_owner="operator-session",
            model_starts=1):
    """Mint the lease and the server admission from the live read-backs with ONE `now`, then install them: lease first, server admission last."""
    spec, wheel, package = _inputs(run_dir)
    pod = check_pod(run_dir, readback_dir)
    now = int(now_fn())
    image_digest = "sha256:" + spec["image"].rsplit("@sha256:", 1)[1]
    binding = pod["binding"]
    admission_raw, _ = server_minter.mint(read_source=read_source, source_commit=source_commit, image_digest=image_digest, package_admission_raw=package,
                                          subject=subject, generation=generation, binding=binding, now=now)
    q.check_server_admission(admission_raw, spec, binding, now=now)
    lease_raw, _ = lease_minter.mint(subject=subject, generation=generation, namespace=spec["namespace"], namespace_uid=binding["namespaceUID"], node_name=pod["nodeName"],
                                     image=spec["image"], source_commit=source_commit, package_admission_sha256=hashlib.sha256(package).hexdigest(), now=now,
                                     model_starts=model_starts, rollback_owner=rollback_owner)
    expiry = now + server_minter.DEFAULT_TTL_SECONDS
    files = [(delivery.LEASE, lease_raw), (delivery.SERVER_ADMISSION, admission_raw)]
    plan = delivery.delivery_plan(spec, pod["podName"], [(name, delivery.content_hash(raw)) for name, raw in files], kubectl=kubectl)
    log = []
    for (name, raw), argv in zip(files, plan):
        _write_exclusive(Path(run_dir) / "delivery" / name, raw)
        _require(now_fn() < expiry - DELIVERY_SAFETY_SECONDS, "DELIVERY_WINDOW_ALMOST_OVER_NOTHING_MORE_IS_SENT")
        code, out, err = run(argv, raw)
        log.append({"file": name, "sha256": delivery.content_hash(raw), "exit": code, "stdoutSha256": hashlib.sha256(out or b"").hexdigest(),
                    "stderrSha256": hashlib.sha256(err or b"").hexdigest(), "stderrBytes": len(err or b"")})
        _require(code == 0, "EXEC_FAILED:" + name)
    return {"pod": pod["podName"], "node": pod["nodeName"], "mintedAt": now, "expiresAt": expiry, "delivered": log}


MAX_ROW_BYTES = 64 * 1024


def deliver_row(run_dir, readback_dir, row_raw, *, kubectl, run=default_exec):
    """D10(b), REDUCED ASSURANCE: install ONE operator-supplied LiteLLM spend row for ONE admitted call as <rows dir>/<litellm_call_id>.json, write-once,
    inside the lease window (the capture reads it when the task is captured). The bytes are the operator's evidence: only their shape is checked here
    (one JSON object with a canonical-UUID litellm_call_id, the file name); the A2A reconciliation judges the content."""
    _require(isinstance(row_raw, bytes) and 0 < len(row_raw) <= MAX_ROW_BYTES, "ROW_FILE_SIZE")
    try:
        row = json.loads(row_raw)
    except ValueError:
        raise P3Refused("ROW_FILE_NOT_JSON") from None
    _require(isinstance(row, dict) and isinstance(row.get("litellm_call_id"), str) and delivery.CALL_ID.fullmatch(row["litellm_call_id"]), "ROW_OBJECT_WITH_CALL_ID_REQUIRED")
    spec, _, _ = _inputs(run_dir)
    pod = check_pod(run_dir, readback_dir)
    sha = delivery.content_hash(row_raw)
    argv = delivery.row_argv(spec, pod["podName"], row["litellm_call_id"], sha, kubectl=kubectl)
    code, out, err = run(argv, row_raw)
    _require(code == 0, "EXEC_FAILED:row:" + row["litellm_call_id"])
    return {"pod": pod["podName"], "callId": row["litellm_call_id"], "sha256": sha, "stderrBytes": len(err or b"")}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--run-dir", required=True)
    prep.add_argument("--spec", required=True)
    prep.add_argument("--wheel", required=True)
    prep.add_argument("--package-admission", required=True)
    for name in ("check-live", "check-pod", "deliver", "deliver-row"):
        item = sub.add_parser(name)
        item.add_argument("--run-dir", required=True)
        item.add_argument("--readback-dir", required=True)
        if name == "check-live":
            item.add_argument("--stages", default=None, help="comma list of the stages that exist so far (namespace,objects,job)")
        if name == "deliver-row":
            item.add_argument("--kubectl", required=True)
            item.add_argument("--row-file", required=True)
        if name == "deliver":
            item.add_argument("--kubectl", required=True)
            item.add_argument("--source-root", required=True)
            item.add_argument("--source-commit", required=True)
            item.add_argument("--subject", required=True)
            item.add_argument("--generation", required=True)
            item.add_argument("--model-starts", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args.run_dir, _load(args.spec), Path(args.wheel).read_bytes(), Path(args.package_admission).read_bytes())
        elif args.command == "check-live":
            result = check_live(args.run_dir, args.readback_dir, args.stages.split(",") if args.stages else None)
        elif args.command == "check-pod":
            result = check_pod(args.run_dir, args.readback_dir)
        elif args.command == "deliver-row":
            result = deliver_row(args.run_dir, args.readback_dir, Path(args.row_file).read_bytes(), kubectl=args.kubectl)
        else:
            result = deliver(args.run_dir, args.readback_dir, kubectl=args.kubectl, read_source=server_minter.tree_reader(args.source_root),
                             source_commit=args.source_commit, subject=args.subject, generation=args.generation, model_starts=args.model_starts)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print("P3_REFUSED:" + type(error).__name__ + ":" + str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
