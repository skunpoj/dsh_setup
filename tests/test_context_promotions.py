import copy
import importlib.util
from pathlib import Path
import unittest
import yaml
import tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class RuntimePromotion(unittest.TestCase):
    def test_profile_backup_survives_repeat_start_and_exact_restore(self):
        m=load('promote_1m_runtimes')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profiles/web/cordis.patch.yml';profile.parent.mkdir(parents=True);profile.write_text('original-profile')
            c={'image':'old','volumeMounts':[{'name':'state','mountPath':'/state'}]}
            backup=m.profile_init(c,'same')['command'][2].replace('/state',root.as_posix())
            exec(backup,{})
            profile.write_text('new-profile');exec(backup,{})
            self.assertEqual(profile.read_text(),'new-profile')
            self.assertEqual((root/'.context-upgrade-backup/same/profile.yml').read_text(),'original-profile')
            restore=m.profile_init(c,'same',True)['command'][2].replace('/state',root.as_posix());exec(restore,{})
            self.assertEqual(profile.read_text(),'original-profile')

    def test_proxy_preserves_secrets_and_unrelated_route(self):
        m=load('promote_1m_proxy')
        original={'spec':{'replicas':1,'template':{'metadata':{},'spec':{
            'containers':[{'image':'old','env':[{'name':'MASTER_KEY','valueFrom':{'secretKeyRef':{'name':'existing','key':'key'}}}]}],
            'volumes':[{'name':'config','configMap':{'name':'original'}}]}}}}
        routes=[{'model_name':n,'litellm_params':{'model':'openai/deepseek-v4.1-flash','api_base':'http://internal/v1'}} for n in ['deepseek-flash','deepseek-v4.1-flash']]
        other={'model_name':'unrelated','litellm_params':{'model':'other','api_base':'http://other'}}
        data={'config.yaml':yaml.safe_dump({'model_list':routes+[other],'litellm_settings':{'callbacks':['old']}})}
        before=copy.deepcopy(original);v,cm,digest=m.candidate(original,data,'qualified@sha256:abc')
        self.assertEqual(original,before);self.assertTrue(cm['immutable'])
        self.assertEqual(yaml.safe_load(cm['data']['config.yaml'])['model_list'][-1],other)
        self.assertEqual(v['template']['spec']['containers'][0]['env'][0],before['spec']['template']['spec']['containers'][0]['env'][0])
        side=v['template']['spec']['containers'][1]
        self.assertIn('127.0.0.1',side['command'])
        self.assertFalse(any(e['name']=='DSH_CAPTURE_SYNTHETIC_ENVELOPE' for e in side['env']))
        self.assertFalse(v['template']['spec']['automountServiceAccountToken'])

    def test_preserves_mounts_and_restores_profile_before_old_runtime(self):
        m=load('promote_1m_runtimes')
        original={'spec':{'replicas':1,'strategy':{'type':'Recreate'},'template':{'metadata':{},'spec':{
            'containers':[{'image':'old@sha256:abc','env':[{'name':'PRIVATE_KEY','valueFrom':{'secretKeyRef':{'name':'existing','key':'key'}}}],
                'volumeMounts':[{'name':'state','mountPath':'/state'},{'name':'cifs','mountPath':'/workspace'}]}],
            'volumes':[{'name':'state','persistentVolumeClaim':{'claimName':'private-state'}},{'name':'cifs','persistentVolumeClaim':{'claimName':'original-share'}}]}}}}
        before=copy.deepcopy(original);v=m.candidate(original,'test')
        self.assertEqual(original,before)
        p=v['template']['spec'];self.assertEqual(p['volumes'],before['spec']['template']['spec']['volumes'])
        self.assertEqual(p['containers'][0]['env'][0],before['spec']['template']['spec']['containers'][0]['env'][0])
        init=p['initContainers'][0];self.assertEqual(init['image'],'old@sha256:abc')
        self.assertEqual(len(init['volumeMounts']),1)
        self.assertIn('exist_ok=False',init['command'][2])
        restored=m.profile_init(before['spec']['template']['spec']['containers'][0],'test',True)
        self.assertIn('hashlib.sha256(original)',restored['command'][2]);self.assertIn('os.replace',restored['command'][2])

    def test_transport_overlay_retains_mounts_and_restart_safe_rollback(self):
        m=load('rollout_managed_transport')
        original={'spec':{'replicas':1,'strategy':{'type':'Recreate'},'template':{
            'metadata':{'annotations':{'dsh.bot.or.th/context-rollout':'retained-tag'}},'spec':{
            'containers':[{'image':'qualified-image','env':[{'name':'PRIVATE','valueFrom':{'secretKeyRef':{'name':'existing','key':'key'}}}],
                'volumeMounts':[{'name':'state','mountPath':'/state'},{'name':'cifs','mountPath':'/workspace'}]}],
            'initContainers':[{'name':'context-profile-backup','image':'old-backup-image'}],
            'volumes':[{'name':'state'},{'name':'cifs'}]}}}}
        before=copy.deepcopy(original);new,rollback=m.specification(original,'immutable-source')
        self.assertEqual(original,before)
        pod=new['template']['spec'];self.assertEqual(pod['volumes'][:2],before['spec']['template']['spec']['volumes'])
        self.assertEqual(pod['containers'][0]['volumeMounts'][:2],before['spec']['template']['spec']['containers'][0]['volumeMounts'])
        self.assertEqual(pod['containers'][0]['env'][0],before['spec']['template']['spec']['containers'][0]['env'][0])
        self.assertIn('if root.exists()',rollback['template']['spec']['initContainers'][0]['command'][2])
        self.assertFalse(any(v['name']=='context-transport' for v in rollback['template']['spec']['volumes']))

    def test_excludes_legacy_and_shared_gateway(self):
        m=load('promote_1m_runtimes')
        self.assertTrue(m.selected('dsh-u-1234567890abcdef-secure'))
        self.assertTrue(m.selected('dsh-secure'))
        for name in ['dsh','dsh-user2','dsh3','dsh-environment-gateway','unexpected']:
            self.assertFalse(m.selected(name))

if __name__=='__main__':unittest.main()
