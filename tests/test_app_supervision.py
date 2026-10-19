import copy,importlib.util,unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('services',Path(__file__).parents[1]/'scripts/deploy_app_supervision.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Manifest(unittest.TestCase):
    def base(self):
        return {'spec':{'template':{'spec':{'containers':[{'name':'dsh','image':'registry.example.internal/runtime@sha256:'+'a'*64,'env':[{'name':'DEEPSEEK_API_KEY','value':'synthetic-private-key'},{'name':'DSH_ENVIRONMENT','value':'secure'},{'name':'DSH_TRUSTED_HOST','value':'dsh.example.internal'}],'volumeMounts':[{'name':'workspace','mountPath':'/workspace','subPath':'users/alice'},{'name':'mask','mountPath':'/workspace/private','readOnly':True},{'name':'state','mountPath':'/state','subPath':'alice/state'},{'name':'tokens','mountPath':'/runtime-tokens'}]}],'volumes':[]}}}}
    def test_preserves_main_and_excludes_credentials(self):
        old=self.base();new=module.sidecar(old,'source','service-control','identity');pod=new['spec']['template']['spec'];side=pod['containers'][1]
        self.assertEqual(pod['containers'][0],old['spec']['template']['spec']['containers'][0])
        self.assertFalse(pod['automountServiceAccountToken']);self.assertTrue(side['securityContext']['readOnlyRootFilesystem'])
        self.assertFalse(any(e['name']=='DEEPSEEK_API_KEY' for e in side['env']))
        paths={m['mountPath']:m for m in side['volumeMounts']};self.assertNotIn('/runtime-tokens',paths);self.assertNotIn('/state',paths)
        self.assertTrue(paths['/service-control']['readOnly']);self.assertEqual(paths['/service-status']['name'],'app-service-status');self.assertEqual(paths['/state/jupyter']['subPath'],'alice/state/jupyter');self.assertTrue(paths['/workspace/private']['readOnly'])
    def test_gateway_reads_separate_status_claim(self):
        spec={'template':{'spec':{'containers':[{'env':[],'volumeMounts':[]}],'volumes':[]}}};result=module.gateway_control_spec(spec,'control',['alice-key']);pod=result['template']['spec'];mount=next(m for m in pod['containers'][0]['volumeMounts']if m['name']=='app-status-alice-key');self.assertTrue(mount['readOnly']);self.assertEqual(pod['volumes'][1]['persistentVolumeClaim']['claimName'],'dsh-app-status-alice-key')
    def test_no_shared_pid_namespace(self):
        old=self.base();old['spec']['template']['spec']['shareProcessNamespace']=True
        with self.assertRaises(ValueError):module.sidecar(old,'source','service-control','identity')
    def test_keys_bind_runtime_and_environment(self):
        self.assertNotEqual(module.key('alice.example.internal','off'),module.key('bob.example.internal','off'))
        self.assertNotEqual(module.key('alice.example.internal','off'),module.key('alice.example.internal','on'))


if __name__=='__main__':unittest.main()
