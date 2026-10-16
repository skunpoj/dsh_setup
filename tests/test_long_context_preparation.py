import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


class CanaryPreparationTests(unittest.TestCase):
    def test_actual_seed_script_preserves_yaml_and_enforces_private_ephemeral_mounts(self):
        file = Path(__file__).parents[1]/'scripts/prepare_1m_canary.py'
        spec = importlib.util.spec_from_file_location('prepare_candidate_test', file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.kube = lambda *a: json.dumps({'spec': {'template': {'spec': {
            'securityContext': {'runAsUser': 10001},
            'containers': [{'image': 'qualified@sha256:example', 'securityContext': {}}]}}}})
        applied = []
        module.apply = applied.append
        module.prepare_dsh('10.42.1.2')
        _, policy, pod = applied
        self.assertEqual(policy['spec']['ingress'], [])
        self.assertTrue(all('emptyDir' in v or 'configMap' in v for v in pod['spec']['volumes']))
        seed = pod['spec']['initContainers'][0]['command'][-1]
        script = seed.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        self.assertNotIn('\x01', script)
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)/'profile.yml'
            profile.write_text('''- id: llm-pi-ai
  config:
    providers:
      litellm-cluster:
        apiKeyEnv: DEEPSEEK_API_KEY
        baseURL: http://litellm.llm.svc.cluster.local:4000/v1
        models:
          - id: deepseek-v4.1-flash
            contextWindow: 131072
- id: compaction-basic
  config:
    thresholdRatio: 0.75
''', encoding='utf8')
            script = script.replace("Path('/state')", 'Path('+repr(directory)+')')
            result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = yaml.safe_load(profile.read_text(encoding='utf8'))
            provider = data[0]['config']['providers']['litellm-cluster']
            self.assertEqual(provider['models'][0]['contextWindow'], 1048576)
            self.assertEqual(provider['streamIdleTimeoutMs'], 3600000)
            self.assertEqual(provider['timeoutMs'], 3600000)
            self.assertEqual(provider['baseURL'], 'http://10.42.1.2:4000/v1')
            self.assertEqual(data[1]['config']['maxTokens'], 8192)
            self.assertEqual(data[1]['config']['thresholdRatio'], .875)


if __name__ == '__main__':
    unittest.main()
