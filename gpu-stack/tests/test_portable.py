import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('portable_render', ROOT/'render.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class PortableTests(unittest.TestCase):
    def setUp(self):
        self.settings=json.loads((ROOT/'settings.example.json').read_text(encoding='utf-8-sig'))
        self.docs=module.render(self.settings)

    def test_eight_objects_and_private_listener(self):
        self.assertEqual(len(self.docs),8)
        services=[d for d in self.docs if d['kind']=='Service']
        self.assertEqual(sorted(p['port'] for d in services for p in d['spec']['ports']),[4000,8000])
        d=next(d for d in self.docs if d['kind']=='Deployment' and d['metadata']['name']=='local-inference')
        self.assertEqual(d['spec']['replicas'],1)
        self.assertEqual(d['spec']['strategy']['type'],'Recreate')
        c=d['spec']['template']['spec']['containers'][1]
        self.assertIn('127.0.0.1',c['command'])
        self.assertFalse(d['spec']['template']['spec']['automountServiceAccountToken'])

    def test_no_secret_objects_or_embedded_credentials(self):
        self.assertFalse(any(d['kind']=='Secret' for d in self.docs))
        d=next(d for d in self.docs if d['kind']=='Deployment' and d['metadata']['name']=='local-inference')
        env=d['spec']['template']['spec']['containers'][0]['env']
        for key in ['LITELLM_MASTER_KEY','INTERNAL_ROUTE_KEY','DATABASE_URL']:
            self.assertIn('secretKeyRef', next(v for v in env if v['name']==key)['valueFrom'])

    def test_model_source_is_pinned_and_long_budget_consistent(self):
        d=next(d for d in self.docs if d['kind']=='Deployment' and d['metadata']['name']=='local-model')
        c=d['spec']['template']['spec']['containers'][0]
        self.assertIn('@sha256:',c['image'])
        self.assertEqual(c['resources']['limits']['nvidia.com/gpu'],4)
        self.assertFalse(any(v.get('subPath') in ['model_runner.py','allocator_pressure_guard.py'] for v in c['volumeMounts']))
        a=c['args']
        self.assertNotIn('--enable-mixed-chunk',a)
        for flag,value in {'--context-length':'1048576','--chunked-prefill-size':'1024','--max-prefill-tokens':'1024','--prefill-max-requests':'2','--mem-fraction-static':'0.923','--max-running-requests':'8','--swa-prefix-tails':'16','--speculative-algorithm':'DSPARK','--speculative-dspark-block-size':'5','--cuda-graph-max-bs-decode':'8'}.items():
            self.assertEqual(a[a.index(flag)+1],value)
        cfg=next(d['data']['config.yaml'] for d in self.docs if d['kind']=='ConfigMap' and 'config.yaml' in d['data'])
        parsed=yaml.safe_load(cfg)
        self.assertEqual([m['model_name'] for m in parsed['model_list']],module.ALIASES)
        for policy in parsed['router_settings']['model_group_retry_policy'].values():self.assertEqual(policy['RateLimitErrorRetries'],0)

    def test_indexer_gate_uses_the_same_four_gpus_before_model_start(self):
        model=next(d for d in self.docs if d['kind']=='Deployment'and d['metadata']['name']=='local-model')
        pod=model['spec']['template']['spec'];main=pod['containers'][0]
        gate=next(c for c in pod['initContainers']if c['name']=='verify-indexer-reference')
        self.assertEqual(gate['image'],main['image'])
        self.assertEqual(gate['resources']['requests']['nvidia.com/gpu'],4)
        effective=max(sum(int(c.get('resources',{}).get('requests',{}).get('nvidia.com/gpu',0))for c in pod['containers']),max(int(c.get('resources',{}).get('requests',{}).get('nvidia.com/gpu',0))for c in pod['initContainers']))
        self.assertEqual(effective,4)
        self.assertEqual(gate['workingDir'],'/overlay')
        self.assertIn('indexer_reference_gate.py',gate['command'][-1]);self.assertIn('indexer_tile_patch.py',gate['command'][-1]);self.assertIn('tiledCases', (ROOT/'runtime/indexer_reference_gate.py').read_text())
        mounted=next(v for v in main['volumeMounts']if v.get('subPath')=='dsv41_sparse.py')
        self.assertTrue(mounted['readOnly'])
        self.assertEqual(model['spec']['strategy']['type'],'Recreate')

    def test_indexer_source_stays_out_of_gateway_runtime(self):
        configs=[d for d in self.docs if d['kind']=='ConfigMap']
        patches=next(d['data']for d in configs if 'scheduler_fairness_patch.py'in d['data'])
        gateway=next(d['data']for d in configs if 'config.yaml'in d['data'])
        for name in ['indexer_scratch_patch.py','indexer_reference_gate.py','indexer_tile_patch.py','indexer_dequant_patch.py','indexer_dequant_reference_gate.py']:
            self.assertIn(name,patches)
            self.assertNotIn(name,gateway)
        self.assertIn('b56eca87c3706edc9dd4db0f64431b87d52864495765bc3a85af6dbde21e2a5a',patches['indexer_scratch_patch.py'])

    def test_egress_denies_model_and_limits_gateway(self):
        policies={d['metadata']['name']:d['spec'] for d in self.docs if d['kind']=='NetworkPolicy'}
        self.assertEqual(policies['local-model-boundaries']['egress'],[])
        e=policies['local-inference-boundaries']['egress']
        self.assertEqual(len(e),3)
        self.assertFalse(any('ipBlock' in p for rule in e for p in rule['to']))
        self.assertEqual(policies['local-inference-boundaries']['ingress'][0]['ports'],[{'protocol':'TCP','port':4000}])

    def test_invalid_names_tags_and_unexpected_settings_refused(self):
        for key,value in [('namespace','../private'),('modelClaim','bad/path'),('gatewayImage','image:latest'),('password','must-not-be-a-setting')]:
            s={**self.settings,key:value}
            with self.assertRaises(ValueError):module.render(s)

    def test_namespace_and_references_are_rendered_consistently(self):
        docs=module.render({**self.settings,'namespace':'isolated-test','modelClaim':'different-weights'})
        self.assertTrue(all(d['metadata']['namespace']=='isolated-test' for d in docs))
        cms={d['metadata']['name'] for d in docs if d['kind']=='ConfigMap'}
        for d in docs:
            if d['kind']=='Deployment':
                for v in d['spec']['template']['spec']['volumes']:
                    if 'configMap' in v:self.assertIn(v['configMap']['name'],cms)
        self.assertIn('local-model.isolated-test.svc.cluster.local',yaml.safe_dump_all(docs))

    def test_remote_backend_has_no_local_gpu_or_weights(self):
        s=json.loads((ROOT/'settings.remote-backend.example.json').read_text())
        docs=module.render(s)
        self.assertEqual(len(docs),4)
        self.assertEqual([d['metadata']['name']for d in docs if d['kind']=='Deployment'],['local-inference'])
        text=yaml.safe_dump_all(docs)
        self.assertNotIn('nvidia.com/gpu',text)
        self.assertNotIn('persistentVolumeClaim',text)
        self.assertNotIn('local-model-boundaries',text)
        d=next(d for d in docs if d['kind']=='Deployment')
        c=next(c for c in d['spec']['template']['spec']['containers']if c['name']=='context-forwarder')
        self.assertEqual(next(e['value']for e in c['env']if e['name']=='DSH_TOKENIZER_URL'),s['backendOrigin']+'/v1/tokenize')
        p=next(d for d in docs if d['kind']=='NetworkPolicy')
        self.assertEqual(p['spec']['egress'][0],{'to':[{'ipBlock':{'cidr':'192.0.2.40/32'}}],'ports':[{'protocol':'TCP','port':8443}]})

    def test_remote_origin_and_egress_fail_closed(self):
        s=json.loads((ROOT/'settings.remote-backend.example.json').read_text())
        for change in [{'backendOrigin':'https://user:password@gpu.example.internal'},
                       {'backendOrigin':'https://gpu.example.internal/v1'},
                       {'backendOrigin':'https://gpu.example.internal?key=x'},
                       {'backendOrigin':'https://gpu.example.internal?'},
                       {'backendOrigin':'https://gpu.example.internal#'},
                       {'backendOrigin':'file:///etc/passwd'},
                       {'backendOrigin':'https://gpu.example.internal:99999'},
                       {'backendCIDRs':[]},{'backendCIDRs':['0.0.0.0/0']},
                       {'backendCIDRs':['10.0.0.0/8']},{'backendCIDRs':['8.8.8.8/32']},
                       {'backendCIDRs':['127.0.0.1/32']},{'backendCIDRs':[1]},
                       {'backendCIDRs':['10.20.30.40']},{'modelClaim':'unused-weights'}]:
            with self.assertRaises(ValueError,msg=str(change)):module.render({**s,**change})

    def test_publication_hashes_and_canonical_source_drift(self):
        manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
        for name,expected in manifest['publicContentSha256'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),expected,name)
        canonical=ROOT.parent/'scripts'
        if canonical.exists():
            for name,expected in manifest['sourceContentSha256'].items():
                f=canonical/name
                if f.exists():self.assertEqual(hashlib.sha256(f.read_text(encoding='utf-8-sig').encode()).hexdigest(),expected,'Requalify portable copy: '+name)

    def test_publication_has_no_known_internal_or_credential_values(self):
        # Check both staged source and rendered content. Report only the path/pattern, never a match value.
        patterns=[r'github_pat_',r'kubeconfig-u-',
                  r'(?<![0-9])(?:10|172\.(?:1[6-9]|2[0-9]|3[01])|192\.168)\.(?:[0-9]{1,3}\.){1,2}[0-9]{1,3}',
                  r'(?i)(?:password|api_key)\s*[:=]\s*[\"\x27](?!os\.environ|must-not|DATABASE|LITELLM)[A-Za-z0-9_$-]{12,}']
        candidates=[(f.relative_to(ROOT).as_posix(),f.read_text(encoding='utf-8-sig')) for f in ROOT.rglob('*') if f.is_file() and '__pycache__' not in str(f) and f.suffix in ['.py','.md','.json','.yaml'] and f.name!='test_portable.py']
        candidates.append(('rendered',yaml.safe_dump_all(self.docs)))
        for name,text in candidates:
            for pattern in patterns:self.assertIsNone(re.search(pattern,text),name+' failed privacy pattern')

if __name__=='__main__':unittest.main()
