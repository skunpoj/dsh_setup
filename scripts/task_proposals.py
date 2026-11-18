"""Chat-proposed tasks that only a signed human confirmation can start (option C of the chat delegation route).

The DSH chat agent submits a PROPOSAL (no approval claim). The broker keeps it in memory, starts nothing and counts it nowhere. A person confirms it on a gateway card;
the gateway signs a short-lived receipt with an Ed25519 private key that only the gateway holds; only a receipt whose signature verifies against the configured PUBLIC key
and whose every field equals the stored proposal turns the proposal into a task. The chat agent and the gateway use the same bearer token to the broker, so the signature is
the only thing that proves the click: no key, an unsafe key file or a bad signature means confirmation is refused (fail closed).

Receipt (the POST body of /v1/tasks/<id>/confirm): taskId, runtime, project, writes, backend, promptSha256, subject, origin, expiresAt, exp, nonce, sig.
Everything except `sig` is signed as canonical JSON: json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=True) encoded as UTF-8; `sig` is the standard
base64 of the 64-byte Ed25519 signature. exp is epoch seconds, at most 120 s ahead and not past.
"""
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path

TTL_SECONDS = 600
RECEIPT_MAX_AHEAD = 120
MAX_PENDING_PER_SUBJECT = 5
MAX_PENDING_TOTAL = 50
RUNTIMES = ("sdk", "claude", "deepagents")
PUBKEY_ENV = "DSH_CONFIRM_PUBKEY_FILE"
DEFAULT_PUBKEY = "/opt/dsh/config/confirm-receipt-public.pem"
NODE = os.environ.get("DSH_NODE", "/usr/local/bin/node")
NONCE = re.compile(r"[A-Za-z0-9_-]{16,64}")
PROPOSAL_ID = re.compile(r"[a-f0-9]{32}")
SIGNED_FIELDS = ("taskId", "runtime", "project", "writes", "backend", "promptSha256", "subject", "origin", "expiresAt", "exp", "nonce")
VERIFY_SCRIPT = ("const c=require('crypto'),f=require('fs');"
                 "try{const k=c.createPublicKey(f.readFileSync(process.argv[1]));"
                 "if(k.asymmetricKeyType!=='ed25519')process.exit(3);"
                 "process.exit(c.verify(null,f.readFileSync(0),k,Buffer.from(process.argv[2],'base64'))?0:1)}catch(e){process.exit(2)}")


class KeyUnavailable(Exception):
    pass


def canonical(fields):
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def prompt_hash(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def read_only_mount(path):
    try:
        return bool(os.statvfs(path).f_flag & getattr(os, "ST_RDONLY", 1))
    except (OSError, AttributeError):
        return False


def key_path_checked(path, owner_uid=0, check_owner=True):
    """The public key must be a regular file that only root can write, on a path the chat uid cannot redirect.

    A Kubernetes ConfigMap volume exposes each file as a symlink into a kubelet-owned directory (a subPath mount gives a regular file). A symlink is therefore accepted
    only when its filesystem is mounted READ-ONLY (the chat shell cannot repoint it) and the resolved target is a regular, root-owned, not group/other-writable file."""
    p = Path(path)
    try:
        link = os.lstat(p)
        info = os.stat(p)
    except OSError as error:
        raise KeyUnavailable("CONFIRMATION_KEY_MISSING") from error
    if stat.S_ISLNK(link.st_mode) and os.name != "nt" and not read_only_mount(p.parent):
        raise KeyUnavailable("CONFIRMATION_KEY_SYMLINK_ON_WRITABLE_MOUNT")
    if not stat.S_ISREG(info.st_mode):
        raise KeyUnavailable("CONFIRMATION_KEY_NOT_A_REGULAR_FILE")
    if os.name != "nt" and info.st_mode & 0o022:   # POSIX permission bits do not exist on the Windows test host; the image is Linux
        raise KeyUnavailable("CONFIRMATION_KEY_WRITABLE_BY_OTHERS")
    if check_owner and info.st_uid != owner_uid:
        raise KeyUnavailable("CONFIRMATION_KEY_WRONG_OWNER")
    return str(p)


def node_verify(pubkey_path, data, signature_b64, timeout=5):
    try:
        base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError):
        return False
    try:
        done = subprocess.run([NODE, "-e", VERIFY_SCRIPT, pubkey_path, signature_b64], input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        raise KeyUnavailable("CONFIRMATION_VERIFIER_UNAVAILABLE") from error
    if done.returncode == 0:
        return True
    if done.returncode == 1:
        return False
    raise KeyUnavailable("CONFIRMATION_KEY_UNUSABLE")


class Refusal(Exception):
    def __init__(self, status, error):
        super().__init__(error)
        self.status, self.error = status, error


class Proposals:
    def __init__(self, clock=time.time, key_file=None, owner_uid=0, check_owner=True, verifier=node_verify):
        self.clock, self.verifier, self.owner_uid, self.check_owner = clock, verifier, owner_uid, check_owner
        self.key_file = key_file
        self.lock = threading.Lock()
        self.items = {}
        self.nonces = {}

    def pubkey(self):
        return key_path_checked(self.key_file or os.environ.get(PUBKEY_ENV, DEFAULT_PUBKEY), self.owner_uid, self.check_owner)

    def now(self):
        return int(self.clock())

    def sweep(self):
        now = self.now()
        for item in self.items.values():
            if item["state"] == "proposed" and now >= item["expiresAt"]:
                item["state"] = "expired"
        for nonce, exp in list(self.nonces.items()):
            if now > exp + 5:
                del self.nonces[nonce]
        done = [key for key, item in self.items.items() if item["state"] != "proposed" and now > item["expiresAt"] + 3600]
        for key in done:
            del self.items[key]

    @staticmethod
    def view(item):
        keys = ("id", "state", "runtime", "project", "writes", "backend", "prompt", "promptSha256", "origin", "createdAt", "expiresAt")
        out = {key: item[key] for key in keys}
        if item.get("taskId"):
            out["taskId"] = item["taskId"]
        if item.get("error"):
            out["error"] = item["error"]
        return out

    def create(self, subject, request):
        """request: runtime, backend, project, writes, prompt, origin (already validated by the broker). subject may be '' (single-user private workspace)."""
        with self.lock:
            self.sweep()
            pending = [i for i in self.items.values() if i["state"] == "proposed"]
            if len(pending) >= MAX_PENDING_TOTAL or sum(1 for i in pending if i["subject"] == subject) >= MAX_PENDING_PER_SUBJECT:
                raise Refusal(409, "TOO_MANY_PENDING_PROPOSALS")
            now = self.now()
            item = {"id": uuid.uuid4().hex, "state": "proposed", "subject": subject, "createdAt": now, "expiresAt": now + TTL_SECONDS,
                    "promptSha256": prompt_hash(request["prompt"]), "taskId": None, "error": None}
            item.update({key: request[key] for key in ("runtime", "backend", "project", "writes", "prompt", "origin")})
            self.items[item["id"]] = item
            return self.view(item)

    def visible(self, item, subject):
        return item["subject"] in ("", subject)

    def list(self, subject):
        with self.lock:
            self.sweep()
            return [self.view(i) for i in self.items.values() if i["state"] == "proposed" and self.visible(i, subject)]

    def get(self, proposal_id, subject):
        with self.lock:
            self.sweep()
            item = self.items.get(proposal_id)
            if item is None:
                return None
            if not self.visible(item, subject):
                raise Refusal(403, "FOREIGN_PROPOSAL_SUBJECT")
            return self.view(item)

    def owns(self, proposal_id):
        with self.lock:
            return proposal_id in self.items

    def deny(self, proposal_id, subject):
        with self.lock:
            self.sweep()
            item = self.items.get(proposal_id)
            if item is None:
                raise Refusal(404, "PROPOSAL_NOT_FOUND")
            if not self.visible(item, subject):
                raise Refusal(403, "FOREIGN_PROPOSAL_SUBJECT")
            if item["state"] != "proposed":
                raise Refusal(409, "PROPOSAL_NOT_PENDING")
            item["state"] = "cancelled"
            return self.view(item)

    def confirm(self, proposal_id, subject, receipt, create_task):
        """create_task(request_with_approved_true, authenticated_subject) -> (status, body). Raises Refusal; returns (status, body)."""
        with self.lock:
            self.sweep()
            item = self.items.get(proposal_id)
            if item is None:
                raise Refusal(404, "PROPOSAL_NOT_FOUND")
            if not self.visible(item, subject):
                raise Refusal(403, "FOREIGN_PROPOSAL_SUBJECT")
            if item["state"] != "proposed":
                raise Refusal(409, "PROPOSAL_NOT_PENDING")
            if not subject:
                raise Refusal(400, "SUBJECT_REQUIRED")
            if not isinstance(receipt, dict) or set(receipt) != set(SIGNED_FIELDS) | {"sig"}:
                raise Refusal(400, "INVALID_RECEIPT")
            sig = receipt["sig"]
            fields = {key: receipt[key] for key in SIGNED_FIELDS}
            expected = {"taskId": item["id"], "runtime": item["runtime"], "project": item["project"], "writes": item["writes"], "backend": item["backend"],
                        "promptSha256": item["promptSha256"], "subject": subject, "origin": item["origin"], "expiresAt": item["expiresAt"]}
            for key, value in expected.items():
                if type(fields[key]) is not type(value) or fields[key] != value:
                    raise Refusal(400, "RECEIPT_MISMATCH")
            now = self.now()
            exp, nonce = fields["exp"], fields["nonce"]
            if type(exp) is not int or exp < now or exp > now + RECEIPT_MAX_AHEAD:
                raise Refusal(400, "RECEIPT_EXPIRED_OR_TOO_FAR")
            if not isinstance(nonce, str) or not NONCE.fullmatch(nonce) or not isinstance(sig, str) or len(sig) > 200:
                raise Refusal(400, "INVALID_RECEIPT")
            if nonce in self.nonces:
                raise Refusal(409, "RECEIPT_REPLAYED")
            try:
                valid = self.verifier(self.pubkey(), canonical(fields), sig)
            except KeyUnavailable as error:
                raise Refusal(503, str(error))
            if not valid:
                raise Refusal(403, "RECEIPT_SIGNATURE_INVALID")
            request = {"runtime": item["runtime"], "backend": item["backend"], "project": item["project"], "prompt": item["prompt"],
                       "writes": item["writes"], "approved": True, "origin": item["origin"]}
            try:
                status, body = create_task(request, item["subject"] or None)
            except ValueError as error:
                item["state"] = "failed"
                item["error"] = str(error)
                self.nonces[nonce] = exp
                raise Refusal(400, str(error))
            except RuntimeError as error:
                raise Refusal(409, str(error))      # e.g. TASK_ALREADY_ACTIVE: the proposal stays pending, the person can confirm again with a new receipt
            if status == 202 and isinstance(body, dict) and body.get("taskId"):
                item["state"], item["taskId"] = "approved", body["taskId"]
                self.nonces[nonce] = exp
                return 202, {"id": item["id"], "state": "approved", "taskId": body["taskId"]}
            item["state"], item["error"] = "failed", str((body or {}).get("error", "CREATE_FAILED")) if isinstance(body, dict) else "CREATE_FAILED"
            self.nonces[nonce] = exp
            raise Refusal(status if isinstance(status, int) else 500, item["error"])


PROPOSALS = Proposals()
