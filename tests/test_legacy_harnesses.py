from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from rollout_legacy_harnesses import candidate,repair_key_mode


class LegacyHarnessesTests(unittest.TestCase):
    def original(self):
        return {'spec':{'replicas':1,'strategy':{'type':'Recreate'},'template':{'spec':{
            'volumes':[{'name':'home','persistentVolumeClaim':{'claimName':'private-owner-home'}}],
            'containers':[{'name':'dsh','image':'image@sha256:'+'a'*64,
                'securityContext':{'runAsUser':10001,'runAsNonRoot':True},
                'volumeMounts':[{'name':'home','mountPath':'/root','subPath':'owner'}]},
                {'name':'auth-proxy','env':[{'name':'AUTH_USER','value':'owner'}]}]}}}}

    def test_alias_retains_same_bounded_home_without_new_data_scope(self):
        old=self.original();new=candidate(old,'scoped-key','pinned-policy');p=new['template']['spec'];worker=p['containers'][0]
        alias=next(m for m in worker['volumeMounts']if m['mountPath']=='/state')
        self.assertEqual(alias,{'name':'home','mountPath':'/state','subPath':'owner'})
        self.assertEqual(p['containers'][1],old['spec']['template']['spec']['containers'][1])
        self.assertEqual(p['volumes'][0],old['spec']['template']['spec']['volumes'][0])
        self.assertTrue(all(m.get('readOnly')for m in worker['volumeMounts']if m['name']in ['harness-credentials','managed-client-policy']))
        self.assertEqual(old,self.original())

    def test_key_mode_repair_cannot_expose_mount_to_auth_container(self):
        old=self.original();old['spec']=candidate(old,'scoped-key','pinned-policy')
        p=old['spec']['template']['spec'];v=next(v for v in p['volumes']if v['name']=='harness-credentials');v['secret']['defaultMode']=0o440
        repaired=repair_key_mode(old,'scoped-key');after=next(v for v in repaired['template']['spec']['volumes']if v['name']=='harness-credentials')
        self.assertEqual(after['secret']['defaultMode'],0o444)
        p['containers'][1]['volumeMounts']=[{'name':'harness-credentials','mountPath':'/unexpected'}]
        with self.assertRaises(ValueError):repair_key_mode(old,'scoped-key')

    def test_existing_state_alias_or_credential_scope_is_refused(self):
        for kind in ['state','credentials','root']:
            old=self.original();p=old['spec']['template']['spec'];worker=p['containers'][0]
            if kind=='state':worker['volumeMounts'].append({'name':'other','mountPath':'/state'})
            elif kind=='credentials':p['volumes'].append({'name':'harness-credentials'})
            else:worker['securityContext']['runAsUser']=0
            with self.assertRaises(ValueError):candidate(old,'scoped-key','pinned-policy')


if __name__=='__main__':unittest.main()
