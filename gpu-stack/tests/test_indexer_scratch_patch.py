"""Source-fence and file-preservation checks; GPU math runs in the startup gate."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT/'runtime/indexer_scratch_patch.py'
if not HELPER.exists():
    HELPER = ROOT/'scripts/indexer_scratch_patch.py'
spec = importlib.util.spec_from_file_location('qualified_indexer_patch', HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

FIXTURE = ('import torch\nclass Indexer:\n'
           '    def scores(self, q, k, weights):\n'
           '        s = torch.einsum("bhd,nd->bhn", q, k)\n'
           + module.ANCHOR + '\n# unrelated source must remain unchanged\n')

def digest(source):
    return hashlib.sha256(source.encode()).hexdigest()

class IndexerPatchTests(unittest.TestCase):
    def test_production_pin_is_the_qualified_image_source(self):
        self.assertEqual(module.SOURCE_SHA256,
            'b56eca87c3706edc9dd4db0f64431b87d52864495765bc3a85af6dbde21e2a5a')

    def test_unknown_source_is_refused_without_force_option(self):
        with self.assertRaisesRegex(ValueError, 'Unqualified indexer source'):
            module.patch(FIXTURE)

    def test_reviewed_target_changes_only_the_exact_anchor(self):
        with patch.object(module, 'SOURCE_SHA256', digest(FIXTURE)):
            result = module.patch(FIXTURE)
        self.assertEqual(result, FIXTURE.replace(module.ANCHOR, module.REPLACEMENT, 1))
        ast.parse(result)
        self.assertIn('# unrelated source must remain unchanged', result)

    def test_ambiguous_anchor_is_refused_even_with_reviewed_digest(self):
        source = FIXTURE + FIXTURE
        with patch.object(module, 'SOURCE_SHA256', digest(source)):
            with self.assertRaisesRegex(ValueError, 'target changed'):
                module.patch(source)

    def test_cli_preserves_an_existing_output_file(self):
        with tempfile.TemporaryDirectory(prefix='indexer-patch-test-') as name:
            root = Path(name).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            original, output = root/'source.py', root/'overlay.py'
            original.write_text(FIXTURE, encoding='utf-8')
            output.write_text('preserve-this-generation', encoding='utf-8')
            run = subprocess.run([sys.executable, str(HELPER), str(original), str(output)],
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(output.read_text(encoding='utf-8'), 'preserve-this-generation')
            self.assertEqual(original.read_text(encoding='utf-8'), FIXTURE)

    def test_cli_source_drift_does_not_create_an_overlay(self):
        with tempfile.TemporaryDirectory(prefix='indexer-patch-test-') as name:
            root = Path(name).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            original, output = root/'source.py', root/'overlay.py'
            original.write_text(FIXTURE, encoding='utf-8')
            run = subprocess.run([sys.executable, str(HELPER), str(original), str(output)],
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(output.exists())
            self.assertEqual(original.read_text(encoding='utf-8'), FIXTURE)

if __name__ == '__main__':
    unittest.main()
