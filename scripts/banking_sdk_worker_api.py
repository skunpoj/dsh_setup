"""Distinct banking-only namespace/PVC/Pod/immutable grant API. Explicit TLS+bearer; no discovery, Secrets, retry or delete."""
import http.client
import json
import re
import threading
import ssl
from urllib.parse import urlsplit
from scripts.a2a_worker_journal import uid
from scripts.banking_sdk_scope_factory import canonical,digest
from scripts.banking_sdk_worker import worker_template,validate_grant
from scripts.banking_sdk_package_mounts import package_inputs,package_map_names,validate_package_map
from scripts import banking_allowance


def unique_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('DUPLICATE_WORKER_API_FIELD')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs)


class BankingWorkerAPI:
    def __init__(self, *, origin, tls_context, authorization, namespace,
                 namespace_uid, allowed_claims, controller_refs=None, allowed_accounts=None, admission=None, policy=None, reservation_validator=None, connection_factory=http.client.HTTPSConnection):
        parsed=urlsplit(origin)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in ('','/') or parsed.query or parsed.fragment
                or any(c in origin for c in ('\r','\n','\0'))):
            raise ValueError('EXPLICIT_KUBERNETES_TLS_ORIGIN_REQUIRED')
        if (not isinstance(tls_context,ssl.SSLContext) or not tls_context.check_hostname
                or tls_context.verify_mode!=ssl.CERT_REQUIRED):
            raise ValueError('VERIFIED_KUBERNETES_TLS_CONTEXT_REQUIRED')
        if not callable(authorization):raise ValueError('EXPLICIT_AUTHORIZATION_SUPPLIER_REQUIRED')
        if not isinstance(namespace,str) or not re.fullmatch(r'llm',namespace):
            raise ValueError('EXACT_WORKER_NAMESPACE_REQUIRED')
        self.origin,self.tls,self.authorization=parsed,tls_context,authorization
        self.namespace,self.namespace_uid=namespace,uid(namespace_uid)
        if not isinstance(allowed_claims,dict) or len(allowed_claims)!=2 or any(not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',str(k)) for k in allowed_claims):
            raise ValueError('EXACT_BANKING_PVC_IDENTITIES_REQUIRED')
        for value in allowed_claims.values():uid(value)
        self.admission,self.policy,self.reservation_validator=admission,policy,reservation_validator
        self.pod_templates={};self.pod_uids={};self.grant_bodies={};self.grant_uids={};self.used_posts=set();self.posting=threading.local()
        self.allowed_claims=dict(allowed_claims)
        self.allowed_accounts=dict(allowed_accounts or {})
        if set(self.allowed_accounts)-{'dsh-banking-sdk-controller','dsh-banking-sdk-worker'}:raise ValueError('BANKING_DEDICATED_ACCOUNT_NAMES_REQUIRED')
        for value in self.allowed_accounts.values():uid(value)
        self.controller_refs=dict(controller_refs or {})
        if set(self.controller_refs)-{'Pod','ReplicaSet','Deployment'} or any(not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}',str(v)) for v in self.controller_refs.values()):raise ValueError('EXACT_BANKING_CONTROLLER_REFERENCES_REQUIRED')
        self.reference_paths={k:('/api/v1/namespaces/'+namespace+'/pods/' if k=='Pod' else '/apis/apps/v1/namespaces/'+namespace+('/replicasets/' if k=='ReplicaSet' else '/deployments/'))+name for k,name in self.controller_refs.items()}
        self.connection_factory=connection_factory
        self.ns_path='/api/v1/namespaces/'+namespace
        self.pods_path=self.ns_path+'/pods'
        self.maps_path=self.ns_path+'/configmaps'
        self.claims_path=self.ns_path+'/persistentvolumeclaims'

    @staticmethod
    def pod_name(name):
        if not isinstance(name,str) or not re.fullmatch(r'a2a-[a-f0-9]{32}',name):
            raise ValueError('EXACT_A2A_POD_NAME_REQUIRED')
        return name

    def _request(self,method,path,body=None):
        if not self.tls.check_hostname or self.tls.verify_mode!=ssl.CERT_REQUIRED:
            raise ValueError('VERIFIED_KUBERNETES_TLS_CONTEXT_REVOKED')
        post_digest=digest(body) if method=='POST' and isinstance(body,dict) else None
        allowed=(method=='GET' and path in self.reference_paths.values() or method=='GET' and path==self.ns_path
                 or method=='POST' and path in {self.pods_path,self.maps_path} and getattr(self.posting,'digest',None)==post_digest and post_digest is not None
                 or method=='GET' and path in {self.pods_path+'/'+name for name in self.pod_uids}
                 or method=='GET' and path in {self.claims_path+'/'+name for name in self.allowed_claims}
                 or method=='GET' and path in {self.ns_path+'/serviceaccounts/'+name for name in self.allowed_accounts}
                 or method=='GET' and path in {self.maps_path+'/'+name for name in self.grant_uids}
                 or method=='GET' and path in {self.maps_path+'/'+name for name in package_map_names()})
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
        if status!=200:raise ValueError('BANKING_NAMESPACE_HTTP_'+str(status))
        meta=value.get('metadata',{})
        # llm is a shared namespace. Its exact identity is checked here;
        # Test/banking classification belongs to the admitted controller and
        # worker resources and is verified independently. Native unchanged.
        if value.get('kind')!='Namespace' or value.get('apiVersion')!='v1':why='KIND'
        elif meta.get('name')!=self.namespace:why='NAME'
        elif meta.get('uid')!=self.namespace_uid:why='UID'
        elif meta.get('deletionTimestamp'):why='DELETING'
        elif not isinstance(meta.get('resourceVersion'),str) or not meta['resourceVersion']:why='RESOURCE_VERSION'
        else:why=None
        if why:raise ValueError('BANKING_NAMESPACE_IDENTITY_REFUSED_'+why)
        return value

    def read_pod(self,name):
        name=self.pod_name(name)
        if name not in self.pod_uids:raise ValueError('BANKING_UNBOUND_OR_FOREIGN_POD_READ')
        self.read_namespace()
        status,value=self._request('GET',self.pods_path+'/'+name)
        self.read_namespace()  # Namespace replacement also fences a 404 result.
        if status==404 and value.get('kind')=='Status' and value.get('reason')=='NotFound':
            return None
        if status!=200:raise ValueError('WORKER_POD_READ_REFUSED')
        meta=value.get('metadata',{})
        if (value.get('kind')!='Pod' or value.get('apiVersion')!='v1'
                or meta.get('name')!=name or meta.get('namespace')!=self.namespace or meta.get('uid')!=self.pod_uids[name]
                or not meta.get('resourceVersion')):
            raise ValueError('WORKER_POD_IDENTITY_UNAVAILABLE')
        uid(meta.get('uid'))
        return value

    def read_claim(self,name):
        if name not in self.allowed_claims:raise ValueError('BANKING_PVC_SCOPE_REFUSED')
        self.read_namespace();status,value=self._request('GET',self.claims_path+'/'+name);self.read_namespace()
        meta=value.get('metadata',{})
        if status!=200 or value.get('kind')!='PersistentVolumeClaim' or meta.get('name')!=name or meta.get('namespace')!=self.namespace or meta.get('uid')!=self.allowed_claims[name] or meta.get('deletionTimestamp') or value.get('status',{}).get('phase')!='Bound':
            raise ValueError('BANKING_PVC_IDENTITY_OR_BINDING_REFUSED')
        return value

    def read_package_inputs(self):
        contract=package_inputs(namespace=self.namespace,namespace_uid=self.namespace_uid,admission_sha256=self.admission.get('packageAdmissionSha256'))
        result=[]
        for item in contract['inputs']:
            self.read_namespace();status,value=self._request('GET',self.maps_path+'/'+item['name']);self.read_namespace()
            if status!=200:raise ValueError('BANKING_PACKAGE_CONFIGMAP_READ_REFUSED')
            result.append(validate_package_map(value,item))
        return result

    def bind_task(self,*,binding,cap,template):
        if not isinstance(self.admission,dict) or not isinstance(self.policy,dict) or not callable(self.reservation_validator):
            raise ValueError('EXPLICIT_BANKING_API_ADMISSION_REQUIRED')
        if (not banking_allowance._valid_sdk_binding(binding,binding.get('taskId') if isinstance(binding,dict) else None,binding)
                or binding['subject']!=self.admission['authenticatedSubject'] or binding['generation']!=self.admission['generation']
                or binding['runId']!=self.admission['runId'] or binding['project']!=self.policy['project'] or not (cap is None and self.admission['expiresAt'] is None or type(cap) is int and 2<=cap<=32)):
            raise ValueError('FOREIGN_BANKING_API_TASK_BINDING')
        reservation=self.reservation_validator(binding['taskId'])
        if not isinstance(reservation,dict) or reservation.get('binding')!=binding or reservation.get('cap')!=cap or not re.fullmatch(r'[a-f0-9]{64}',str(reservation.get('grantSha256'))):
            raise ValueError('BANKING_GLOBAL_RESERVATION_REQUIRED_BEFORE_API')
        policy={k:v for k,v in self.policy.items() if k not in {'workspaceClaimUID','project','serviceAccountUID'}}
        operation=digest(dict(scope=self.admission['scopeDigest'],task=binding['taskId'],binding=binding))[:32]
        expected=worker_template(admission=self.admission,binding=binding,cap=cap,policy=policy,create_operation=operation)
        if canonical(expected)!=canonical(template):raise ValueError('BANKING_API_TEMPLATE_NOT_ADMITTED')
        self.read_package_inputs()
        name=expected['metadata']['name']
        if name in self.pod_templates:raise ValueError('BANKING_API_TASK_REBIND_REFUSED')
        self.pod_templates[name]=dict(body=expected,binding=binding,cap=cap,grantSha256=reservation['grantSha256'])

    def bind_recovery_read(self,*,template,pod_uid,grant_name,grant_uid):
        # Called only after protected backend original/WAL identity validation.
        uid(pod_uid);uid(grant_uid);name=self.pod_name(template['metadata']['name'])
        if template['metadata']['namespace']!=self.namespace or grant_name!='sdk-bank-grant-'+name[4:]:raise ValueError('EXACT_BANKING_RECOVERY_OBJECTS_REQUIRED')
        if name in self.pod_uids and self.pod_uids[name]!=pod_uid or grant_name in self.grant_uids and self.grant_uids[grant_name]!=grant_uid:raise ValueError('BANKING_RECOVERY_UID_CHANGED')
        self.pod_uids[name]=pod_uid;self.grant_uids[grant_name]=grant_uid
        # Never authorizes a new POST or attach.

    def create_once(self,body):
        if not isinstance(body,dict):raise ValueError('EXACT_BANKING_OBJECT_REQUIRED')
        meta=body.get('metadata',{});kind=body.get('kind');name=meta.get('name')
        if meta.get('namespace')!=self.namespace:raise ValueError('BANKING_CREATE_NAMESPACE_REFUSED')
        if kind=='Pod':
            admitted=self.pod_templates.get(name)
            if admitted is None or canonical(body)!=canonical(admitted['body']):raise ValueError('BANKING_UNADMITTED_POD_CREATE')
            self.read_package_inputs()
            path=self.pods_path
        elif kind=='ConfigMap':
            if not isinstance(name,str) or not re.fullmatch(r'sdk-bank-grant-[a-f0-9]{32}',name):raise ValueError('BANKING_GRANT_NAME_REFUSED')
            pod_name='a2a-'+name.removeprefix('sdk-bank-grant-');admitted=self.pod_templates.get(pod_name)
            if admitted is None or pod_name not in self.pod_uids or set(body)!={'apiVersion','kind','metadata','immutable','data'} or body.get('immutable') is not True or set(body.get('data',{}))!={'grant.json'}:
                raise ValueError('BANKING_UNADMITTED_GRANT_CREATE')
            import time
            grant=validate_grant(unique_json(body['data']['grant.json'].encode()),worker_uid=self.pod_uids[pod_name],clock=time.time)
            if grant['binding']!=admitted['binding'] or grant['cap']!=admitted['cap'] or grant['grantSha256']!=admitted['grantSha256'] or grant['scopeDigest']!=self.admission['scopeDigest']:raise ValueError('BANKING_GRANT_RESERVATION_MISMATCH')
            path=self.maps_path
        else:raise ValueError('BANKING_CREATE_KIND_REFUSED')
        key=(kind,name)
        if key in self.used_posts:raise ValueError('BANKING_POST_ALREADY_CONSUMED')
        self.read_namespace();self.used_posts.add(key);self.posting.digest=digest(body)
        try:status,value=self._request('POST',path,body)
        finally:self.posting.digest=None
        self.read_namespace()
        if status!=201 or value.get('kind')!=kind or value.get('metadata',{}).get('name')!=name or value['metadata'].get('namespace')!=self.namespace:
            raise ValueError('BANKING_CREATE_UNCERTAIN_NO_RETRY')
        uid(value['metadata'].get('uid'))
        if kind=='Pod':
            self.pod_uids[name]=value['metadata']['uid']
            self.read_package_inputs()
        else:self.grant_uids[name]=value['metadata']['uid']
        return value

    def read_grant(self,name):
        if name not in self.grant_uids or not re.fullmatch(r'sdk-bank-grant-[a-f0-9]{32}',str(name)):raise ValueError('BANKING_GRANT_NAME_REFUSED')
        self.read_namespace();status,value=self._request('GET',self.maps_path+'/'+name);self.read_namespace()
        if status!=200 or value.get('kind')!='ConfigMap' or value.get('apiVersion')!='v1' or value.get('immutable') is not True or value.get('metadata',{}).get('namespace')!=self.namespace or value['metadata'].get('name')!=name or value['metadata'].get('uid')!=self.grant_uids[name] or value['metadata'].get('deletionTimestamp') or not value['metadata'].get('resourceVersion'):
            raise ValueError('BANKING_IMMUTABLE_GRANT_READ_REFUSED')
        return value

    def read_reference(self,kind):
        if kind not in self.reference_paths:raise ValueError('BANKING_CONTROLLER_REFERENCE_REFUSED')
        self.read_namespace();status,value=self._request('GET',self.reference_paths[kind]);self.read_namespace()
        meta=value.get('metadata',{})
        if status!=200 or value.get('kind')!=kind or meta.get('name')!=self.controller_refs[kind] or meta.get('namespace')!=self.namespace or meta.get('deletionTimestamp') or not meta.get('resourceVersion'):
            raise ValueError('BANKING_CONTROLLER_RESOURCE_REFUSED')
        uid(meta.get('uid'));return value

    def read_account(self,name):
        if name not in self.allowed_accounts:raise ValueError('BANKING_FOREIGN_SERVICE_ACCOUNT_REFUSED')
        self.read_namespace();status,value=self._request('GET',self.ns_path+'/serviceaccounts/'+name);self.read_namespace()
        meta=value.get('metadata',{})
        if status!=200 or value.get('kind')!='ServiceAccount' or value.get('apiVersion')!='v1' or meta.get('name')!=name or meta.get('namespace')!=self.namespace or meta.get('uid')!=self.allowed_accounts[name] or meta.get('deletionTimestamp') or not meta.get('resourceVersion'):
            raise ValueError('BANKING_DEDICATED_SERVICE_ACCOUNT_IDENTITY_REFUSED')
        return value
