"""Protected controller named-resource identity, synthetic reads only."""
import copy
from unittest import TestCase
from scripts.a2a_controller_observer import ProtectedTaskControllerObserver
from scripts.official_sdk_deployment_observer import ENVIRONMENT,ROLE


class ControllerObserverTests(TestCase):
    def setUp(self):
        self.ns='dsh-a2a-qual';self.digest='sha256:'+'a'*64
        self.uids=[str(n)*8+'-'+str(n)*4+'-'+str(n)*4+'-'+str(n)*4+'-'+str(n)*12 for n in range(1,5)]
        self.resources={};self.calls=[]
        def resource(kind,version,name,uid):
            value=dict(kind=kind,apiVersion=version,metadata=dict(name=name,uid=uid,
                resourceVersion='1',labels={ENVIRONMENT:'test',ROLE:'qualification'}))
            if kind!='Namespace':value['metadata']['namespace']=self.ns
            self.resources[kind]=value;return value
        resource('Namespace','v1',self.ns,self.uids[0])
        profile=dict(serviceAccountName='dsh-agent-task-controller',containers=[dict(
            name='controller',image='registry.invalid/controller@'+self.digest)])
        deployment=resource('Deployment','apps/v1','dsh-agent-task-controller',self.uids[3])
        deployment['spec']=dict(replicas=1,template=dict(spec=copy.deepcopy(profile)))
        rs=resource('ReplicaSet','apps/v1','controller-rs',self.uids[2])
        rs['metadata']['ownerReferences']=[dict(kind='Deployment',apiVersion='apps/v1',
            name='dsh-agent-task-controller',uid=self.uids[3],controller=True)]
        rs['spec']=dict(template=dict(spec=copy.deepcopy(profile)))
        pod=resource('Pod','v1','controller-pod',self.uids[1])
        pod['metadata']['ownerReferences']=[dict(kind='ReplicaSet',apiVersion='apps/v1',
            name='controller-rs',uid=self.uids[2],controller=True)]
        pod['spec']={**copy.deepcopy(profile),'nodeName':'test-node'}
        pod['status']=dict(phase='Running',containerStatuses=[dict(name='controller',ready=True,
            restartCount=0,state={'running':{'startedAt':'synthetic'}},imageID='containerd://'+self.digest)])
        self.identity=dict(namespace=self.ns,namespaceUID=self.uids[0],podUID=self.uids[1],container='controller')
        def read(*args):self.calls.append(args);return copy.deepcopy(self.resources[args[0]])
        self.observer=ProtectedTaskControllerObserver(read_resource=read,executing_identity=lambda:dict(self.identity),
            namespace=self.ns,namespace_uid=self.uids[0],pod_name='controller-pod',pod_uid=self.uids[1],
            replicaset_name='controller-rs',replicaset_uid=self.uids[2],deployment_uid=self.uids[3],
            image_digest=self.digest,node_name='test-node')

    def test_exact_named_chain_yields_only_placement_binding(self):
        self.assertEqual(self.calls,[])
        binding=self.observer()
        self.assertEqual(binding['workloadUID'],self.uids[3])
        self.assertEqual([row[0] for row in self.calls],['Namespace','Deployment','ReplicaSet','Pod'])
        self.assertNotIn('qualified',binding);self.assertNotIn('liveAccepted',binding)

    def test_replaced_namespace_owner_or_executing_identity_refuses(self):
        for kind in self.resources:
            with self.subTest(kind=kind):
                old=self.resources[kind]['metadata']['uid'];self.resources[kind]['metadata']['uid']=self.uids[0]
                if old==self.uids[0]:self.resources[kind]['metadata']['uid']=self.uids[1]
                with self.assertRaisesRegex(ValueError,'IDENTITY_CHANGED'):self.observer()
                self.resources[kind]['metadata']['uid']=old
        self.resources['Pod']['metadata']['ownerReferences'][0]['uid']=self.uids[3]
        with self.assertRaisesRegex(ValueError,'OWNER_CHAIN_CHANGED'):self.observer()
        self.identity['container']='user-runtime'
        with self.assertRaisesRegex(ValueError,'FOREIGN_EXECUTING'):self.observer()

    def test_production_classification_sidecar_host_scope_and_extra_replica_refuse(self):
        self.resources['Namespace']['metadata']['labels'][ENVIRONMENT]='production'
        with self.assertRaisesRegex(ValueError,'CLASSIFICATION'):self.observer()
        self.resources['Namespace']['metadata']['labels'][ENVIRONMENT]='test'
        for replicas in (0,2,True):
            self.resources['Deployment']['spec']['replicas']=replicas
            with self.assertRaisesRegex(ValueError,'SINGLE_TASK_WRITER'):self.observer()
        self.resources['Deployment']['spec']['replicas']=1
        self.resources['Pod']['spec']['hostPID']=True
        with self.assertRaisesRegex(ValueError,'PROFILE'):self.observer()
        self.resources['Pod']['spec'].pop('hostPID')
        self.resources['Pod']['spec']['containers'].append(dict(name='sidecar',image='foreign'))
        with self.assertRaisesRegex(ValueError,'PROFILE'):self.observer()

    def test_running_image_restart_node_and_server_body_are_verified(self):
        pod=self.resources['Pod'];status=pod['status']['containerStatuses'][0]
        for field,value in [('restartCount',1),('restartCount',False),('ready',False),
                            ('imageID','containerd://sha256:'+'f'*64)]:
            old=status[field];status[field]=value
            with self.assertRaises(ValueError):self.observer()
            status[field]=old
        pod['spec']['nodeName']='different-node'
        with self.assertRaisesRegex(ValueError,'NODE_CHANGED'):self.observer()
