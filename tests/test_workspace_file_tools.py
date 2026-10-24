import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('files', ROOT/'container/workspace-file-tools.py')
files = importlib.util.module_from_spec(spec)
spec.loader.exec_module(files)


@unittest.skipUnless(os.name == 'posix', 'Linux dirfd protection is exercised in the disposable worker')
class WorkspaceFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'workspace'
        self.root.mkdir()
        (self.root/'project').mkdir()
        self.outside = Path(self.temp.name)/'secret'
        self.outside.write_text('not for the model')

    def call(self, name, path, **args):
        return files.operate({'name':name, 'arguments':{'path':path, **args}}, str(self.root))

    def test_real_write_read_replace_and_list(self):
        self.call('write_file', 'project/test.json', content='{"value":"original"}')
        self.assertEqual(self.call('read_file', 'project/test.json')['content'], '{"value":"original"}')
        self.call('write_file', str(self.root/'project/test.json'), content='new')
        self.assertEqual((self.root/'project/test.json').read_text(), 'new')
        self.assertEqual(self.call('list_directory', 'project'), {'entries':['test.json']})

    def test_outside_traversal_and_unknown_operations_denied(self):
        for path in [str(self.outside), '../secret', 'project/../../secret']:
            for operation in ['read_file','write_file']:
                with self.assertRaises(ValueError): self.call(operation,path,content='bad')
        with self.assertRaises(ValueError): self.call('execute','project')
        self.assertEqual(self.outside.read_text(), 'not for the model')

    def test_symlink_parent_and_leaf_denied(self):
        (self.root/'link').symlink_to(self.outside.parent, target_is_directory=True)
        (self.root/'leaf').symlink_to(self.outside)
        for path in ['link/secret','leaf']:
            for operation in ['read_file','write_file']:
                with self.assertRaises((OSError,ValueError)): self.call(operation,path,content='bad')
        self.assertEqual(self.outside.read_text(), 'not for the model')

    def test_hardlink_and_fifo_denied(self):
        os.link(self.outside,self.root/'hardlink')
        os.mkfifo(self.root/'fifo')
        for path in ['hardlink','fifo']:
            for operation in ['read_file','write_file']:
                with self.assertRaises(ValueError): self.call(operation,path,content='bad')

    def test_bounded_text_and_missing_parent(self):
        with self.assertRaises(ValueError): self.call('write_file','large',content='x'*(files.LIMIT+1))
        with self.assertRaises(FileNotFoundError): self.call('write_file','missing/file',content='x')
        (self.root/'binary').write_bytes(b'\xff')
        with self.assertRaises(UnicodeError): self.call('read_file','binary')


if __name__ == '__main__': unittest.main()
