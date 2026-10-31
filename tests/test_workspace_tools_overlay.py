import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workspace_tools_overlay import transform


class WorkspaceOverlayTests(unittest.TestCase):
    def setUp(self):
        self.storage={'name':'workspace','persistentVolumeClaim':{'claimName':'keep-user-data'}}
        self.spec={'template':{'spec':{'automountServiceAccountToken':False,
            'volumes':[self.storage,{'name':'platform-guide','configMap':{'name':'keep-guide'}}],
            'containers':[{'name':'dsh','image':'pinned-digest','volumeMounts':[
                {'name':'workspace','mountPath':'/workspace','subPath':'keep-user'},
                {'name':'platform-guide','mountPath':'/etc/kilo/kilo.json','subPath':'kilo.json','readOnly':True}],
                'lifecycle':{'postStart':{'exec':{'command':['python3',
                    '/opt/dsh/scripts/configure_platform_guide.py','--state','/state','--workspace','/workspace']}}}}]}}}

    def test_preserves_storage_image_and_original_input(self):
        before=copy.deepcopy(self.spec)
        result=transform(self.spec,'candidate')['template']['spec']
        self.assertEqual(self.spec,before)
        self.assertEqual(result['volumes'][0],self.storage)
        worker=result['containers'][0]
        self.assertEqual(worker['image'],'pinned-digest')
        self.assertEqual(worker['volumeMounts'][0],before['template']['spec']['containers'][0]['volumeMounts'][0])
        self.assertNotIn('postStart',worker['lifecycle'])
        items=result['volumes'][-1]['configMap']['items']
        self.assertEqual(next(v['mode']for v in items if v['key']=='kilo-managed.py'),0o555)
        self.assertTrue(all(m['readOnly']for m in worker['volumeMounts']if m['name']=='workspace-tools'))

    def test_foreign_startup_hook_and_policy_mount_refused(self):
        worker=self.spec['template']['spec']['containers'][0]
        worker['lifecycle']['postStart']={'exec':{'command':['unrelated']}}
        with self.assertRaises(ValueError):transform(self.spec,'candidate')
        worker['lifecycle']={}
        worker['volumeMounts'][-1]['name']='unrelated-policy'
        with self.assertRaises(ValueError):transform(self.spec,'candidate')

    def test_duplicate_and_service_account_refused(self):
        result=transform(self.spec,'candidate')
        with self.assertRaises(ValueError):transform(result,'another')
        self.spec['template']['spec']['automountServiceAccountToken']=True
        with self.assertRaises(ValueError):transform(self.spec,'candidate')


if __name__ == '__main__':unittest.main()
