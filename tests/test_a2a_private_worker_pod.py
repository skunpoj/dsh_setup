from unittest import TestCase
from scripts.a2a_private_worker_pod import worker_pod


class WorkerPodTests(TestCase):
    def options(self):
        return dict(namespace='test-synthetic',task_id='a'*32,
            image='registry.invalid/runtime@sha256:'+'b'*64,
            workspace_claim='private-test',project_subpath='owner/project',
            credential_secret='task-scoped-synthetic',correlation_id='c'*32)

    def test_payload_has_neither_model_credential_nor_guard_ledger_mount(self):
        pod=worker_pod(**self.options());spec=pod['spec']
        worker,guard=spec['containers']
        self.assertFalse(spec['automountServiceAccountToken'])
        self.assertFalse(spec['shareProcessNamespace']);self.assertFalse(spec['hostPID'])
        mounts={v['name'] for v in worker['volumeMounts']}
        self.assertNotIn('task-model-credential',mounts);self.assertNotIn('guard-state',mounts)
        self.assertIn('task-model-credential',{v['name'] for v in guard['volumeMounts']})
        self.assertEqual(spec['restartPolicy'],'Never')
        self.assertTrue(worker['stdinOnce']);self.assertTrue(worker['securityContext']['readOnlyRootFilesystem'])
        self.assertEqual(worker['securityContext']['capabilities']['add'],['KILL','SETGID','SETUID'])

    def test_only_exact_private_project_mount_and_explicit_write_policy(self):
        pod=worker_pod(**self.options())
        mount=pod['spec']['containers'][0]['volumeMounts'][0]
        self.assertEqual(mount['subPath'],'owner/project');self.assertTrue(mount['readOnly'])
        pod=worker_pod(**self.options(),writes=True)
        self.assertFalse(pod['spec']['containers'][0]['volumeMounts'][0]['readOnly'])
        for subpath in ('../other','/other','owner/../other','owner//other'):
            options=self.options();options['project_subpath']=subpath
            with self.assertRaisesRegex(ValueError,'SUBPATH'):worker_pod(**options)

    def test_mutable_images_and_host_path_like_names_are_refused(self):
        for key,value in (('image','registry.invalid/runtime:latest'),
                          ('workspace_claim','../../host'),('namespace','llm/other')):
            options=self.options();options[key]=value
            with self.assertRaises(ValueError):worker_pod(**options)
