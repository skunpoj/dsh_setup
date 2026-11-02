"""Fixed read-only qualification API and explicit protected mTLS requester.

No kubeconfig, environment token, credential discovery, Windows authentication,
proxy, redirect, retry, exec, list, mutation or Secrets interface exists. The
requester runs only in the separately admitted protected control-plane process;
it is never an SDK child helper and is NOT configured by the default broker.
"""
import http.client
import json
from pathlib import Path
import re
import ssl
import stat
import sys

API_HOST = "kubernetes.default.svc"
IDENTITY_ROOT = Path("/etc/dsh-native-identity")
CA = IDENTITY_ROOT / "kubernetes-ca.crt"
CERTIFICATE = IDENTITY_ROOT / "kubernetes-client.crt"
PRIVATE_KEY = IDENTITY_ROOT / "kubernetes-client.key"
MAX_RESPONSE = 2 * 1024 * 1024


def name(value, *, namespace=False):
    if (not isinstance(value, str) or len(value) > (63 if namespace else 253)
            or not value or (namespace and "." in value)
            or any(len(part) > 63 or not re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", part)
                for part in value.split("."))):
        raise ValueError("INVALID_FIXED_QUALIFICATION_RESOURCE_NAME")
    return value


def fixed_paths(namespace, pod_name, job_name):
    namespace = name(namespace, namespace=True); pod_name = name(pod_name); job_name = name(job_name)
    return {
        ("Namespace", "v1", None, namespace): "/api/v1/namespaces/" + namespace,
        ("Pod", "v1", namespace, pod_name): "/api/v1/namespaces/" + namespace + "/pods/" + pod_name,
        ("Job", "batch/v1", namespace, job_name): "/apis/batch/v1/namespaces/" + namespace + "/jobs/" + job_name,
    }


def unique_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError("DUPLICATE_QUALIFICATION_API_FIELD")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def protected_identity_file(path, *, private=False):
    # Fixed role-mounted files, not an arbitrary secret lookup. Only metadata is
    # inspected here; ssl loads the approved client identity inside this process.
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("UNPROTECTED_CONTROL_PLANE_IDENTITY")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or (private and info.st_mode & 0o077):
        raise ValueError("UNPROTECTED_CONTROL_PLANE_IDENTITY")


class ProtectedQualificationRequester:
    """Concrete one-shot HTTPS GET. Construct only after physical admission.

    Construction loads the explicitly mounted mTLS identity. No constructor or
    method in this module is invoked against real identity/network by source
    tests; this is implementation, not an executed access/readiness receipt.
    """
    def __init__(self, *, namespace, pod_name, job_name):
        if sys.platform != "linux": raise ValueError("PROTECTED_CONTROL_PLANE_REQUIRES_LINUX")
        self.allowed_paths = frozenset(fixed_paths(namespace, pod_name, job_name).values())
        for path in (CA, CERTIFICATE): protected_identity_file(path)
        protected_identity_file(PRIVATE_KEY, private=True)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED; context.check_hostname = True
        context.load_verify_locations(cafile=str(CA))
        def refuse_password_prompt():
            raise ValueError("ENCRYPTED_CONTROL_PLANE_KEY_REFUSED_NO_PROMPT")
        context.load_cert_chain(certfile=str(CERTIFICATE), keyfile=str(PRIVATE_KEY), password=refuse_password_prompt)
        self.context = context

    def __call__(self, method, path, body):
        if method != "GET" or path not in self.allowed_paths or body is not None:
            raise ValueError("UNADMITTED_QUALIFICATION_API_OPERATION")
        connection = http.client.HTTPSConnection(API_HOST, 443, context=self.context, timeout=3)
        try:
            # No bearer/default identity, proxy headers or user-supplied headers.
            connection.request("GET", path, headers={"Accept": "application/json", "Connection": "close"})
            response = connection.getresponse()
            if response.status != 200:
                # 404/redirect/timeout is never an absence, permission or retry.
                raise ValueError("QUALIFICATION_NAMED_GET_FAILED")
            if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("QUALIFICATION_API_JSON_REQUIRED")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("QUALIFICATION_API_ENCODING_REFUSED")
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE: raise ValueError("QUALIFICATION_API_RESPONSE_TOO_LARGE")
            value = unique_json(raw)
            if not isinstance(value, dict): raise ValueError("QUALIFICATION_API_OBJECT_REQUIRED")
            return 200, value
        finally:
            connection.close()


class FixedQualificationReadAPI:
    def __init__(self, request, *, namespace, pod_name, job_name):
        if not callable(request): raise ValueError("PROTECTED_NAMED_GET_REQUESTER_REQUIRED")
        self.paths = fixed_paths(namespace, pod_name, job_name)
        self.request = request

    def read_resource(self, kind, api_version, namespace, resource_name):
        key = (kind, api_version, namespace, resource_name)
        if key not in self.paths: raise ValueError("UNADMITTED_QUALIFICATION_NAMED_RESOURCE")
        status, value = self.request("GET", self.paths[key], None)
        if type(status) is not int or status != 200 or not isinstance(value, dict):
            raise ValueError("QUALIFICATION_NAMED_GET_FAILED")
        meta = value.get("metadata", {})
        if (value.get("kind") != kind or value.get("apiVersion") != api_version
                or meta.get("name") != resource_name
                or (kind != "Namespace" and meta.get("namespace") != namespace)):
            raise ValueError("QUALIFICATION_API_RESOURCE_MISMATCH")
        return value
