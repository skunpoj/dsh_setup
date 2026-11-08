"""Real TLS Kubernetes REST transport restricted to one Test worker namespace.

Authentication is explicitly injected by the protected control plane. No
environment/Windows/credential-store lookup, proxy, redirect, token persistence,
retry, Secrets access, arbitrary exec, or namespace mutation exists here.
This transport does not grant admission or attest a physical runtime.
"""
import http.client
import json
import re
import ssl
from urllib.parse import urlsplit
from scripts.a2a_worker_journal import uid


def unique_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('DUPLICATE_WORKER_API_FIELD')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs)


class WorkerAPI:
    def __init__(self, *, origin, tls_context, authorization, namespace,
                 namespace_uid, connection_factory=http.client.HTTPSConnection):
        parsed=urlsplit(origin)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('','/') or parsed.query or parsed.fragment
                or any(c in origin for c in ('\r','\n','\0'))):
            raise ValueError('EXPLICIT_KUBERNETES_TLS_ORIGIN_REQUIRED')
        if (not isinstance(tls_context,ssl.SSLContext) or not tls_context.check_hostname
                or tls_context.verify_mode!=ssl.CERT_REQUIRED):
            raise ValueError('VERIFIED_KUBERNETES_TLS_CONTEXT_REQUIRED')
        if not callable(authorization):raise ValueError('EXPLICIT_AUTHORIZATION_SUPPLIER_REQUIRED')
        if not isinstance(namespace,str) or not re.fullmatch(r'dsh-a2a-[a-z0-9][a-z0-9-]{0,54}',namespace):
            raise ValueError('EXACT_WORKER_NAMESPACE_REQUIRED')
        self.origin,self.tls,self.authorization=parsed,tls_context,authorization
        self.namespace,self.namespace_uid=namespace,uid(namespace_uid)
        self.connection_factory=connection_factory
        self.ns_path='/api/v1/namespaces/'+namespace
        self.pods_path=self.ns_path+'/pods'

    @staticmethod
    def pod_name(name):
        if not isinstance(name,str) or not re.fullmatch(r'a2a-[a-f0-9]{32}',name):
            raise ValueError('EXACT_A2A_POD_NAME_REQUIRED')
        return name

    def _request(self,method,path,body=None):
        if not self.tls.check_hostname or self.tls.verify_mode!=ssl.CERT_REQUIRED:
            raise ValueError('VERIFIED_KUBERNETES_TLS_CONTEXT_REVOKED')
        allowed=(method=='GET' and path==self.ns_path or
                 method=='POST' and path==self.pods_path or
                 method in {'GET','DELETE'} and re.fullmatch(re.escape(self.pods_path)+r'/a2a-[a-f0-9]{32}',path))
        if not allowed:raise ValueError('WORKER_API_ROUTE_REFUSED')
        connection=None
        try:
            authorization=self.authorization()
            if (not isinstance(authorization,str) or not authorization.startswith('Bearer ')
                    or not 8<len(authorization)<=16384 or any(c in authorization for c in ('\r','\n','\0'))):
                raise ValueError('INVALID_INJECTED_WORKER_AUTHORIZATION')
            raw=None if body is None else json.dumps(body,separators=(',',':')).encode()
            if raw is not None and len(raw)>1048576:raise ValueError('WORKER_API_BODY_LIMIT')
            connection=self.connection_factory(self.origin.hostname,self.origin.port or 443,
                                               context=self.tls,timeout=15)
            connection.request(method,path,body=raw,
                headers={'Authorization':authorization,'Accept':'application/json','Content-Type':'application/json'})
            response=connection.getresponse()
            data=response.read(8388609)
            if len(data)>8388608:raise ValueError('WORKER_API_RESPONSE_LIMIT')
            value=unique_json(data)
            if not isinstance(value,dict):raise ValueError('INVALID_WORKER_API_RESPONSE')
            if 300<=response.status<400:raise ValueError('WORKER_API_REDIRECT_REFUSED')
            return response.status,value
        except Exception:
            # No request/header/provider detail is copied into an exception.
            # A failed POST/DELETE is uncertain and MUST NOT be resent.
            raise RuntimeError('WORKER_API_OPERATION_UNCERTAIN_NO_RETRY') from None
        finally:
            if connection is not None:connection.close()

    def read_namespace(self):
        status,value=self._request('GET',self.ns_path)
        meta=value.get('metadata',{})
        labels=meta.get('labels',{})
        if (status!=200 or value.get('kind')!='Namespace' or value.get('apiVersion')!='v1'
                or meta.get('name')!=self.namespace or meta.get('uid')!=self.namespace_uid
                or meta.get('deletionTimestamp') or not meta.get('resourceVersion')
                or labels.get('dsh.example.com/runtime-environment')!='test'
                or labels.get('dsh.example.com/runtime-purpose')!='qualification'):
            raise ValueError('WORKER_NAMESPACE_IDENTITY_OR_CLASSIFICATION_REFUSED')
        return value

    def read_pod(self,name):
        name=self.pod_name(name)
        self.read_namespace()
        status,value=self._request('GET',self.pods_path+'/'+name)
        self.read_namespace()  # Namespace replacement also fences a 404 result.
        if status==404 and value.get('kind')=='Status' and value.get('reason')=='NotFound':
            return None
        if status!=200:raise ValueError('WORKER_POD_READ_REFUSED')
        meta=value.get('metadata',{})
        if (value.get('kind')!='Pod' or value.get('apiVersion')!='v1'
                or meta.get('name')!=name or meta.get('namespace')!=self.namespace
                or not meta.get('resourceVersion')):
            raise ValueError('WORKER_POD_IDENTITY_UNAVAILABLE')
        uid(meta.get('uid'))
        return value

    def create_pod_once(self,manifest):
        # Caller must save its one-shot Task reservation BEFORE calling here.
        meta=manifest.get('metadata',{}) if isinstance(manifest,dict) else {}
        name=self.pod_name(meta.get('name'))
        if manifest.get('kind')!='Pod' or manifest.get('apiVersion')!='v1' or meta.get('namespace')!=self.namespace:
            raise ValueError('WORKER_CREATE_RESOURCE_REFUSED')
        self.read_namespace()
        status,value=self._request('POST',self.pods_path,manifest)
        if status!=201:raise ValueError('WORKER_CREATE_UNCERTAIN_NO_RESEND')
        self.read_namespace()
        actual=value.get('metadata',{})
        if (value.get('kind')!='Pod' or actual.get('name')!=name or actual.get('namespace')!=self.namespace):
            raise ValueError('WORKER_CREATE_RESPONSE_IDENTITY_MISMATCH')
        uid(actual.get('uid'))
        return value  # Not running-image, process-start or acceptance proof.

    def delete_pod_once(self, *, name, pod_uid, resource_version):
        name=self.pod_name(name);uid(pod_uid)
        if not isinstance(resource_version,str) or not re.fullmatch(r'[0-9]{1,32}',resource_version):
            raise ValueError('EXACT_WORKER_RESOURCE_VERSION_REQUIRED')
        self.read_namespace()
        options={'apiVersion':'v1','kind':'DeleteOptions','propagationPolicy':'Foreground',
                 'preconditions':{'uid':pod_uid,'resourceVersion':resource_version}}
        status,_=self._request('DELETE',self.pods_path+'/'+name,options)
        if status not in (200,202):raise ValueError('WORKER_DELETE_UNCERTAIN_NO_RESEND')
        return {'deleteAccepted':True,'podUID':pod_uid}  # Never an absence proof.
