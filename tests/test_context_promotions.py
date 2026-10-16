import copy
import importlib.util
from pathlib import Path
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class RuntimePromotion(unittest.TestCase):
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

    def test_excludes_legacy_and_shared_gateway(self):
        m=load('promote_1m_runtimes')
        self.assertTrue(m.selected('dsh-u-1234567890abcdef-secure'))
        self.assertTrue(m.selected('dsh-secure'))
        for name in ['dsh','dsh-user2','dsh3','dsh-environment-gateway','unexpected']:
            self.assertFalse(m.selected(name))

if __name__=='__main__':unittest.main()
