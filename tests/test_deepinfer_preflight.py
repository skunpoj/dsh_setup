import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

spec = importlib.util.spec_from_file_location('preflight', Path(__file__).parents[1] / 'scripts/deepinfer_preflight.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class HardwareGate(unittest.TestCase):
    def test_h100_is_blocked(self):
        rows = gate.parse_hardware('NVIDIA H100 NVL, 9.0, 580.178.04\n' * 4)
        result = gate.assess(rows, {})
        self.assertEqual(result['status'], 'blocked-unsupported-gpu')
        self.assertFalse(result['productionEligible'])
        self.assertFalse(result['weightsLoaded'])

    def test_sm100_only_passes_architecture_not_production(self):
        result = gate.assess(gate.parse_hardware('synthetic SM100, 10.0, synthetic-driver'), {})
        self.assertTrue(result['offlineArchitectureEligible'])
        self.assertFalse(result['productionEligible'])

    def test_mixed_or_future_architecture_is_not_assumed_supported(self):
        for capability in ['9.0', '11.0']:
            rows = gate.parse_hardware('synthetic SM100, 10.0, synthetic-driver\nsynthetic GPU, ' + capability + ', synthetic-driver')
            self.assertFalse(gate.assess(rows, {})['offlineArchitectureEligible'])

    def test_empty_or_malformed_discovery_is_refused(self):
        for text in ['', 'NVIDIA GPU, unavailable, driver', 'NVIDIA GPU, 9.0', ', 9.0, driver']:
            with self.assertRaises(ValueError):
                gate.parse_hardware(text)

    def test_unreviewed_source_revision_is_refused(self):
        with patch.object(gate, 'git', return_value=b'unreviewed-revision\n'):
            with self.assertRaisesRegex(ValueError, 'Unreviewed DeepInfer'):
                gate.inspect_source(Path('synthetic-source'))

    def test_modified_kernel_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, files in gate.SOURCES.items():
                for file in files:
                    location = root / 'vendor' / name / file
                    location.parent.mkdir(parents=True, exist_ok=True)
                    location.write_text('synthetic-original-kernel\n', encoding='utf-8')

            def fake_git(location, *args):
                if args == ('rev-parse', 'HEAD'):
                    return (gate.PIN if location == root else gate.DEPENDENCIES[location.name]).encode()
                if args[:1] == ('ls-tree',):
                    name = args[-1].split('/')[-1]
                    return ('160000 commit ' + gate.DEPENDENCIES[name] + '\tvendor/' + name).encode()
                if args == ('show', 'HEAD:README.md'):
                    return b'NVIDIA SM100 GPUs'
                return b'synthetic-original-kernel\n'

            with patch.object(gate, 'git', side_effect=fake_git):
                self.assertEqual(len(gate.inspect_source(root)), 4)
                target = root / 'vendor/FlashMLA/csrc/api/common.h'
                target.write_text('synthetic-guard-bypass\n', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Modified kernel'):
                    gate.inspect_source(root)


if __name__ == '__main__':
    unittest.main()
