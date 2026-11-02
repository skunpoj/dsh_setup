"""Verify native OpenShell resource snapshots without credentials or mutations.

Based on NVIDIA/OpenShell bdb956f2's Kubernetes identity model. This is one
component of the protected supervisor, not its assignment/stop implementation.
An observation of Pending resources never grants dispatch permission.
"""
import hashlib
import json
import re

UPSTREAM_COMMIT='bdb956f2cd65a635f1294fccf1d138d263bf650f'
SCOPE_FIELDS={'subject','generation','taskId','project','bindingId'}
SCOPE_ANNOTATION='dsh.example.com/task-scope-sha256'
NATIVE_ID='openshell.ai/sandbox-id'
ROLE='openshell.ai/boundary-role'
PAIR='openshell.ai/boundary-pair'
GATEWAY='openshell.ai/gateway-id'
WORKSPACE='openshell.ai/sandbox-workspace'
API_VERSIONS={'agents.x-k8s.io/v1alpha1','agents.x-k8s.io/v1beta1'}


def scope_digest(context):
    if not isinstance(context,dict) or set(context)!=SCOPE_FIELDS|{'workerUID'}:
        raise ValueError('INVALID_NATIVE_CONTEXT')
    if any(not isinstance(v,str) or not v or len(v)>1024 for v in context.values()):
        raise ValueError('INVALID_NATIVE_CONTEXT')
    return hashlib.sha256(json.dumps({k:context[k] for k in sorted(SCOPE_FIELDS)},
        sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def _metadata(value,kind,namespace):
    if not isinstance(value,dict) or value.get('kind')!=kind:
        raise ValueError('INVALID_NATIVE_RESOURCE')
    meta=value.get('metadata',{})
    if (meta.get('namespace')!=namespace or meta.get('deletionTimestamp')
            or any(not isinstance(meta.get(k),str) or not meta[k] for k in ['name','uid','resourceVersion'])):
        raise ValueError('NATIVE_RESOURCE_IDENTITY_UNAVAILABLE')
    return meta


def _owner(meta,sandbox,controller):
    owners=[owner for owner in meta.get('ownerReferences',[]) if owner.get('kind')=='Sandbox']
    if len(owners)!=1:
        raise ValueError('NATIVE_OWNER_AMBIGUOUS')
    owner=owners[0]
    if (owner.get('apiVersion')!=sandbox['apiVersion']
            or owner.get('name')!=sandbox['metadata']['name']
            or owner.get('uid')!=sandbox['metadata']['uid']
            or (controller and owner.get('controller') is not True)
            or (not controller and owner.get('controller') is True)):
        raise ValueError('NATIVE_OWNER_UID_MISMATCH')


def _image(pod,name,image,require_running):
    containers=[c for c in pod.get('spec',{}).get('containers',[]) if c.get('name')==name]
    if len(containers)!=1 or containers[0].get('image')!=image:
        raise ValueError('NATIVE_SPEC_IMAGE_MISMATCH')
    if not require_running:return
    statuses=[c for c in pod.get('status',{}).get('containerStatuses',[]) if c.get('name')==name]
    if (pod.get('status',{}).get('phase')!='Running' or len(statuses)!=1
            or statuses[0].get('ready') is not True
            or not statuses[0].get('state',{}).get('running')
            or not str(statuses[0].get('imageID','')).endswith(image[image.rfind('@')+1:])):
        raise ValueError('NATIVE_RUNNING_IMAGE_UNVERIFIED')


class NativeKubernetesIdentityVerifier:
    def __init__(self,*,namespace,gateway,workspace,worker_image,supervisor_image):
        if namespace not in {'dsh-openshell-test-20261028','dsh-openshell'}:
            raise ValueError('UNADMITTED_NATIVE_NAMESPACE')
        for image in [worker_image,supervisor_image]:
            if not isinstance(image,str) or not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}',image):
                raise ValueError('NATIVE_IMAGE_PIN_REQUIRED')
        if not all(isinstance(v,str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,62}',v) for v in [gateway,workspace]):
            raise ValueError('INVALID_NATIVE_OWNER_CONFIG')
        self.namespace,self.gateway,self.workspace=namespace,gateway,workspace
        self.worker_image,self.supervisor_image=worker_image,supervisor_image

    def verify(self,context,sandbox,workload,supervisor,*,expected=None,require_running=False):
        digest=scope_digest(context)
        if sandbox.get('apiVersion') not in API_VERSIONS:
            raise ValueError('UNSUPPORTED_NATIVE_SANDBOX_VERSION')
        native=_metadata(sandbox,'Sandbox',self.namespace)
        labels=native.get('labels',{})
        if (labels.get(NATIVE_ID)!=context['workerUID'] or labels.get(GATEWAY)!=self.gateway
                or labels.get(WORKSPACE)!=self.workspace or labels.get('openshell.ai/managed-by')!='openshell'):
            raise ValueError('NATIVE_SANDBOX_OWNER_MISMATCH')
        worker=_metadata(workload,'Pod',self.namespace)
        control=_metadata(supervisor,'Pod',self.namespace)
        _owner(worker,sandbox,True);_owner(control,sandbox,False)
        if (worker.get('annotations',{}).get(NATIVE_ID)!=context['workerUID']
                or worker.get('annotations',{}).get(SCOPE_ANNOTATION)!=digest):
            raise ValueError('NATIVE_WORKLOAD_BINDING_MISMATCH')
        if workload.get('spec',{}).get('automountServiceAccountToken') is not False:
            raise ValueError('NATIVE_WORKLOAD_TOKEN_AUTOMOUNT_NOT_DISABLED')
        for meta,role in [(worker,'workload'),(control,'supervisor')]:
            role_labels=meta.get('labels',{})
            if (role_labels.get(ROLE)!=role or role_labels.get(PAIR)!=context['workerUID'].lower()
                    or role_labels.get(NATIVE_ID)!=context['workerUID']):
                raise ValueError('NATIVE_PAIR_BINDING_MISMATCH')
        if (control.get('labels',{}).get(GATEWAY)!=self.gateway
                or control.get('annotations',{}).get(NATIVE_ID)!=context['workerUID']
                or control['name']!='os-supervisor-'+context['workerUID'].lower()):
            raise ValueError('NATIVE_SUPERVISOR_BINDING_MISMATCH')
        _image(workload,'agent',self.worker_image,require_running)
        _image(supervisor,'supervisor',self.supervisor_image,require_running)
        identity={**context,'namespace':self.namespace,'sandboxName':native['name'],
                  'sandboxUID':native['uid'],'sandboxAPIVersion':sandbox['apiVersion'],
                  'podName':worker['name'],'podUID':worker['uid'],
                  'supervisorPodName':control['name'],'supervisorPodUID':control['uid'],
                  'scopeSHA256':digest}
        if expected is not None and identity!=expected:
            raise ValueError('NATIVE_RESOURCE_REPLACED')
        # Resource versions are fresh observations, separate from immutable
        # identity so status-only updates cannot silently change a binding.
        return {'identity':identity,'resourceVersions':{'sandbox':native['resourceVersion'],
                'workload':worker['resourceVersion'],'supervisor':control['resourceVersion']},
                'runningImagesVerified':require_running}
