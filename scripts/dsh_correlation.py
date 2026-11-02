"""Opaque, non-secret DSH task and operation correlation identifiers."""
import hashlib
import re
import secrets

ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def new_task_correlation_id():
    return secrets.token_hex(16)


def validate_correlation_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("invalid DSH correlation id")
    return value


def operation_correlation_id(task_correlation_id, sequence, fingerprint):
    task_correlation_id = validate_correlation_id(task_correlation_id)
    if sequence < 1 or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("invalid correlation inputs")
    material = f"dsh-op-v1\0{task_correlation_id}\0{sequence}\0{fingerprint}".encode()
    return hashlib.sha256(material).hexdigest()[:32]
