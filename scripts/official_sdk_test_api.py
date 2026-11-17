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

# Explicit qualification-only projected identity route. The selected entry never
# falls back to the retained mTLS requester, an environment token or credentials.
QUALIFICATION_NAMESPACE = 'dsh-a2a-qual'
QUALIFICATION_NAMESPACE_UID = '62a5f057-09b0-49c0-946f-2b986eef0059'
QUALIFICATION_ACCOUNT = 'sdk-qualification'
QUALIFICATION_TOKEN_ROOT = Path('/run/dsh-qualification-api')
QUALIFICATION_TOKEN = QUALIFICATION_TOKEN_ROOT / 'token'
QUALIFICATION_API_POLICY = Path('/etc/dsh-native-admission/qualification-api-identity.json')
QUALIFICATION_SELF_UID = Path('/run/dsh-executing-identity/pod-uid')


def qualification_projected_token_bytes(path, limit):
    """Fixed Kubelet projection: root1777 is safe ONLY on verified RO mount."""
    import os
    root = QUALIFICATION_TOKEN_ROOT
    if path != QUALIFICATION_TOKEN:raise ValueError('FIXED_QUALIFICATION_TOKEN_REQUIRED')
    # Ancestors are fixed directories, never the regular-file validator.
    for ancestor in (root.parent,*root.parent.parents):
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('QUALIFICATION_PROJECTED_ANCESTOR_DIRECTORY_REFUSED')
    root_before = root.lstat()
    root_identity = lambda s: (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid)
    mode = stat.S_IMODE(root_before.st_mode)
    if (not stat.S_ISDIR(root_before.st_mode) or root_before.st_uid != 0 or root_before.st_gid != 0
            or ((mode & 0o022) and mode != 0o1777) or not os.path.ismount(root)):
        raise ValueError('PROTECTED_QUALIFICATION_TOKEN_ROOT_REQUIRED')
    rootfd = os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        if root_identity(os.fstat(rootfd)) != root_identity(root_before) or not os.fstatvfs(rootfd).f_flag & os.ST_RDONLY:
            raise ValueError('QUALIFICATION_PROJECTED_ROOT_NOT_READONLY_OR_CHANGED')
        candidate = path.resolve(strict=True)
        if not candidate.is_relative_to(root) or candidate == root:
            raise ValueError('QUALIFICATION_TOKEN_PROJECTION_ESCAPE')
        parent = candidate.parent
        while parent != root:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
                raise ValueError('QUALIFICATION_PROJECTED_PARENT_REFUSED')
            parent = parent.parent
        before = candidate.lstat()
        file_identity = lambda s: (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_nlink,s.st_mtime_ns,s.st_ctime_ns)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
                or stat.S_IMODE(before.st_mode) not in (0o400,0o600) or before.st_nlink != 1
                or before.st_dev != root_before.st_dev or not 0 < before.st_size <= limit):
            raise ValueError('QUALIFICATION_PROJECTED_PRIVATE_FILE_REFUSED')
        fd = os.open(candidate,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            if file_identity(os.fstat(fd)) != file_identity(before) or not os.fstatvfs(fd).f_flag & os.ST_RDONLY:
                raise ValueError('QUALIFICATION_PROJECTED_FILE_NOT_READONLY_OR_CHANGED')
            with os.fdopen(fd,'rb',closefd=False) as stream:raw = stream.read(limit+1)
            if (len(raw) != before.st_size or len(raw)>limit or file_identity(os.fstat(fd)) != file_identity(before)
                    or file_identity(candidate.lstat()) != file_identity(before)):
                raise ValueError('QUALIFICATION_PROJECTED_FILE_CHANGED')
            if (root_identity(os.fstat(rootfd)) != root_identity(root_before)
                    or root_identity(root.lstat()) != root_identity(root_before)
                    or not os.fstatvfs(rootfd).f_flag & os.ST_RDONLY or not os.fstatvfs(fd).f_flag & os.ST_RDONLY
                    or not os.path.ismount(root)):
                raise ValueError('QUALIFICATION_PROJECTED_ROOT_CHANGED_AFTER_READ')
            return raw
        finally:os.close(fd)
    finally:os.close(rootfd)


def qualification_fixed_bytes(path, limit, *, projected=False):
    import os
    if projected:return qualification_projected_token_bytes(path,limit)
    candidate = path
    protected_identity_file(candidate, private=projected)
    fd = os.open(candidate, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        identity = lambda s: (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
        if before.st_size > limit or identity(candidate.lstat()) != identity(before):
            raise ValueError('QUALIFICATION_FIXED_FILE_IDENTITY_REFUSED')
        with os.fdopen(fd,'rb',closefd=False) as stream: raw = stream.read(limit+1)
        if len(raw)>limit or identity(os.fstat(fd))!=identity(before) or identity(candidate.lstat())!=identity(before):
            raise ValueError('QUALIFICATION_FIXED_FILE_CHANGED')
        return raw
    finally: os.close(fd)


def validate_qualification_token_claims(token, policy, *, self_uid, now):
    import base64
    expected = {'kind','namespace','namespaceUID','serviceAccount','serviceAccountUID','podName','podUID','jobName','audience'}
    uuid = r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}'
    if (not isinstance(policy,dict) or set(policy)!=expected or policy['kind']!='DSH_QUALIFICATION_PROJECTED_IDENTITY_V1'
            or policy['namespace']!=QUALIFICATION_NAMESPACE or policy['namespaceUID']!=QUALIFICATION_NAMESPACE_UID
            or policy['serviceAccount']!=QUALIFICATION_ACCOUNT
            or any(not re.fullmatch(uuid,str(policy[k])) for k in ('serviceAccountUID','podUID'))
            or policy['podUID']!=self_uid or not isinstance(policy['audience'],str) or not policy['audience']
            or len(policy['audience'])>256):
        raise ValueError('EXACT_QUALIFICATION_PROJECTED_IDENTITY_REQUIRED')
    name(policy['podName']);name(policy['jobName'])
    if not isinstance(token,str) or not 8<len(token)<=16384 or any(c in token for c in ('\r','\n','\0')):
        raise ValueError('QUALIFICATION_PROJECTED_TOKEN_REFUSED')
    try:
        parts=token.split('.')
        if len(parts)!=3 or not all(parts):raise ValueError()
        claims=unique_json(base64.urlsafe_b64decode(parts[1]+'='*((-len(parts[1]))%4)))
    except Exception:
        raise ValueError('QUALIFICATION_PROJECTED_TOKEN_REFUSED') from None
    kube=claims.get('kubernetes.io',{}) if isinstance(claims,dict) else {}
    audiences=claims.get('aud') if isinstance(claims,dict) else None
    if isinstance(audiences,str):audiences=[audiences]
    if (not isinstance(claims,dict) or claims.get('sub')!='system:serviceaccount:'+QUALIFICATION_NAMESPACE+':'+QUALIFICATION_ACCOUNT
            or type(claims.get('exp')) not in (int,float) or not now<claims['exp']<=now+660
            or type(claims.get('nbf',0)) not in (int,float) or claims.get('nbf',0)>now
            or not isinstance(audiences,list) or audiences!=[policy['audience']]
            or not isinstance(kube,dict) or kube.get('namespace')!=QUALIFICATION_NAMESPACE
            or not isinstance(kube.get('serviceaccount'),dict) or kube['serviceaccount'].get('name')!=QUALIFICATION_ACCOUNT
            or kube['serviceaccount'].get('uid')!=policy['serviceAccountUID']
            or not isinstance(kube.get('pod'),dict) or kube['pod'].get('name')!=policy['podName']
            or kube['pod'].get('uid')!=policy['podUID']):
        raise ValueError('QUALIFICATION_PROJECTED_TOKEN_BINDING_REFUSED')
    # These checks bind claims; API-server TLS authentication verifies signature.
    return token


class ProjectedTokenQualificationRequester:
    """Three named GETs, explicit projected identity, no credential fallback."""
    def __init__(self, *, namespace, pod_name, job_name):
        if sys.platform!='linux': raise ValueError('PROTECTED_CONTROL_PLANE_REQUIRES_LINUX')
        if namespace!=QUALIFICATION_NAMESPACE:raise ValueError('EXACT_QUALIFICATION_NAMESPACE_REQUIRED')
        self.allowed_paths=frozenset(fixed_paths(namespace,pod_name,job_name).values())
        self.policy=unique_json(qualification_fixed_bytes(QUALIFICATION_API_POLICY,16384))
        if self.policy.get('podName')!=pod_name or self.policy.get('jobName')!=job_name:
            raise ValueError('QUALIFICATION_API_POLICY_RESOURCE_MISMATCH')
        self.self_uid=qualification_fixed_bytes(QUALIFICATION_SELF_UID,128).decode('ascii').strip()
        protected_identity_file(CA)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.verify_mode=ssl.CERT_REQUIRED;context.check_hostname=True
        context.load_verify_locations(cafile=str(CA))
        self.context=context

    def __call__(self, method, path, body):
        import time
        if method!='GET' or path not in self.allowed_paths or body is not None:
            raise ValueError('UNADMITTED_QUALIFICATION_API_OPERATION')
        if not self.context.check_hostname or self.context.verify_mode!=ssl.CERT_REQUIRED:
            raise ValueError('QUALIFICATION_API_TLS_REVOKED')
        token=qualification_fixed_bytes(QUALIFICATION_TOKEN,16384,projected=True).decode('ascii').strip()
        token=validate_qualification_token_claims(token,self.policy,self_uid=self.self_uid,now=time.time())
        connection=http.client.HTTPSConnection(API_HOST,443,context=self.context,timeout=3)
        try:
            connection.request('GET',path,headers={'Authorization':'Bearer '+token,'Accept':'application/json','Connection':'close'})
            response=connection.getresponse()
            if response.status!=200:raise ValueError('QUALIFICATION_NAMED_GET_FAILED')
            if response.getheader('Content-Type','').split(';',1)[0].strip().lower()!='application/json':
                raise ValueError('QUALIFICATION_API_JSON_REQUIRED')
            if response.getheader('Content-Encoding','identity').lower()!='identity':
                raise ValueError('QUALIFICATION_API_ENCODING_REFUSED')
            raw=response.read(MAX_RESPONSE+1)
            if len(raw)>MAX_RESPONSE:raise ValueError('QUALIFICATION_API_RESPONSE_TOO_LARGE')
            value=unique_json(raw)
            if not isinstance(value,dict):raise ValueError('QUALIFICATION_API_OBJECT_REQUIRED')
            return 200,value
        except Exception:
            raise ValueError('QUALIFICATION_PROJECTED_API_FAILED_NO_FALLBACK') from None
        finally:connection.close()
