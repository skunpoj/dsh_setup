"""Namespace-scoped native resource API, with an injected authenticated request.

No credential discovery, generic paths, Secrets, exec, force deletion or retry.
The protected server factory must supply a TLS-verified request implementation
returning (HTTP status, decoded JSON). This module does not create that identity.
"""
import re
from urllib.parse import urlencode
from scripts.openshell_kubernetes_identity import API_VERSIONS


class NativeKubernetesAPI:
    def __init__(self,request,*,namespace):
        if namespace not in {'dsh-openshell-test-20261028','dsh-openshell'}:
            raise ValueError('UNADMITTED_NATIVE_NAMESPACE')
        if not callable(request):raise ValueError('AUTHENTICATED_REQUEST_REQUIRED')
        self.request,self.namespace=request,namespace

    def _path(self,namespace,kind,api_version,name=None):
        if namespace!=self.namespace:raise ValueError('FOREIGN_NATIVE_NAMESPACE')
        if kind=='Pod' and api_version=='v1':base='/api/v1/namespaces/'+namespace+'/pods'
        elif kind=='Sandbox' and api_version in API_VERSIONS:
            base='/apis/'+api_version+'/namespaces/'+namespace+'/sandboxes'
        else:raise ValueError('UNADMITTED_NATIVE_RESOURCE')
        if name is not None:
            if not isinstance(name,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}',name):
                raise ValueError('INVALID_NATIVE_RESOURCE_NAME')
            base+='/'+name
        return base

    def _list(self,namespace,kind,api_version,selector):
        if not isinstance(selector,str) or not selector or len(selector)>1024:
            raise ValueError('INVALID_NATIVE_LIST_SELECTOR')
        path=self._path(namespace,kind,api_version)+'?'+urlencode({'labelSelector':selector})
        status,body=self.request('GET',path,None)
        if status!=200:raise ValueError('NATIVE_API_LIST_FAILED')
        return body

    def list_sandboxes(self,namespace,api_version,selector):
        return self._list(namespace,'Sandbox',api_version,selector)

    def list_pods(self,namespace,selector):return self._list(namespace,'Pod','v1',selector)

    def read_resource(self,namespace,kind,api_version,name):
        status,body=self.request('GET',self._path(namespace,kind,api_version,name),None)
        if status==404:return None
        if status!=200:raise ValueError('NATIVE_API_READ_FAILED')
        if not isinstance(body,dict):raise ValueError('NATIVE_API_READ_INVALID')
        return body

    def delete_exact(self,namespace,kind,api_version,name,*,uid,resource_version):
        for value in [uid,resource_version]:
            if not isinstance(value,str) or not value or len(value)>256:
                raise ValueError('NATIVE_DELETE_PRECONDITION_REQUIRED')
        path=self._path(namespace,kind,api_version,name)
        # UID fences replacements; resourceVersion also refuses changed objects.
        # Leave normal Pod grace/finalizers intact: no force/unsafe-store option.
        options={'apiVersion':'v1','kind':'DeleteOptions','propagationPolicy':'Foreground',
                 'preconditions':{'uid':uid,'resourceVersion':resource_version}}
        status,_=self.request('DELETE',path,options)
        if status not in (200,202):raise ValueError('NATIVE_CONDITIONAL_DELETE_NOT_ACCEPTED')
        # HTTP acceptance is deliberately not an absence or process-exit proof.
        return {'uid':uid,'resourceVersion':resource_version,'deleteAccepted':True}
