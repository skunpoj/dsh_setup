import copy
from unittest import TestCase
from scripts.a2a_sdk_worker_pod import sdk_worker_pod,PACKAGE
from scripts.a2a_worker_identity import annotate,verify_pod


class SDKWorkerPodTests(TestCase):
    def pod(self):
        return sdk_worker_pod(namespace='dsh-a2a-qualified',task_id='a'*32,
            image='registry.invalid/runtime@sha256:'+'b'*64,workspace_claim='private',
            project_subpath='owner/project',credential_secret='synthetic',correlation_id='c'*32,
            package_admission_sha256='d'*64)
    def test_exact_sdk_entry_and_existing_private_mount_and_guard_boundaries(self):
        pod=self.pod();worker,guard=pod['spec']['containers']
        self.assertEqual(worker['command'],['/usr/local/bin/python3','-I','-S','/opt/dsh/scripts/a2a_sdk_worker.py'])
        self.assertFalse(pod['spec']['automountServiceAccountToken'])
        self.assertFalse(pod['spec']['shareProcessNamespace'])
        self.assertNotIn('task-model-credential',{m['name'] for m in worker['volumeMounts']})
        self.assertIn('task-model-credential',{m['name'] for m in guard['volumeMounts']})
        self.assertTrue(worker['volumeMounts'][0]['readOnly'])
        self.assertTrue(guard['stdinOnce'])
    def test_package_binding_removal_or_change_cannot_reuse_exact_pod_identity(self):
        expected=annotate(self.pod(),namespace_uid='11111111-1111-4111-8111-111111111111',operation_id='e'*32)
        actual=copy.deepcopy(expected)
        actual['metadata'].update(uid='22222222-2222-4222-8222-222222222222',resourceVersion='1')
        verify_pod(actual,expected)
        for value in (None,'f'*64):
            changed=copy.deepcopy(actual)
            if value is None:del changed['metadata']['annotations'][PACKAGE]
            else:changed['metadata']['annotations'][PACKAGE]=value
            with self.assertRaisesRegex(ValueError,'ANNOTATION_CHANGED'):verify_pod(changed,expected)
    def test_missing_package_hash_refuses_before_any_operation(self):
        with self.assertRaisesRegex(ValueError,'PACKAGE_ADMISSION'):
            sdk_worker_pod(package_admission_sha256='0'*64)
