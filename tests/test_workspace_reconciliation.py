import importlib.util
from pathlib import Path
import tempfile
import unittest
import io
import tarfile

spec = importlib.util.spec_from_file_location('reconcile', Path(__file__).resolve().parents[1] / 'scripts/reconcile_workspace.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReconciliationTests(unittest.TestCase):
    def test_portable_history_restore_verifies_content_and_refuses_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'history.tar.gz'
            with tarfile.open(archive, 'w:gz') as target:
                member = tarfile.TarInfo('sessions/example.json')
                data = b'{"test":"history"}'
                member.size = len(data)
                target.addfile(member, io.BytesIO(data))
            result = module.restore_history_archive(archive, root / 'restored')
            self.assertEqual(result['restoredStateFilesChecked'], 1)
            self.assertEqual((root / 'restored/sessions/example.json').read_bytes(), data)
            with tarfile.open(archive, 'w:gz') as target:
                member = tarfile.TarInfo('../outside')
                member.size = 1
                target.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                module.restore_history_archive(archive, root / 'rejected')
            self.assertFalse((root / 'outside').exists())

    def test_preserves_both_conflict_versions_and_destination_only_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target, recovery = root / 'source', root / 'central', root / 'recovery'
            source.mkdir(); target.mkdir()
            (source / 'changed').write_text('new local work')
            (target / 'changed').write_text('previous central work')
            (target / 'central-only').write_text('keep me')
            (source / 'new').write_text('new file')
            result = module.reconcile(source, target, recovery)
            self.assertEqual((target / 'changed').read_text(), 'new local work')
            self.assertEqual((recovery / 'central-conflicts/changed').read_text(), 'previous central work')
            self.assertEqual((target / 'central-only').read_text(), 'keep me')
            self.assertEqual(result['verifiedFiles'], 2)
            self.assertEqual(result['conflictsPreserved'], 1)
            self.assertEqual(result['destinationOnlyPreserved'], 1)
            with self.assertRaises(FileExistsError):
                module.reconcile(source, target, recovery)

    def test_type_collision_fails_before_modifying_central(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, target = root / 'source', root / 'central'
            source.mkdir(); target.mkdir()
            (source / 'item').write_text('file')
            (target / 'item').mkdir()
            with self.assertRaises(ValueError):
                module.reconcile(source, target, root / 'recovery')
            self.assertTrue((target / 'item').is_dir())
            self.assertFalse((root / 'recovery').exists())


if __name__ == '__main__':
    unittest.main()
