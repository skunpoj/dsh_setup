import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('managed_kilo', ROOT/'container/kilo-managed.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManagedKiloTests(unittest.TestCase):
    def test_external_and_publication_commands_refused(self):
        for command in [['cloud'], ['auth'], ['remote'], ['plugin'], ['run', '--share'],
                        ['run', '--model=other/model'], ['run', '--attach', 'https://example.com'],
                        ['run', '--dir=/state']]:
            with self.assertRaises(ValueError):
                module.validate(command)

    def test_internal_run_allowed(self):
        args = ['run', '--model', module.MODEL, 'Reply exactly OK']
        self.assertEqual(module.validate(args), args)

    def test_workspace_project_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'workspace'
            root.mkdir()
            project = root/'project'
            project.mkdir()
            module.validate_project(project,root)
            for outside in [Path(directory),Path(directory)/'workspace-other']:
                with self.assertRaises(ValueError): module.validate_project(outside,root)

    def test_local_edit_policy_does_not_enable_shell_or_external_access(self):
        policy=json.loads((ROOT/'container/kilo-managed.json').read_text())['permission']
        self.assertEqual(policy['edit'],'allow')
        self.assertEqual(policy['external_directory'],'deny')
        self.assertEqual(policy['*'],'ask')
        with self.assertRaises(ValueError): module.validate(['run','--auto','test'])

    def test_inherited_override_is_discarded(self):
        with patch.object(module, 'POLICY', ROOT/'container/kilo-managed.json'):
            env = module.environment({'KILO_BIN_PATH': '/tmp/other', 'KILO_TEST_MANAGED_CONFIG_DIR': '/tmp',
                                      'HTTPS_PROXY': 'https://example.com', 'NODE_OPTIONS': '--require /tmp/plugin',
                                      'HOME': '/home/dsh'})
        for name in ['KILO_BIN_PATH', 'KILO_TEST_MANAGED_CONFIG_DIR', 'HTTPS_PROXY', 'NODE_OPTIONS']:
            self.assertNotIn(name, env)
        self.assertEqual(env['KILO_DISABLE_PROJECT_CONFIG'], 'true')
        self.assertEqual(env['XDG_DATA_HOME'], '/state/kilo/data')

    def test_policy_budgets_and_private_credential_reference(self):
        policy = json.loads((ROOT/'container/kilo-managed.json').read_text())
        self.assertEqual(policy['enabled_providers'], ['dsh-internal'])
        self.assertEqual(policy['share'], 'disabled')
        provider = policy['provider']['dsh-internal']
        self.assertEqual(provider['models']['deepseek-v4.1-flash']['limit'], {'context': 1048576, 'output': 8192})
        self.assertEqual(provider['options']['apiKey'], '{file:/harness-credentials/api-key}')


if __name__ == '__main__':
    unittest.main()
