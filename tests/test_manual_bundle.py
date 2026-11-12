import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('manual_bundle',Path(__file__).resolve().parents[1]/'scripts/build_manual_bundle.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ManualBundleTests(unittest.TestCase):
    def test_committed_publication_ignores_checkout_line_endings_and_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            names=['DSH_USER_MANUAL','DSH_GUIDED_TOUR','DSH_PLATFORM_GUIDE','DSH_SECURITY_ENVIRONMENT_AND_FEATURES','MANAGED_CLIENT_SUPPORT']
            original=b'<p>Committed guide</p>\n'
            for name in names:(root/(name+'.html')).write_bytes(original)
            subprocess.run(['git','init','-q'],cwd=folder,check=True)
            subprocess.run(['git','-c','core.autocrlf=false','add','docs'],cwd=folder,check=True)
            subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],cwd=folder,check=True)
            (root/'DSH_USER_MANUAL.html').write_bytes(b'<p>Uncommitted edit</p>\r\n')
            with patch.object(module,'ROOT',root):module.build(Path(folder)/'bundle','HEAD')
            for name in names:self.assertEqual((Path(folder)/'bundle'/(name+'.html')).read_bytes(),original)
            manifest=json.loads((Path(folder)/'bundle/manifest.json').read_text())
            self.assertEqual(len(manifest['sourceCommit']),40)

    def test_committed_publication_from_nested_repository_path(self):
        # GPU_server keeps docs at deployment/vllm/dsh-environments/docs, not the repository root.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'deployment/dsh-environments/docs';root.mkdir(parents=True)
            names=['DSH_USER_MANUAL','DSH_GUIDED_TOUR','DSH_PLATFORM_GUIDE','DSH_SECURITY_ENVIRONMENT_AND_FEATURES','MANAGED_CLIENT_SUPPORT']
            for name in names:(root/(name+'.html')).write_bytes(b'<p>Nested guide</p>\n')
            # an internal runbook in docs/ is never part of the public bundle (user policy, 11 Nov 2026)
            (root/'DSH_SETUP_AND_STRESS_TEST_GUIDE.html').write_bytes(b'<p>Internal runbook</p>\n')
            subprocess.run(['git','init','-q'],cwd=folder,check=True)
            subprocess.run(['git','-c','core.autocrlf=false','add','deployment'],cwd=folder,check=True)
            subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],cwd=folder,check=True)
            with patch.object(module,'ROOT',root):result=module.build(Path(folder)/'bundle','HEAD')
            self.assertEqual(result['files'],5)

    def test_link_closure_and_content_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            for name in ['DSH_USER_MANUAL','DSH_GUIDED_TOUR','DSH_PLATFORM_GUIDE','DSH_SECURITY_ENVIRONMENT_AND_FEATURES','MANAGED_CLIENT_SUPPORT']:
                (root/(name+'.html')).write_text('<a href="details.json">Details</a><a href="../private.json">Outside</a>',encoding='utf-8')
            (root/'details.json').write_text('{"public":true}',encoding='utf-8')
            with patch.object(module,'ROOT',root):
                result=module.build(Path(folder)/'bundle')
            manifest=json.loads((Path(folder)/'bundle/manifest.json').read_text())
            self.assertEqual(result['files'],6)
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



class ExplicitPublicEntrypointTests(unittest.TestCase):
    def test_cli_reads_explicit_selection_and_rejects_empty_selection(self):
        import sys
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);root=home/'docs';root.mkdir();scripts=home/'scripts';scripts.mkdir()
            script=scripts/'build_manual_bundle.py';script.write_bytes(Path(module.__file__).read_bytes())
            (root/'index.html').write_bytes(b'<p>Selected public index</p>')
            selection=home/'selection.json';selection.write_text('["index.html"]',encoding='utf-8')
            result=subprocess.run([sys.executable,str(script),'--output',str(home/'bundle'),'--entrypoints-json',str(selection)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['files'],1)
            self.assertEqual((home/'bundle/index.html').read_bytes(),(root/'index.html').read_bytes())
            selection.write_text('[]',encoding='utf-8')
            result=subprocess.run([sys.executable,str(script),'--output',str(home/'invalid'),'--entrypoints-json',str(selection)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((home/'invalid').exists())

    def test_selected_public_roots_close_links_without_private_defaults_or_retention(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            (root/'index.html').write_text('<a href="details.json">Details</a>',encoding='utf-8')
            (root/'details.json').write_bytes(b'{"public":true}')
            (root/'COURSE_GUIDE.md').write_text('Not selected',encoding='utf-8')
            with patch.object(module,'ROOT',root):
                result=module.build(Path(folder)/'bundle',entrypoints=['index.html'])
            manifest=json.loads((Path(folder)/'bundle/manifest.json').read_text())
            self.assertEqual(set(manifest['files']),{'index.html','details.json'})
            self.assertEqual(result['files'],2)
            for name,record in manifest['files'].items():
                self.assertEqual(record['sha256'],hashlib.sha256((root/name).read_bytes()).hexdigest())

    def test_default_still_retains_optional_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            for name in ['DSH_USER_MANUAL','DSH_GUIDED_TOUR','DSH_PLATFORM_GUIDE','DSH_SECURITY_ENVIRONMENT_AND_FEATURES','MANAGED_CLIENT_SUPPORT']:
                (root/(name+'.html')).write_bytes(b'<p>Guide</p>')
            (root/'COURSE_GUIDE.md').write_bytes(b'Retained')
            with patch.object(module,'ROOT',root):result=module.build(Path(folder)/'bundle')
            self.assertEqual(result['files'],6)
            self.assertEqual((Path(folder)/'bundle/COURSE_GUIDE.md').read_bytes(),b'Retained')

    def test_invalid_selections_refused_before_any_output_write(self):
        invalid=[[],{},'index.html',[None],['index.html']*2,['../secret.json'],['/index.html'],['https://example.invalid/index.html'],['C:/index.html'],['a\\index.html'],['folder/alternate:stream.html'],['bad'+chr(0)+'.html'],['./index.html'],['a//index.html'],['index.html?x=1'],['index.html#part'],['secret.exe'],['index.html']*501]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            for i,selection in enumerate(invalid):
                target=Path(folder)/('out'+str(i))
                with self.subTest(selection=selection),patch.object(module,'ROOT',root),self.assertRaises(ValueError):
                    module.build(target,entrypoints=selection)
                self.assertFalse(target.exists())

    def test_direct_and_linked_internal_runbooks_remain_held(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            (root/'INSTALL.md').write_bytes(b'Internal')
            (root/'index.html').write_bytes(b'<a href="INSTALL.md">Internal</a>')
            for i,name in enumerate(['INSTALL.md','index.html']):
                with patch.object(module,'ROOT',root),self.assertRaisesRegex(ValueError,'publication hold'):
                    module.build(Path(folder)/('out'+str(i)),entrypoints=[name])
                self.assertFalse((Path(folder)/('out'+str(i))/'INSTALL.md').exists())

    def test_output_under_input_is_refused_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'docs';root.mkdir()
            (root/'index.html').write_bytes(b'Original')
            with patch.object(module,'ROOT',root),self.assertRaisesRegex(ValueError,'read-only docs input'):
                module.build(root/'out',entrypoints=['index.html'])
            self.assertEqual(list(root.iterdir()),[root/'index.html'])
            self.assertEqual((root/'index.html').read_bytes(),b'Original')

if __name__=='__main__':
    unittest.main()
