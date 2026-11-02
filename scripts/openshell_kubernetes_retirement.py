"""Exact resource retirement component; not a complete OpenShell supervisor.

Uses the existing task journal and a namespace-scoped API. It does not issue a
public name-only native Stop, remove finalizers, kill a replacement or retry an
uncertain DELETE. Resource absence alone never proves worker process exit.
"""
import re
import threading
from scripts.openshell_kubernetes_identity import NATIVE_ID
from scripts.openshell_kubernetes_observer import complete_items
from scripts.openshell_task_binding import OpenShellBinding


class NativeKubernetesRetirement:
    def __init__(self,registry,api,*,namespace):
        if namespace!=api.namespace:raise ValueError('FOREIGN_NATIVE_NAMESPACE')
        self.registry,self.api,self.namespace=registry,api,namespace
        self.lock=threading.RLock()

    def _bound(self,assigned,operation):
        if (not isinstance(assigned,dict) or set(assigned)!=OpenShellBinding.KEYS|{'podUID'}
                or not isinstance(operation,str) or not re.fullmatch(r'[a-f0-9]{32}',operation)):
            raise ValueError('INVALID_NATIVE_RETIREMENT_IDENTITY')
        if not isinstance(assigned['workerUID'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,63}',assigned['workerUID']):
            raise ValueError('INVALID_NATIVE_RETIREMENT_SELECTOR')
        task=self.registry.get(assigned['taskId']);state=getattr(task,'openshell',None)
        if (task is None or task.request.get('backend')!='openshell' or not state
                or any(state.get(k)!=v for k,v in assigned.items())
                or state.get('phase')!='stop-reserved' or state.get('stopOperationId')!=operation
                or state.get('fenced') is not True or state.get('revoked') is not True):
            raise ValueError('UNRESERVED_NATIVE_RETIREMENT')
        identity=state.get('nativeResources',{})
        if (identity.get('namespace')!=self.namespace or identity.get('podUID')!=assigned['podUID']
                or any(identity.get(k)!=v for k,v in assigned.items())):
            raise ValueError('UNVERIFIED_NATIVE_RETIREMENT_RESOURCES')
        return task,state,identity

    def _resources(self,identity):
        return [('Sandbox',identity['sandboxAPIVersion'],identity['sandboxName'],identity['sandboxUID']),
                ('Pod','v1',identity['podName'],identity['podUID']),
                ('Pod','v1',identity['supervisorPodName'],identity['supervisorPodUID'])]

    def _snapshot(self,identity):
        values=[]
        for kind,version,name,uid in self._resources(identity):
            value=self.api.read_resource(self.namespace,kind,version,name)
            if value is not None:
                meta=value.get('metadata',{})
                if (value.get('kind')!=kind or value.get('apiVersion')!=version
                        or meta.get('namespace')!=self.namespace or meta.get('name')!=name
                        or meta.get('uid')!=uid or not isinstance(meta.get('resourceVersion'),str)
                        or not meta['resourceVersion']):
                    raise ValueError('NATIVE_RETIREMENT_RESOURCE_REPLACED')
            values.append(value)
        return values

    def retire_exact(self,assigned,operation):
        with self.lock:return self._retire_exact(assigned,operation)

    def _retire_exact(self,assigned,operation):
        task,state,identity=self._bound(assigned,operation)
        # Inspect every target before touching any, so a known replaced sibling
        # cannot cause partial deletion of the remaining task resources.
        snapshot=self._snapshot(identity)
        for spec,value in zip(self._resources(identity),snapshot):
            if value is None:continue
            self._bound(assigned,operation)
            kind,version,name,uid=spec
            key=kind+'/'+uid
            prior=task.openshell.get('nativeDeleteOperations',{})
            if key in prior:
                # Re-observe absence separately; never repeat a submitted call,
                # including after a timeout, crash or accepted-but-pending delete.
                raise ValueError('NATIVE_DELETE_ALREADY_RESERVED_NO_RETRY')
            record={'operationId':operation,'name':name,'uid':uid,'apiVersion':version,
                    'resourceVersion':value['metadata']['resourceVersion'],'phase':'reserved'}
            task.openshell={**task.openshell,'nativeDeleteOperations':{**prior,key:record}};task.save()
            receipt=self.api.delete_exact(self.namespace,kind,version,name,
                uid=uid,resource_version=record['resourceVersion'])
            if receipt!={'uid':uid,'resourceVersion':record['resourceVersion'],'deleteAccepted':True}:
                raise ValueError('NATIVE_DELETE_RECEIPT_MISMATCH')
            task.openshell['nativeDeleteOperations'][key]={**record,'phase':'accepted'};task.save()
        return self.verify_resources_absent(assigned,operation)

    def verify_resources_absent(self,assigned,operation):
        _,_,identity=self._bound(assigned,operation)
        if any(value is not None for value in self._snapshot(identity)):
            raise ValueError('NATIVE_RESOURCES_STILL_PRESENT')
        selector=NATIVE_ID+'='+assigned['workerUID']
        # Direct-name absence is insufficient if the controller produced another
        # Pod/name for the same native ID. List errors/pagination are not absence.
        pods=complete_items(self.api.list_pods(self.namespace,selector))
        sandboxes=complete_items(self.api.list_sandboxes(self.namespace,identity['sandboxAPIVersion'],selector))
        if pods or sandboxes:raise ValueError('NATIVE_RESOURCES_REAPPEARED')
        return {**assigned,'operationId':operation,'resourcesAbsent':True,
                'processExitVerified':False}
