"""Instruction refresh must preserve private user context and fail closed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from platform_guide_overlay import transform, with_deployment_context

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guide', ROOT / 'scripts/configure_platform_guide.py')
guide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guide)


class GuideTests(unittest.TestCase):
    def test_deployment_context_keeps_shared_version_and_body(self):
        core = '# DSH shared platform guide\n\nGuide version: 1.2\n\nShared files.\n'
        context = '## Current deployment profile\n\nInternet-only.\n'
        updated = with_deployment_context(core, context)
        self.assertTrue(updated.startswith('# DSH shared platform guide\n\nGuide version: 1.2\n'))
        self.assertLess(updated.index('Internet-only.'), updated.index('Shared files.'))
        self.assertEqual(with_deployment_context(core), core)
        for invalid in ['Unscoped text', '## Current deployment profile\n' + 'x' * 8192]:
            with self.assertRaises(ValueError):
                with_deployment_context(core, invalid)
        with self.assertRaises(ValueError):
            with_deployment_context(core + 'Guide version: duplicate\n', context)

    def test_refresh_preserves_user_text_and_only_one_current_block(self):
        before = '# My own project rules\nKeep this unchanged.\n'
        initial = guide.managed_content(before, 'version one')
        after = guide.managed_content(initial, 'version two')
        self.assertTrue(after.startswith(before))
        self.assertNotIn('version one', after)
        self.assertEqual(after.count(guide.BEGIN), 1)
        self.assertEqual(guide.managed_content(after, 'version two'), after)

    def test_ambiguous_markers_refuse_mutation(self):
        for broken in [guide.BEGIN, guide.END, guide.BEGIN + guide.BEGIN + guide.END + guide.END]:
            with self.assertRaises(ValueError):
                guide.managed_content(broken, 'current')

    def test_runtime_refresh_and_readback_preserve_both_stores(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, workspace = root / 'state', root / 'workspace'
            state.mkdir(); workspace.mkdir()
            original = 'Private project guidance\n'
            (workspace / 'AGENTS.md').write_text(original)
            guide_file = root / 'guide.md'
            guide_file.write_text('shared guide v1')
            guide.install_runtime(state, workspace, guide_file)
            self.assertIn('shared guide v1', (state / 'AGENTS.md').read_text())
            self.assertTrue((workspace / 'AGENTS.md').read_text().startswith(original))
            guide_file.write_text('shared guide v2')
            guide.install_runtime(state, workspace, guide_file)
            for file in [state / 'AGENTS.md', workspace / 'AGENTS.md']:
                self.assertIn('shared guide v2', file.read_text())
                self.assertNotIn('shared guide v1', file.read_text())

    def test_unreviewed_trueforge_package_refused(self):
        for name in guide.HASHES:
            with self.assertRaises(ValueError):
                guide.trueforge_patch(('anything ' + guide.TARGET).encode(), name)

    def test_exclusive_staging_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'AGENTS.md'
            target.write_text('original')
            target.with_name(target.name + '.platform-guide-new').write_text('untrusted staging file')
            with self.assertRaises(FileExistsError):
                guide.write_atomic(target, 'replacement')
            self.assertEqual(target.read_text(), 'original')

    def test_overlay_preserves_image_storage_and_other_sidecars(self):
        original = {'template': {'spec': {'automountServiceAccountToken': False,
            'volumes': [{'name': 'private-data', 'persistentVolumeClaim': {'claimName': 'private-claim'}}],
            'containers': [{'name': 'dsh', 'image': 'qualified@sha256:unchanged',
                'volumeMounts': [{'name': 'private-data', 'mountPath': '/state'}]},
                {'name': 'app-supervisor', 'image': 'supervisor@sha256:unchanged'}]}}}
        changed = transform(original, 'qualified-guide')
        worker = changed['template']['spec']['containers'][0]
        self.assertEqual(worker['image'], original['template']['spec']['containers'][0]['image'])
        self.assertEqual(worker['volumeMounts'][0], original['template']['spec']['containers'][0]['volumeMounts'][0])
        self.assertEqual(changed['template']['spec']['containers'][1], original['template']['spec']['containers'][1])
        self.assertTrue(all(m['readOnly'] for m in worker['volumeMounts'][1:]))
        self.assertNotIn('lifecycle', original['template']['spec']['containers'][0])
        with self.assertRaises(ValueError):
            transform(changed, 'another-guide')


if __name__ == '__main__':
    unittest.main()
