"""Mint the A2A factory execution lease (/etc/dsh-native-admission/a2a-factory-lease.json) for ONE qualification Job (OpenShell lane).

ProtectedA2AFactory._fresh() (a2a_factory_contract) reads this finite lease on every bind and every model-start check. It must have EXACTLY these keys:
subject, generation, namespace, namespaceUID, nodeName, image, sourceCommit, packageAdmissionSha256, provider, resourceBudget, expiresAt, modelStartsAllowed, rollbackOwner.
The first ten must equal the controllers' own values (provider and resourceBudget are the module constants PROVIDER and BUDGET), 0 < expiresAt - now <= 300,
modelStartsAllowed is an int 0..3 (a model start needs >= 1), rollbackOwner matches [A-Za-z0-9_.@:-]{1,128}.

Like the server admission it can only be written AFTER the Pod exists (the Pod's node is known only after scheduling, the namespace UID only from the live read-back).
This module builds bytes only. It never touches a cluster, never reads a credential, never delivers the file (sdk_qualification_delivery does, with one operator exec).
Before returning, it runs the REAL ProtectedA2AFactory._fresh on those bytes against a stand-in that carries the controllers' values.
"""
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import a2a_factory_contract as factory  # noqa: E402

FIXED_PATH = "/etc/dsh-native-admission/a2a-factory-lease.json"
DEFAULT_TTL_SECONDS = 270
UID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
NODE = re.compile(r"[a-z0-9][a-z0-9.-]{0,252}")


class LeaseRefused(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise LeaseRefused(code)


def node_from_pod(pod, *, excluded_nodes=()):
    """The node the broker Pod really runs on, from the live Pod read-back; refused when unscheduled or on an excluded node."""
    _require(isinstance(pod, dict) and pod.get("kind") == "Pod", "POD_READBACK_REQUIRED")
    node = pod.get("spec", {}).get("nodeName")
    _require(isinstance(node, str) and NODE.fullmatch(node), "POD_NOT_SCHEDULED")
    _require(node not in set(excluded_nodes), "POD_ON_AN_EXCLUDED_NODE")
    return node


def build_lease(*, subject, generation, namespace, namespace_uid, node_name, image, source_commit, package_admission_sha256, now,
                model_starts=1, rollback_owner="operator-session", ttl=DEFAULT_TTL_SECONDS):
    _require(all(isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", v) for v in (subject, generation)), "INVALID_SUBJECT_OR_GENERATION")
    _require(re.fullmatch(r"dsh-a2a-[a-z0-9][a-z0-9-]{0,54}", str(namespace)), "A2A_OWNED_TEST_NAMESPACE_REQUIRED")
    _require(UID.fullmatch(str(namespace_uid)), "NAMESPACE_UID_REQUIRED")
    _require(isinstance(node_name, str) and NODE.fullmatch(node_name), "NODE_NAME_REQUIRED")
    _require(isinstance(image, str) and 0 < len(image) <= 512 and "@" in image, "IMAGE_REFERENCE_REQUIRED")
    _require(re.fullmatch(r"[a-f0-9]{40}", str(source_commit)) and source_commit != "0" * 40, "SOURCE_COMMIT_REQUIRED")
    _require(re.fullmatch(r"[a-f0-9]{64}", str(package_admission_sha256)) and package_admission_sha256 != "0" * 64, "PACKAGE_ADMISSION_SHA256_REQUIRED")
    _require(type(model_starts) is int and 0 <= model_starts <= 3, "MODEL_STARTS_0_TO_3_REQUIRED")
    _require(isinstance(rollback_owner, str) and re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", rollback_owner), "INVALID_ROLLBACK_OWNER")
    _require(type(ttl) is int and 0 < ttl <= 295, "TTL_1_TO_295_REQUIRED")
    return {"subject": subject, "generation": generation, "namespace": namespace, "namespaceUID": namespace_uid, "nodeName": node_name, "image": image,
            "sourceCommit": source_commit, "packageAdmissionSha256": package_admission_sha256, "provider": dict(factory.PROVIDER),
            "resourceBudget": dict(factory.BUDGET), "expiresAt": int(now) + ttl, "modelStartsAllowed": model_starts, "rollbackOwner": rollback_owner}


def selfcheck(raw, *, subject, generation, namespace, namespace_uid, node_name, image, source_commit, package_admission_sha256, now):
    """The REAL ProtectedA2AFactory._fresh on these exact bytes, with a stand-in carrying the controllers' own values."""
    sdk = SimpleNamespace(subject=subject, generation=generation, api=SimpleNamespace(namespace=namespace, namespace_uid=namespace_uid),
                          node_name=node_name, image=image, source_commit=source_commit, package_hash=package_admission_sha256)
    placement = {"namespace": namespace}
    standin = SimpleNamespace(sdk=sdk, placement=placement, observe=lambda: placement, read=lambda: json.loads(raw), clock=lambda: now)
    try:
        return factory.ProtectedA2AFactory._fresh(standin)
    except ValueError as error:
        raise LeaseRefused("FACTORY_REFUSED:" + str(error)) from error


def mint(*, subject, generation, namespace, namespace_uid, node_name, image, source_commit, package_admission_sha256, now,
         model_starts=1, rollback_owner="operator-session", ttl=DEFAULT_TTL_SECONDS):
    lease = build_lease(subject=subject, generation=generation, namespace=namespace, namespace_uid=namespace_uid, node_name=node_name, image=image,
                        source_commit=source_commit, package_admission_sha256=package_admission_sha256, now=now, model_starts=model_starts,
                        rollback_owner=rollback_owner, ttl=ttl)
    raw = (json.dumps(lease, sort_keys=True, indent=2) + "\n").encode("utf-8")
    selfcheck(raw, subject=subject, generation=generation, namespace=namespace, namespace_uid=namespace_uid, node_name=node_name, image=image,
              source_commit=source_commit, package_admission_sha256=package_admission_sha256, now=now)
    return raw, lease
