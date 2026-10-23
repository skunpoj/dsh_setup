import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from telemetry_equivalence import verify, SOURCE, SCOPE, FLAG, ANNOTATION


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = {SOURCE: sha(b'old observer\n'), 'models/model.py': sha(b'unchanged model\n')}
        self.new = dict(self.old, **{SOURCE: sha(b'new observer\n')})
        cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'old-cm', 'namespace': 'test'},
              'immutable': True, 'data': {'allocator_observer.py': 'old observer\n', 'model.py': 'unchanged model\n'}}
        spec = {'replicas': 1, 'template': {'metadata': {'annotations': {'run': 'same'}}, 'spec': {
            'volumes': [{'name': 'allocator-patch', 'configMap': {'name': 'old-cm'}}],
            'containers': [{'name': 'vllm', 'image': 'example.invalid/runtime@sha256:' + 'a' * 64,
                            'args': ['--context-length', '1048576', '--mem-fraction-static', '0.922'],
                            'env': [{'name': 'KEEP', 'value': 'same'}]}]}}}
        self.docs = {'oldCM': cm, 'newCM': copy.deepcopy(cm), 'oldSpec': spec, 'newSpec': copy.deepcopy(spec)}
        self.docs['newCM']['metadata']['name'] = 'new-cm'
        self.docs['newCM']['data']['allocator_observer.py'] = 'new observer\n'
        pod = self.docs['newSpec']['template']['spec']
        pod['volumes'][0]['configMap']['name'] = 'new-cm'
        pod['containers'][0]['env'].append({'name': FLAG, 'value': '1'})
        self.docs['newSpec']['template']['metadata']['annotations'][ANNOTATION] = 'read-only-v1'
        self.proof = {'scope': SCOPE, 'changedSource': SOURCE,
                      'oldObserverSHA256': self.old[SOURCE], 'newObserverSHA256': self.new[SOURCE]}
        self.path = self.root / 'proof.json'
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        for key, document in self.docs.items():
            path = self.root / (key + '.json')
            raw = json.dumps(document, indent=2).encode()
            path.write_bytes(raw)
            self.proof[key] = {'path': str(path), 'sha256': sha(raw)}
        self.path.write_text(json.dumps(self.proof), encoding='utf-8')

    def check_reject(self):
        self.save()
        with self.assertRaises(RuntimeError):
            verify(self.old, self.new, self.path)

    def test_exact_positive_delta(self):
        value = verify(self.old, self.new, self.path)
        self.assertTrue(value['allOtherModelSourcesAndNumericalProfileExact'])
        self.assertEqual(value['proofSHA256'], sha(self.path.read_bytes()))
        self.assertEqual(value['oldObserverSHA256'], self.old[SOURCE])

    def test_equal_sources_need_no_proof_or_file_read(self):
        self.assertIsNone(verify(self.old, dict(self.old), self.root / 'absent.json'))

    def test_whole_deployment_artifact_preserves_outer_metadata(self):
        for key in ['oldSpec', 'newSpec']:
            self.docs[key] = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
                              'metadata': {'name': 'model', 'namespace': 'test'}, 'spec': self.docs[key]}
        self.save()
        self.assertTrue(verify(self.old, self.new, self.path)['allOtherModelSourcesAndNumericalProfileExact'])
        self.docs['newSpec']['metadata']['name'] = 'different-model'
        self.check_reject()

    def test_other_model_source_change_rejected(self):
        self.new['models/model.py'] = sha(b'changed math')
        self.check_reject()

    def test_source_key_addition_rejected(self):
        self.new['new.py'] = sha(b'extra source')
        self.check_reject()

    def test_configmap_key_addition_rejected(self):
        self.docs['newCM']['data']['extra.py'] = 'extra'
        self.check_reject()

    def test_other_configmap_source_change_rejected(self):
        self.docs['newCM']['data']['model.py'] += 'changed'
        self.check_reject()

    def test_observer_content_hash_mismatch_rejected(self):
        self.docs['newCM']['data']['allocator_observer.py'] += 'unbound'
        self.check_reject()

    def test_binary_source_addition_rejected(self):
        self.docs['newCM']['binaryData'] = {'extra.py': 'ZXh0cmE='}
        self.check_reject()

    def test_namespace_change_rejected(self):
        self.docs['newCM']['metadata']['namespace'] = 'another'
        self.check_reject()

    def test_mutable_old_configmap_rejected(self):
        for value in [False, None, 1]:
            self.docs['oldCM']['immutable'] = value
            self.check_reject()

    def test_mutable_new_configmap_rejected(self):
        for value in [False, None, 1]:
            self.docs['newCM']['immutable'] = value
            self.check_reject()

    def test_graph_or_numerical_profile_change_rejected(self):
        self.docs['newSpec']['template']['spec']['containers'][0]['args'].extend(['--cuda-graph-max-bs', '16'])
        self.check_reject()

    def test_image_change_rejected(self):
        self.docs['newSpec']['template']['spec']['containers'][0]['image'] = 'another-image'
        self.check_reject()

    def test_flag_value_change_rejected(self):
        self.docs['newSpec']['template']['spec']['containers'][0]['env'][-1]['value'] = '0'
        self.check_reject()

    def test_additional_environment_change_rejected(self):
        self.docs['newSpec']['template']['spec']['containers'][0]['env'].append({'name': 'OTHER', 'value': '1'})
        self.check_reject()

    def test_existing_old_flag_rejected(self):
        self.docs['oldSpec']['template']['spec']['containers'][0]['env'].append({'name': FLAG, 'value': '0'})
        self.check_reject()

    def test_annotation_change_rejected(self):
        self.docs['newSpec']['template']['metadata']['annotations'][ANNOTATION] = 'different'
        self.check_reject()

    def test_volume_reference_change_rejected(self):
        self.docs['newSpec']['template']['spec']['volumes'][0]['configMap']['name'] = 'foreign'
        self.check_reject()

    def test_json_types_are_not_coerced(self):
        self.docs['newSpec']['replicas'] = True
        self.check_reject()

    def test_proof_scope_or_old_hash_change_rejected(self):
        self.proof['scope'] = 'allow-other-changes'
        self.check_reject()
        self.proof['scope'] = SCOPE
        self.proof['oldObserverSHA256'] = sha(b'foreign observer')
        self.check_reject()

    def test_artifact_hash_corruption_rejected(self):
        (self.root / 'newSpec.json').write_bytes(b'{}')
        with self.assertRaises(RuntimeError):
            verify(self.old, self.new, self.path)

    def test_duplicate_json_keys_rejected(self):
        raw = self.path.read_text()
        self.path.write_text('{"scope":"duplicate",' + raw[1:], encoding='utf-8')
        with self.assertRaises(RuntimeError):
            verify(self.old, self.new, self.path)

    def test_missing_proof_rejected_for_delta(self):
        with self.assertRaises(RuntimeError):
            verify(self.old, self.new, None)


if __name__ == '__main__':
    unittest.main()
