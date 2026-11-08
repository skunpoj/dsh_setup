"""Synthetic snapshot checks, not a live cluster or worker qualification."""
import copy
from unittest import TestCase
from scripts.a2a_private_worker_pod import worker_pod
from scripts.a2a_worker_identity import annotate,template_hash,verify_pod,verify_terminal_worker
from scripts.a2a_worker_receipt import terminal_projection
import json


class WorkerIdentityTests(TestCase):
    def terminal(self):
        context=dict(subject='owner',stageId='a'*32,correlationId='c'*32,project='private',runtime='claude')
        receipt=dict(context,scopeUid=self.pod['metadata']['uid'],stopped=True,
            processExitVerified=True,descendantAbsenceVerified=True,pidNamespaceInode=12345,
            exitCode=0,output='synthetic private result')
        self.pod['status']['containerStatuses'][0]['state']={'terminated':dict(exitCode=0,
            finishedAt='synthetic',message=json.dumps(terminal_projection(receipt)))}
        return context,receipt

    def test_lost_stream_can_prove_stop_but_cannot_invent_the_answer(self):
        context,receipt=self.terminal()
        observed=verify_terminal_worker(self.pod,self.expected,pod_uid=self.pod['metadata']['uid'],context=context)
        self.assertTrue(observed['descendantAbsenceVerified'])
        self.assertFalse(observed['outputAvailable']);self.assertFalse(observed['guardStopped'])
        matched=verify_terminal_worker(self.pod,self.expected,pod_uid=self.pod['metadata']['uid'],
                                       context=context,stream_receipt=receipt)
        self.assertTrue(matched['outputAvailable'])

    def test_changed_output_or_foreign_owner_cannot_reuse_a_terminal_receipt(self):
        context,receipt=self.terminal();receipt['output']='different synthetic result'
        with self.assertRaisesRegex(ValueError,'RECEIPT_MISMATCH'):
            verify_terminal_worker(self.pod,self.expected,pod_uid=self.pod['metadata']['uid'],
                                   context=context,stream_receipt=receipt)
        context['subject']='foreign'
        with self.assertRaisesRegex(ValueError,'FOREIGN'):
            verify_terminal_worker(self.pod,self.expected,pod_uid=self.pod['metadata']['uid'],context=context)
    def setUp(self):
        template=worker_pod(namespace='private-test',task_id='a'*32,
            image='registry.invalid/qualified@sha256:'+'b'*64,workspace_claim='private',
            project_subpath='owner/project',credential_secret='synthetic',correlation_id='c'*32)
        self.expected=annotate(template,namespace_uid='11111111-1111-4111-8111-111111111111',operation_id='d'*32)
        self.pod=copy.deepcopy(self.expected)
        self.pod['metadata'].update(uid='22222222-2222-4222-8222-222222222222',resourceVersion='10')
        self.pod['status']=dict(phase='Running',containerStatuses=[dict(name=name,ready=True,
            restartCount=0,state={'running':{'startedAt':'synthetic'}},
            imageID='registry.invalid/qualified@sha256:'+'b'*64) for name in ('worker','model-guard')])

    def test_actual_spec_and_both_image_ids_are_required_not_readiness_alone(self):
        result=verify_pod(self.pod,self.expected,require_running=True)
        self.assertEqual(result['podUID'],self.pod['metadata']['uid'])
        for field,value in [('imageID','registry.invalid/qualified@sha256:'+'e'*64),('restartCount',1)]:
            pod=copy.deepcopy(self.pod);pod['status']['containerStatuses'][1][field]=value
            with self.assertRaisesRegex(ValueError,'IMAGE_OR_GENERATION'):
                verify_pod(pod,self.expected,require_running=True)

    def test_known_api_defaults_do_not_weaken_security_spec_check(self):
        self.pod['spec'].update(dnsPolicy='ClusterFirst',schedulerName='default-scheduler',
                                serviceAccountName='default',nodeName='approved-fixture-node')
        for container in self.pod['spec']['containers']:
            container.update(imagePullPolicy='IfNotPresent',terminationMessagePath='/dev/termination-log',
                             terminationMessagePolicy='File',tty=False)
        self.assertEqual(verify_pod(self.pod,self.expected,require_running=True)['templateSha256'],
                         template_hash(self.expected))

    def test_extra_mount_environment_or_privilege_is_not_an_api_default(self):
        for kind in ('mount','environment','privilege','hostPID','token','numeric-bool'):
            pod=copy.deepcopy(self.pod)
            if kind=='mount':pod['spec']['containers'][0]['volumeMounts'].append({'name':'guard-state','mountPath':'/other'})
            elif kind=='environment':pod['spec']['containers'][0]['env']=[{'name':'UNADMITTED','value':'synthetic'}]
            elif kind=='privilege':pod['spec']['containers'][0]['securityContext']['privileged']=True
            elif kind=='hostPID':pod['spec']['hostPID']=True
            elif kind=='numeric-bool':pod['spec']['automountServiceAccountToken']=0
            else:pod['spec']['automountServiceAccountToken']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):verify_pod(pod,self.expected)

    def test_replacement_pod_or_create_operation_cannot_reuse_an_attachment(self):
        with self.assertRaisesRegex(ValueError,'IDENTITY_CHANGED'):
            verify_pod(self.pod,self.expected,pod_uid='33333333-3333-4333-8333-333333333333')
        self.pod['metadata']['annotations']['dsh.example.com/create-operation']='e'*32
        with self.assertRaisesRegex(ValueError,'OPERATION_BINDING'):
            verify_pod(self.pod,self.expected)

    def test_injected_init_or_ephemeral_container_is_rejected(self):
        for key in ('initContainers','ephemeralContainers'):
            pod=copy.deepcopy(self.pod);pod['spec'][key]=[{'name':'unadmitted','image':'mutable:latest'}]
            with self.subTest(key=key),self.assertRaises(ValueError):verify_pod(pod,self.expected)
