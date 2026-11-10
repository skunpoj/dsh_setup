"""Mint the SDK server admission (kind DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1, mode qualification) for ONE qualification Job (OpenShell lane, P1).

official_sdk_bootstrap.configure() reads /etc/dsh-native-admission/official-sdk-server.json and needs: an exact key set, expiresAt 1..300 s ahead of the clock that reads it, the
image digest, the package admission hash, the scope module hash, the sha256 of EVERY protected source role in bootstrap.SOURCES (read from the module, so a role added later is
covered automatically), and the deploymentBinding (namespace, namespaceUID, podUID, workloadUID, environment, workloadRole) which exists only after the Job has created its Pod.

This module only builds the bytes. It never touches a cluster, never reads a credential, never delivers the file (delivery is sdk_qualification_delivery, one operator exec).
Before returning it runs the REAL configure() on those bytes with injected fakes for everything physical; a descriptor configure() would refuse is never returned.
"""
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import official_sdk_bootstrap as bootstrap  # noqa: E402

KIND = "DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1"
FIXED_PATH = "/etc/dsh-native-admission/official-sdk-server.json"
DEFAULT_TTL_SECONDS = 270
SCOPE_MODULE = "/opt/dsh/scripts/a2a_sdk_scope_factory.py"
UID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}")
SHA256 = re.compile(r"[a-f0-9]{64}")


class MintRefused(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise MintRefused(code)


def tree_reader(dsh_root):
    """Reader for the image paths /opt/dsh/... that reads the same relative file from a checked-out tree (the image copies the tree there).
    A wrong mapping can only make the Pod's own configure() refuse later (it re-hashes the real image files); it can never make it accept."""
    dsh_root = Path(dsh_root)

    def read(path, limit=1024 * 1024):
        _require(isinstance(path, str) and path.startswith("/opt/dsh/") and ".." not in Path(path).parts, "SOURCE_PATH_REFUSED:" + str(path))
        target = dsh_root / path[len("/opt/dsh/"):]
        _require(target.is_file() and not target.is_symlink(), "SOURCE_MISSING:" + path)
        raw = target.read_bytes()
        _require(len(raw) <= limit, "SOURCE_TOO_LARGE:" + path)
        return raw
    return read


def build_descriptor(*, read_source, source_commit, image_digest, package_admission_raw, subject, generation, binding, now, ttl=DEFAULT_TTL_SECONDS):
    _require(re.fullmatch(r"[a-f0-9]{40}", str(source_commit)) and source_commit != "0" * 40, "SOURCE_COMMIT_REQUIRED")
    _require(isinstance(image_digest, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest) and image_digest != "sha256:" + "0" * 64, "IMAGE_DIGEST_REQUIRED")
    for name, value in (("subject", subject), ("generation", generation)):
        _require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}", value), "INVALID_" + name.upper())
    _require(type(ttl) is int and 0 < ttl <= 295, "TTL_1_TO_295_REQUIRED")
    _require(isinstance(binding, dict) and set(binding) == {"namespace", "namespaceUID", "podUID", "workloadUID"}, "BINDING_KEYS")
    _require(all(UID.fullmatch(str(binding[k])) for k in ("namespaceUID", "podUID", "workloadUID")), "BINDING_UIDS_REQUIRED")
    _require(re.fullmatch(r"dsh-a2a-[a-z0-9][a-z0-9-]{0,54}", str(binding["namespace"])), "A2A_OWNED_TEST_NAMESPACE_REQUIRED")
    package = json.loads(package_admission_raw)
    _require(isinstance(package, dict) and package.get("kind") == "DSH_OFFICIAL_SDK_PACKAGE_V1", "PACKAGE_ADMISSION_KIND")
    sources = {role: hashlib.sha256(read_source(path, 1024 * 1024)).hexdigest() for role, path in bootstrap.SOURCES.items()}
    scope_sha = hashlib.sha256(read_source(SCOPE_MODULE, 1024 * 1024)).hexdigest()
    return {"kind": KIND, "mode": "qualification", "subject": subject, "generation": generation, "expiresAt": int(now) + ttl, "sourceCommit": source_commit,
            "imageDigest": image_digest, "packageAdmissionSha256": hashlib.sha256(package_admission_raw).hexdigest(), "scopeModule": SCOPE_MODULE,
            "scopeSha256": scope_sha, "sources": sources,
            "deploymentBinding": dict(binding, environment="test", workloadRole="qualification")}


def selfcheck(raw, *, read_source, package_admission_raw, binding, now):
    """Run the REAL configure() on these exact bytes with injected fakes for everything physical (observer, package check, scope factory, service)."""
    class Scope:
        pass

    def reader(path, limit):
        return raw if path == FIXED_PATH else read_source(path, limit)

    def package_check():
        return {"admissionSha256": hashlib.sha256(package_admission_raw).hexdigest()}

    def factory_loader(module, source):
        return lambda **kwargs: {"scope": Scope(), "guardFactory": object()}

    server = SimpleNamespace()
    registry = SimpleNamespace(tasks={})
    try:
        accepted = bootstrap.configure(server, registry, FIXED_PATH, qualification_allowed=True, reader=reader, package_check=package_check,
                                       factory_loader=factory_loader, clock=lambda: now, runner_factory=lambda **kwargs: SimpleNamespace(qualified=True),
                                       deployment_observer=lambda: dict(binding, environment="test", workloadRole="qualification"))
    except ValueError as error:
        raise MintRefused("CONFIGURE_REFUSED:" + str(error)) from error
    _require(accepted is True and getattr(server, "sdk_service", None) is not None, "CONFIGURE_DID_NOT_ENABLE_THE_SERVICE")
    return True


def mint(*, read_source, source_commit, image_digest, package_admission_raw, subject, generation, binding, now, ttl=DEFAULT_TTL_SECONDS):
    descriptor = build_descriptor(read_source=read_source, source_commit=source_commit, image_digest=image_digest, package_admission_raw=package_admission_raw,
                                  subject=subject, generation=generation, binding=binding, now=now, ttl=ttl)
    raw = (json.dumps(descriptor, sort_keys=True, indent=2) + "\n").encode("utf-8")
    selfcheck(raw, read_source=read_source, package_admission_raw=package_admission_raw, binding=binding, now=now)
    return raw, descriptor
