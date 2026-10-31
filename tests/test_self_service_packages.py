import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'container')]
import package_controller as controller
import package_task as task


class PackageBoundaryTests(unittest.TestCase):
    def request(self):
        return {'id': 'a' * 32, 'owner': 'alice', 'environment': 'analysis', 'specs': ['six==1.17.0']}

    def test_pins_paths_and_identity_not_commands(self):
        for spec in ['six', '--index-url=x', 'https://example.com/a.whl', 'six==1;id', '../x==1', 'six @ https://example.com']:
            request = self.request(); request['specs'] = [spec]
            with self.assertRaises(ValueError): task.validate_request(request)
        for env in ['../alice', '/tmp/env', 'analysis;id', 'A', '']:
            request = self.request(); request['environment'] = env
            with self.assertRaises(ValueError): task.validate_request(request)
        self.assertEqual(task.validate_request(self.request())['owner'], 'alice')

    def test_wheel_traversal_and_startup_hooks_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            for dangerous in ['../outside.py', '/root/x.py', 'startup.pth']:
                path = Path(folder) / 'fixture.whl'
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('fixture-1.dist-info/METADATA', 'Name: fixture\nVersion: 1\n')
                    archive.writestr(dangerous, 'bad')
                with self.assertRaises(ValueError): task.wheel_metadata(path)

    @unittest.skipUnless(hasattr(__import__('os'), 'O_NOFOLLOW'), 'Executed on Linux in live qualification')
    def test_hash_changed_or_symlink_artifact_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source'; source.mkdir(); wheel = source / 'x.whl'; wheel.write_bytes(b'changed')
            manifest = {'wheels': [{'filename': 'x.whl', 'sha256': hashlib.sha256(b'original').hexdigest(), 'bytes': 7}]}
            with self.assertRaises(ValueError): task.stage_verified(manifest, source, root / 'dest1')
            wheel.unlink(); wheel.symlink_to(root / 'other')
            with self.assertRaises(OSError): task.stage_verified(manifest, source, root / 'dest2')

    def test_online_job_cannot_mount_offline_data(self):
        config = {'namespace': 'llm', 'sourceConfigMap': 'source', 'queuePVC': 'queue', 'runtimeImage': 'image@sha256:' + 'a'*64}
        owner = {'secure': 'alice-secure.llm.svc.cluster.local', 'internet': 'alice-internet.llm.svc.cluster.local'}
        document = controller.job(config, self.request(), owner, 'download')
        pod = document['spec']['template']['spec']; main = pod['containers'][0]
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertFalse(any(m['mountPath'] in ['/workspace', '/notebook', '/state'] for m in main['volumeMounts']))
        self.assertEqual(document['spec']['template']['metadata']['labels'], {'app': 'dsh-package-download'})

    def test_install_mounts_only_owner_workspace_and_notebook_subdir(self):
        config = {'namespace': 'llm', 'sourceConfigMap': 'source', 'queuePVC': 'queue', 'runtimeImage': 'image@sha256:' + 'a'*64}
        owner = {'secure': 'alice-secure.llm.svc.cluster.local', 'internet': 'alice-internet.llm.svc.cluster.local'}
        pod = {'volumes': [{'name': 'workspace', 'persistentVolumeClaim': {'claimName': 'private-alice'}}, {'name': 'state', 'persistentVolumeClaim': {'claimName': 'private-state'}}]}
        main = {'volumeMounts': [{'name': 'workspace', 'mountPath': '/workspace', 'subPath': 'alice/secure'}, {'name': 'state', 'mountPath': '/state'}]}
        document = controller.job(config, self.request(), owner, 'install', pod, main)
        result = document['spec']['template']['spec']; mounts = result['containers'][0]['volumeMounts']
        self.assertEqual(next(m['subPath'] for m in mounts if m['mountPath'] == '/workspace'), 'alice/secure')
        self.assertEqual(next(m['subPath'] for m in mounts if m['mountPath'] == '/notebook'), 'jupyter')
        self.assertTrue(next(m['readOnly'] for m in mounts if m['mountPath'] == '/artifacts'))
        self.assertNotIn('/state', [m['mountPath'] for m in mounts])
        self.assertNotIn('fsGroup', result['securityContext'])
        self.assertEqual(document['spec']['template']['metadata']['labels'], {'app': 'dsh-package-install'})

    @unittest.skipUnless(hasattr(__import__('os'), 'O_NOFOLLOW'), 'Executed on Linux in live qualification')
    def test_lexically_earlier_queue_cannot_bypass_two_active_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); jobs = root / 'jobs'; jobs.mkdir()
            ids = ['0'*32, 'b'*32, 'c'*32]
            for rid, state in zip(ids, ['queued', 'downloading', 'downloading']):
                p = jobs / rid; p.mkdir(); request = self.request(); request['id'] = rid
                (p/'request.json').write_text(json.dumps(request)); (p/'public.json').write_text(json.dumps({'state': state}))
            config = {'namespace': 'llm', 'sourceConfigMap': 'source', 'queuePVC': 'queue', 'runtimeImage': 'image@sha256:'+'a'*64, 'storageClass':'test'}
            owner = {'enabled':True, 'internetAllowed':True, 'secure':'alice-secure.llm.svc.cluster.local', 'internet':'alice-internet.llm.svc.cluster.local'}
            called=[]
            def ensure(kube, kind, name, body):
                called.append(name); return {'status':{}}
            with patch.object(controller, 'authorization', return_value=owner), patch.object(controller, 'deployment', return_value=({}, {})), patch.object(controller, 'ensure', side_effect=ensure):
                controller.tick(root, object(), config)
            self.assertFalse(any(name.startswith('dsh-pkg-'+ids[0][:20]) for name in called))
            self.assertEqual(json.loads((jobs/ids[0]/'public.json').read_text())['state'],'queued')


if __name__ == '__main__': unittest.main()
