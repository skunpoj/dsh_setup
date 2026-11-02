import copy
import unittest
from scripts.openshell_kubernetes_identity import (NativeKubernetesIdentityVerifier,
    scope_digest,SCOPE_ANNOTATION,NATIVE_ID,ROLE,PAIR,GATEWAY,WORKSPACE)


class NativeIdentityTests(unittest.TestCase):
    def setUp(self):
        self.context={'subject':'alice','generation':'g1','taskId':'a'*32,'project':'project',
                      'bindingId':'b'*32,'workerUID':'native-1'}
        self.images=['registry/worker@sha256:'+'1'*64,'registry/supervisor@sha256:'+'2'*64]
        self.namespace='dsh-openshell-test-20261028'
        self.verifier=NativeKubernetesIdentityVerifier(namespace=self.namespace,gateway='gateway1',
            workspace='alice',worker_image=self.images[0],supervisor_image=self.images[1])
        self.sandbox={'apiVersion':'agents.x-k8s.io/v1beta1','kind':'Sandbox','metadata':{
            'namespace':self.namespace,'name':'native-workload','uid':'sandbox-uid','resourceVersion':'10',
            'labels':{'openshell.ai/sandbox-id':'native-1','openshell.ai/gateway-id':'gateway1',
                      'openshell.ai/sandbox-workspace':'alice','openshell.ai/managed-by':'openshell'}}}
        def pod(name,uid,role,container,image,controller):
            return {'apiVersion':'v1','kind':'Pod','metadata':{'namespace':self.namespace,'name':name,
                'uid':uid,'resourceVersion':'11','labels':{NATIVE_ID:'native-1',GATEWAY:'gateway1',PAIR:'native-1',ROLE:role},
                'annotations':{NATIVE_ID:'native-1',SCOPE_ANNOTATION:scope_digest(self.context)},
                'ownerReferences':[{'apiVersion':self.sandbox['apiVersion'],'kind':'Sandbox',
                                   'name':'native-workload','uid':'sandbox-uid','controller':controller}]},
                'spec':{'automountServiceAccountToken':False,'containers':[{'name':container,'image':image}]},
                'status':{'phase':'Running','containerStatuses':[{'name':container,'ready':True,
                    'imageID':'docker-pullable://'+image,'state':{'running':{'startedAt':'2026-11-02T00:00:00Z'}}}]}}
        self.workload=pod('worker-pod','worker-uid','workload','agent',self.images[0],True)
        self.supervisor=pod('os-supervisor-native-1','supervisor-uid','supervisor','supervisor',self.images[1],False)

    def verify(self,**options):return self.verifier.verify(self.context,self.sandbox,self.workload,self.supervisor,**options)

    def test_running_pair_bound_to_sandbox_and_scope(self):
        result=self.verify(require_running=True)
        self.assertTrue(result['runningImagesVerified'])
        self.assertEqual(result['identity']['podUID'],'worker-uid')
        self.assertEqual(result['identity']['supervisorPodUID'],'supervisor-uid')

    def test_pending_observation_does_not_grant_running_acceptance(self):
        self.workload['status']={'phase':'Pending'}
        self.assertFalse(self.verify()['runningImagesVerified'])
        with self.assertRaisesRegex(ValueError,'RUNNING_IMAGE'):self.verify(require_running=True)

    def test_foreign_owner_namespace_gateway_or_workspace_refuses(self):
        original=copy.deepcopy(self.sandbox)
        for field,value in [('namespace','foreign'),(GATEWAY,'foreign'),(WORKSPACE,'foreign')]:
            self.sandbox=copy.deepcopy(original)
            if field=='namespace':self.sandbox['metadata'][field]=value
            else:self.sandbox['metadata']['labels'][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.verify()

    def test_owner_reference_uid_and_controller_must_match(self):
        for pod,field,value in [(self.workload,'uid','foreign'),(self.supervisor,'controller',True)]:
            owner=pod['metadata']['ownerReferences'][0];old=owner[field];owner[field]=value
            with self.assertRaisesRegex(ValueError,'OWNER_UID'):self.verify()
            owner[field]=old

    def test_ambiguous_owners_refuse(self):
        self.workload['metadata']['ownerReferences']*=2
        with self.assertRaisesRegex(ValueError,'OWNER_AMBIGUOUS'):self.verify()

    def test_supervisor_noncontroller_owner_may_omit_controller_flag(self):
        self.supervisor['metadata']['ownerReferences'][0].pop('controller')
        self.assertEqual(self.verify()['identity']['supervisorPodUID'],'supervisor-uid')

    def test_foreign_task_or_generation_cannot_reuse_pod(self):
        for key,value in [('subject','bob'),('generation','g2'),('bindingId','c'*32),
                          ('taskId','d'*32),('project','foreign-project')]:
            old=self.context[key];self.context[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'WORKLOAD_BINDING'):self.verify()
            self.context[key]=old

    def test_replaced_workload_or_supervisor_refuses_frozen_identity(self):
        expected=self.verify()['identity']
        for pod in [self.workload,self.supervisor]:
            old=pod['metadata']['uid'];pod['metadata']['uid']='replacement'
            with self.assertRaisesRegex(ValueError,'RESOURCE_REPLACED'):self.verify(expected=expected)
            pod['metadata']['uid']=old

    def test_terminating_pod_is_not_an_active_identity(self):
        self.workload['metadata']['deletionTimestamp']='2026-11-02T00:01:00Z'
        with self.assertRaisesRegex(ValueError,'IDENTITY_UNAVAILABLE'):self.verify()

    def test_readiness_cannot_hide_wrong_image_digest(self):
        self.workload['status']['containerStatuses'][0]['imageID']='registry/worker@sha256:'+'3'*64
        with self.assertRaisesRegex(ValueError,'RUNNING_IMAGE'):self.verify(require_running=True)

    def test_tagged_or_changed_spec_image_refuses(self):
        self.workload['spec']['containers'][0]['image']='registry/worker:latest'
        with self.assertRaisesRegex(ValueError,'SPEC_IMAGE'):self.verify()

    def test_automatic_workload_serviceaccount_token_refuses(self):
        self.workload['spec']['automountServiceAccountToken']=True
        with self.assertRaisesRegex(ValueError,'TOKEN_AUTOMOUNT'):self.verify()

    def test_status_version_update_does_not_change_immutable_identity(self):
        expected=self.verify()['identity'];self.workload['metadata']['resourceVersion']='12'
        result=self.verify(expected=expected)
        self.assertEqual(result['resourceVersions']['workload'],'12')


if __name__=='__main__':unittest.main()
