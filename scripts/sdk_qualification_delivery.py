"""Exact, reviewable commands for the one late-bound file of the qualification run (OpenShell lane, P1). Builds argument lists; NEVER runs them.

The server admission embeds the Pod UID and the Job UID, which exist only after the Job has created its Pod, and it may be at most 300 s old when configure() reads it.
The Pod may not have init containers (official_sdk_executing_identity refuses them) and ConfigMap/Secret volumes are symlinks (protected_bytes refuses them), so the
operator writes the file into the memory-backed emptyDir mounted at /etc/dsh-native-admission with ONE exec on a typed order. The broker entry point waits for the file.
"""
import hashlib
import re

from scripts import sdk_qualification_k8s as q

POD = re.compile(r"[a-z0-9]([-a-z0-9]{0,60}[a-z0-9])?")
TARGET = q.ADMISSION_DIR + "/official-sdk-server.json"


class DeliveryRefused(ValueError):
    pass


SERVER_ADMISSION = "official-sdk-server.json"
LEASE = "a2a-factory-lease.json"
ALLOWED_TARGETS = (LEASE, SERVER_ADMISSION)   # the only initial late-bound files; the server admission is delivered LAST because the entry point waits for it
ROWS_DIR = "a2a-provider-rows"   # D10(b), reduced assurance: per-call write-once files <dir>/<litellm_call_id>.json, delivered inside the lease window
CALL_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def delivery_argv(spec, pod_name, content_sha256, kubectl="kubectl", target_name=SERVER_ADMISSION):
    """The argv of ONE `kubectl exec -i` that installs one late-bound file. The body goes in on stdin; the in-Pod script refuses unless its hash matches."""
    q.validate_spec(spec)
    if not isinstance(pod_name, str) or POD.fullmatch(pod_name) is None:
        raise DeliveryRefused("POD_NAME_REFUSED")
    if not isinstance(content_sha256, str) or re.fullmatch(r"[a-f0-9]{64}", content_sha256) is None or content_sha256 == "0" * 64:
        raise DeliveryRefused("CONTENT_HASH_REQUIRED")
    if target_name not in ALLOWED_TARGETS:
        raise DeliveryRefused("TARGET_NOT_ALLOWED")
    target = q.ADMISSION_DIR + "/" + target_name
    # fixed script text: no value is interpolated except the already validated hash and an allow-listed name; the directory must be root-owned and not
    # group/other writable for protected_bytes
    script = ("set -eu; umask 077; d=" + q.ADMISSION_DIR + "; chmod 0755 \"$d\"; cat > \"$d/.incoming\"; "
              "test \"$(sha256sum \"$d/.incoming\" | cut -d' ' -f1)\" = " + content_sha256 + "; "
              "test ! -e \"" + target + "\"; chmod 0444 \"$d/.incoming\"; mv \"$d/.incoming\" \"" + target + "\"")   # write-once: a second delivery of the same name is refused
    return [kubectl, "-n", spec["namespace"], "exec", "-i", pod_name, "-c", spec["containerName"], "--", "sh", "-c", script]


def row_argv(spec, pod_name, call_id, content_sha256, kubectl="kubectl"):
    """The argv of ONE `kubectl exec -i` that installs ONE provider-rows file <ROWS_DIR>/<call_id>.json (write-once, root-owned, 0444). The directory is
    created on first use (root, 0755); a second delivery of the same call id is refused by the in-Pod script."""
    q.validate_spec(spec)
    if not isinstance(pod_name, str) or POD.fullmatch(pod_name) is None:
        raise DeliveryRefused("POD_NAME_REFUSED")
    if not isinstance(call_id, str) or CALL_ID.fullmatch(call_id) is None:
        raise DeliveryRefused("CALL_ID_REQUIRED")
    if not isinstance(content_sha256, str) or re.fullmatch(r"[a-f0-9]{64}", content_sha256) is None or content_sha256 == "0" * 64:
        raise DeliveryRefused("CONTENT_HASH_REQUIRED")
    target = q.ADMISSION_DIR + "/" + ROWS_DIR + "/" + call_id + ".json"
    script = ("set -eu; umask 077; d=" + q.ADMISSION_DIR + "/" + ROWS_DIR + "; mkdir -p \"$d\"; chmod 0755 \"$d\"; cat > \"$d/.incoming\"; "
              "test \"$(sha256sum \"$d/.incoming\" | cut -d' ' -f1)\" = " + content_sha256 + "; "
              "test ! -e \"" + target + "\"; chmod 0444 \"$d/.incoming\"; mv \"$d/.incoming\" \"" + target + "\"")
    return [kubectl, "-n", spec["namespace"], "exec", "-i", pod_name, "-c", spec["containerName"], "--", "sh", "-c", script]


def delivery_plan(spec, pod_name, files, kubectl="kubectl"):
    """files: ordered [(target_name, sha256)]. Returns the argv list for the operator's single delivery step, in order. The server admission must be present
    and LAST: the entry point starts reading as soon as it appears, and the lease must already exist then."""
    names = [name for name, _ in files]
    if names.count(SERVER_ADMISSION) != 1 or names[-1] != SERVER_ADMISSION or len(set(names)) != len(names):
        raise DeliveryRefused("SERVER_ADMISSION_MUST_BE_LAST_AND_ONLY_ONCE")
    return [delivery_argv(spec, pod_name, sha, kubectl=kubectl, target_name=name) for name, sha in files]


def content_hash(raw):
    return hashlib.sha256(raw).hexdigest()
