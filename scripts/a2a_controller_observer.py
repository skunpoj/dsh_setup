"""Named read-only identity chain for the protected Test Task controller.

Attests placement/immutable image only, never runtime acceptance. No default
client, token discovery, namespace listing, mutation or qualification flag.
"""
import re
from scripts.official_sdk_deployment_observer import exact_running_digest,ENVIRONMENT,ROLE


class ProtectedTaskControllerObserver:
    def __init__(self,*,read_resource,executing_identity,namespace,namespace_uid,
                 pod_name,pod_uid,replicaset_name,replicaset_uid,deployment_uid,image_digest,node_name):
        if not callable(read_resource) or not callable(executing_identity):
            raise ValueError('PROTECTED_CONTROLLER_OBSERVER_DEPENDENCIES_REQUIRED')
        if not re.fullmatch(r'dsh-a2a-[a-z0-9][a-z0-9-]{0,54}',str(namespace)):
            raise ValueError('DEDICATED_A2A_TEST_NAMESPACE_REQUIRED')
        for value in (pod_name,replicaset_name,node_name):
            if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}',value):
                raise ValueError('EXACT_CONTROLLER_RESOURCE_NAME_REQUIRED')
        for value in (namespace_uid,pod_uid,replicaset_uid,deployment_uid):
            if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value):
                raise ValueError('EXACT_CONTROLLER_RESOURCE_UID_REQUIRED')
        if not isinstance(image_digest,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',image_digest):
            raise ValueError('IMMUTABLE_CONTROLLER_IMAGE_REQUIRED')
        self.read,self.identity=read_resource,executing_identity
        self.namespace,self.namespace_uid=namespace,namespace_uid
        self.pod_name,self.pod_uid=pod_name,pod_uid
        self.rs_name,self.rs_uid=replicaset_name,replicaset_uid
        self.deployment_uid,self.digest,self.node=deployment_uid,image_digest,node_name

    def _self(self):
        expected=dict(namespace=self.namespace,namespaceUID=self.namespace_uid,
                      podUID=self.pod_uid,container='controller')
        if self.identity()!=expected:raise ValueError('FOREIGN_EXECUTING_TASK_CONTROLLER')

    def _resource(self,kind,version,name,uid):
        value=self.read(kind,version,None if kind=='Namespace' else self.namespace,name)
        meta=value.get('metadata',{}) if isinstance(value,dict) else {}
        if (not isinstance(value,dict) or value.get('kind')!=kind or value.get('apiVersion')!=version
                or meta.get('name')!=name or meta.get('uid')!=uid or meta.get('deletionTimestamp')
                or not isinstance(meta.get('resourceVersion'),str) or not meta['resourceVersion']
                or (kind!='Namespace' and meta.get('namespace')!=self.namespace)):
            raise ValueError('TASK_CONTROLLER_RESOURCE_IDENTITY_CHANGED')
        labels=meta.get('labels',{})
        if labels.get(ENVIRONMENT)!='test' or labels.get(ROLE)!='qualification':
            raise ValueError('TASK_CONTROLLER_TEST_CLASSIFICATION_REQUIRED')
        return value

    @staticmethod
    def _owner(value,kind,name,uid):
        owners=value['metadata'].get('ownerReferences',[])
        controllers=[row for row in owners if row.get('controller') is True]
        if (len(controllers)!=1 or any(controllers[0].get(k)!=v for k,v in
                dict(kind=kind,name=name,uid=uid,apiVersion='apps/v1').items())):
            raise ValueError('TASK_CONTROLLER_OWNER_CHAIN_CHANGED')

    def _profile(self,spec):
        containers=spec.get('containers',[])
        if (len(containers)!=1 or containers[0].get('name')!='controller'
                or spec.get('serviceAccountName')!='dsh-agent-task-controller'
                or spec.get('hostPID',False) or spec.get('hostNetwork',False)
                or spec.get('hostIPC',False) or spec.get('shareProcessNamespace',False)
                or spec.get('initContainers') or spec.get('ephemeralContainers')):
            raise ValueError('DEDICATED_PROTECTED_CONTROLLER_PROFILE_REQUIRED')
        image=containers[0].get('image')
        if not isinstance(image,str) or not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}',image) or not image.endswith('@'+self.digest):
            raise ValueError('TASK_CONTROLLER_IMAGE_SPEC_CHANGED')

    def __call__(self):
        self._self()
        self._resource('Namespace','v1',self.namespace,self.namespace_uid)
        deployment=self._resource('Deployment','apps/v1','dsh-agent-task-controller',self.deployment_uid)
        replicas=deployment.get('spec',{}).get('replicas')
        if type(replicas) is not int or replicas!=1:
            raise ValueError('SINGLE_TASK_WRITER_REPLICA_REQUIRED')
        self._profile(deployment.get('spec',{}).get('template',{}).get('spec',{}))
        rs=self._resource('ReplicaSet','apps/v1',self.rs_name,self.rs_uid)
        self._owner(rs,'Deployment','dsh-agent-task-controller',self.deployment_uid)
        self._profile(rs.get('spec',{}).get('template',{}).get('spec',{}))
        pod=self._resource('Pod','v1',self.pod_name,self.pod_uid)
        self._owner(pod,'ReplicaSet',self.rs_name,self.rs_uid)
        self._profile(pod.get('spec',{}))
        if pod.get('spec',{}).get('nodeName')!=self.node:
            raise ValueError('TASK_CONTROLLER_NODE_CHANGED')
        statuses=pod.get('status',{}).get('containerStatuses',[])
        if len(statuses)!=1:raise ValueError('TASK_CONTROLLER_STATUS_SET_CHANGED')
        status=statuses[0]
        if (pod.get('status',{}).get('phase')!='Running' or status.get('name')!='controller'
                or status.get('ready') is not True or not status.get('state',{}).get('running')
                or type(status.get('restartCount')) is not int or status['restartCount']!=0
                or exact_running_digest(status.get('imageID'))!=self.digest):
            raise ValueError('TASK_CONTROLLER_RUNNING_IDENTITY_UNVERIFIED')
        self._self()
        return dict(namespace=self.namespace,namespaceUID=self.namespace_uid,podUID=self.pod_uid,
            workloadUID=self.deployment_uid,environment='test',workloadRole='qualification')
