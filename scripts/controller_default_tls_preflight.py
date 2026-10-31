"""Validate a declared controller-default certificate before shared-domain routing.

Input is public certificate PEM only. Never supply or export a private key.
This validates identity/time/pinning, not the system CA trust chain; normal HTTPS
probes against the live controller remain a separate required release gate.
"""
import hashlib
import os
import re
from pathlib import Path
import ssl
import tempfile
import time


def validate(settings, controller_arguments, public_certificate_pem, now=None):
    if not isinstance(settings, dict):
        raise ValueError("Settings must be an object")
    if not isinstance(controller_arguments, list) or not all(isinstance(value, str) for value in controller_arguments):
        raise ValueError("Controller arguments must be a list of strings")
    if settings.get("tlsMode") != "controller-default":
        raise ValueError("Controller-default mode must be explicit")
    ref = settings.get("controllerDefaultTls")
    if not isinstance(ref, dict) or set(ref) != {"namespace", "secretName", "certificateSha256"}:
        raise ValueError("Default certificate reference is malformed")
    if not all(isinstance(value, str) for value in ref.values()) or not re.fullmatch(r"[a-f0-9]{64}", ref["certificateSha256"]):
        raise ValueError("Default certificate fingerprint is malformed")
    if not isinstance(settings.get("domain"), str) or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}", settings["domain"]):
        raise ValueError("App domain is malformed")
    if not isinstance(public_certificate_pem, bytes):
        raise ValueError("Public certificate PEM must be bytes")
    expected = ref["namespace"] + "/" + ref["secretName"]
    if "--default-ssl-certificate=" + expected not in controller_arguments:
        raise ValueError("Running controller default certificate reference differs")
    if hashlib.sha256(public_certificate_pem).hexdigest() != ref["certificateSha256"]:
        raise ValueError("Controller certificate bytes differ from qualification")
    descriptor, name = tempfile.mkstemp(suffix=".pem")
    os.close(descriptor)
    try:
        Path(name).write_bytes(public_certificate_pem)
        certificate = ssl._ssl._test_decode_cert(name)
    finally:
        Path(name).unlink()
    clock = time.time() if now is None else now
    if not ssl.cert_time_to_seconds(certificate["notBefore"]) <= clock < ssl.cert_time_to_seconds(certificate["notAfter"]):
        raise ValueError("Controller default certificate is outside its validity period")
    if ("DNS", "*." + settings["domain"]) not in certificate.get("subjectAltName", ()):
        raise ValueError("Controller default certificate does not cover app hostnames")
    return {"defaultCertificate": expected, "sha256": ref["certificateSha256"],
            "domain": settings["domain"], "notAfter": certificate["notAfter"],
            "publicCertificateOnly": True, "normalLiveTlsStillRequired": True}
