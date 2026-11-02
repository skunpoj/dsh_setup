"""Concrete journal-bound observation side of the native supervisor.

The protected factory injects its already-authenticated, namespace-scoped API.
This module never loads kubeconfig, a token, or an alternate access route.
Assignment publication and exact stop are separate operations, not implied by
successful observation. API list failures or pagination are never absence.
"""
import re
from scripts.openshell_kubernetes_identity import API_VERSIONS,ROLE,NATIVE_ID,GATEWAY


def complete_items(value):
    if (not isinstance(value,dict) or not isinstance(value.get('items'),list)
            or not isinstance(value.get('metadata'),dict)
            or not isinstance(value['metadata'].get('resourceVersion'),str)
            or not value['metadata']['resourceVersion']
            or value['metadata'].get('continue') or value['metadata'].get('_continue')):
        raise ValueError('NATIVE_LIST_INCOMPLETE')
    return value['items']


class NativeKubernetesObserver:
    def __init__(self,registry,api,verifier,*,api_version):
        if api_version not in API_VERSIONS:raise ValueError('UNSUPPORTED_NATIVE_SANDBOX_VERSION')
        self.registry,self.api,self.verifier,self.api_version=registry,api,verifier,api_version

    def observe_exact(self,context):
        result=self.revalidate(context,require_running=False)
        return {**context,'podUID':result['identity']['podUID']}

    def revalidate(self,context,*,require_running):
        if (not isinstance(context,dict) or not isinstance(context.get('workerUID'),str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,63}',context['workerUID'])):
            raise ValueError('INVALID_NATIVE_SELECTOR_IDENTITY')
        task=self.registry.get(context.get('taskId'))
        state=getattr(task,'openshell',None)
        if (task is None or task.request.get('backend')!='openshell' or not state
                or any(state.get(k)!=v for k,v in context.items())):
            raise ValueError('NATIVE_OBSERVER_TASK_BINDING_MISMATCH')
        # Exact selector values are validated before reaching the API. The API
        # must return authoritative list responses, not a watch-cache guess.
        selector=NATIVE_ID+'='+context['workerUID']+','+GATEWAY+'='+self.verifier.gateway
        sandboxes=complete_items(self.api.list_sandboxes(self.verifier.namespace,self.api_version,selector))
        if len(sandboxes)!=1:raise ValueError('NATIVE_SANDBOX_NOT_UNIQUE')
        if sandboxes[0].get('apiVersion')!=self.api_version:
            raise ValueError('NATIVE_LIST_API_VERSION_MISMATCH')
        pods=complete_items(self.api.list_pods(self.verifier.namespace,NATIVE_ID+'='+context['workerUID']))
        workloads=[p for p in pods if p.get('metadata',{}).get('labels',{}).get(ROLE)=='workload']
        supervisors=[p for p in pods if p.get('metadata',{}).get('labels',{}).get(ROLE)=='supervisor']
        if len(workloads)!=1 or len(supervisors)!=1:raise ValueError('NATIVE_POD_PAIR_NOT_UNIQUE')
        result=self.verifier.verify(context,sandboxes[0],workloads[0],supervisors[0],
            expected=state.get('nativeResources'),require_running=require_running)
        # The existing Task journal is the sole durable writer. No second
        # registry, credential store or independent worker ledger is created.
        task.openshell={**task.openshell,'nativeResources':result['identity'],
                         'nativeResourceVersions':result['resourceVersions']}
        task.save()
        return result
