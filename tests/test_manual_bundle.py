import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('manual_bundle',Path(__file__).resolve().parents[1]/'scripts/build_manual_bundle.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManualBundleTests(unittest.TestCase):
    def test_link_closure_and_content_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            for name in ['DSH_PLATFORM_GUIDE','DSH_SECURITY_ENVIRONMENT_AND_FEATURES','DSH_SETUP_AND_STRESS_TEST_GUIDE','MANAGED_CLIENT_SUPPORT']:
                (root/(name+'.html')).write_text('<a href="details.json">Details</a><a href="../private.json">Outside</a>',encoding='utf-8')
            (root/'details.json').write_text('{"public":true}',encoding='utf-8')
            with patch.object(module,'ROOT',root):
                result=module.build(Path(folder)/'bundle')
            manifest=json.loads((Path(folder)/'bundle/manifest.json').read_text())
            self.assertEqual(result['files'],5)
            self.assertNotIn('../private.json',manifest['files'])
            for name,entry in manifest['files'].items():
                self.assertEqual(entry['sha256'],hashlib.sha256((root/name).read_bytes()).hexdigest())

    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileExistsError):
                module.build(Path(folder))

    def test_missing_required_guide_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            with patch.object(module,'ROOT',root),self.assertRaises(ValueError):
                module.build(Path(folder)/'bundle')


if __name__=='__main__':
    unittest.main()
