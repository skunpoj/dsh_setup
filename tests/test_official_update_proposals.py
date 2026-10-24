import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
models=load('check_official_models');release=load('prepare_release_patch')


def table(alias='deepseek-flash', revision='DeepSeek-V4.1-Flash-1017'):
    return f'<table><tr><th>MODEL</th><td><code>{alias}</code><sup>(1)</sup></td></tr><tr><td>MODEL VERSION</td><td>{revision}</td></tr></table>'


class OfficialUpdateTests(unittest.TestCase):
    def test_official_model_revision_keeps_api_alias(self):
        self.assertEqual(models.parse_models(table(),'DeepSeek-V4.1-Flash-1017'),
                         [{'apiModel':'deepseek-flash','officialRevision':'DeepSeek-V4.1-Flash-1017'}])

    def test_new_revision_requires_changelog(self):
        with self.assertRaisesRegex(ValueError,'corroboration'):
            models.parse_models(table(),'old announcement')

    def test_previously_reviewed_revision_not_required_in_current_changelog(self):
        self.assertEqual(len(models.parse_models(table(),'', {('deepseek-flash','DeepSeek-V4.1-Flash-1017')})),1)

    def test_changed_or_unrecognized_document_is_refused(self):
        for html in ['<p>not a pricing table</p>',table('evil/model'),table()+table(),table(revision='unversioned')]:
            with self.subTest(html=html),self.assertRaises(ValueError):models.parse_models(html,'DeepSeek-V4.1-Flash-1017')

    def test_only_fixed_official_urls_can_be_requested(self):
        with self.assertRaisesRegex(ValueError,'fixed official'):
            models.fetch_document('https://example.com/pricing')

    def test_new_model_patch_changes_only_tracking_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir();out=root/'evidence'
            baseline={'schemaVersion':1,'source':models.SOURCE,'changelog':models.CHANGELOG,
                      'models':[{'apiModel':'deepseek-flash','officialRevision':'DeepSeek-V4.1-Flash'}]}
            path=root/'config/official-deepseek-models.json';before=json.dumps(baseline,indent=2)+'\n';path.write_text(before)
            with patch.object(models,'ROOT',root),patch.object(models,'fetch_document',side_effect=[table(),'DeepSeek-V4.1-Flash-1017']),patch('sys.argv',['check','--output-dir',str(out)]),contextlib.redirect_stdout(io.StringIO()):models.main()
            receipt=json.loads((out/'official-models.json').read_text());text=(out/'official-model-update.patch').read_text()
            self.assertTrue(receipt['patchGenerated']);self.assertFalse(receipt['runtimeModelChanged']);self.assertFalse(receipt['inferenceRequested'])
            self.assertEqual(path.read_text(),before);self.assertIn('+      "officialRevision": "DeepSeek-V4.1-Flash-1017"',text)
            self.assertNotIn('configure_models',text);self.assertNotIn('Dockerfile',text)
            subprocess.run(['git','apply','--check','--whitespace=error'],input=text,text=True,cwd=root,check=True,capture_output=True)
            subprocess.run(['git','apply','--whitespace=error'],input=text,text=True,cwd=root,check=True,capture_output=True)
            self.assertEqual(json.loads(path.read_text())['models'][0]['officialRevision'],'DeepSeek-V4.1-Flash-1017')

    def test_unreviewed_release_patch_preserves_fixes_and_remains_blocked(self):
        docker='ARG DSH_VERSION=0.2.1-rc.2\nRUN keep-auth-fix && keep-image-fix\n'
        patch,receipt=release.propose(docker,{'candidateVersion':'0.2.2','sourcePackagePin':'0.2.1-rc.2'},
                                     {'candidateVersion':'0.2.2','buildAllowed':False})
        self.assertIn('+ARG DSH_VERSION=0.2.2',patch);self.assertNotIn('-RUN',patch)
        self.assertFalse(receipt['buildAllowed']);self.assertFalse(receipt['applied']);self.assertFalse(receipt['contractsChanged'])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'Dockerfile';path.write_text(docker)
            subprocess.run(['git','apply','--check','--whitespace=error'],input=patch,text=True,cwd=d,check=True,capture_output=True)
            subprocess.run(['git','apply','--whitespace=error'],input=patch,text=True,cwd=d,check=True,capture_output=True)
            self.assertEqual(path.read_text(),docker.replace('DSH_VERSION=0.2.1-rc.2','DSH_VERSION=0.2.2'))

    def test_same_release_generates_no_patch(self):
        text,receipt=release.propose('ARG DSH_VERSION=0.2.1-rc.2\n',{'candidateVersion':'0.2.1-rc.2','sourcePackagePin':'0.2.1-rc.2'}, {'candidateVersion':'0.2.1-rc.2','buildAllowed':True})
        self.assertEqual(text,'');self.assertEqual(receipt['status'],'unchanged')

    def test_stale_mixed_or_malicious_release_receipts_refused(self):
        cases=[({'candidateVersion':'0.2.2; bad','sourcePackagePin':'0.2.1'}, {'candidateVersion':'0.2.2; bad'}),
               ({'candidateVersion':'0.2.2','sourcePackagePin':'0.2.0'}, {'candidateVersion':'0.2.2'}),
               ({'candidateVersion':'0.2.2','sourcePackagePin':'0.2.1'}, {'candidateVersion':'0.2.3'})]
        for detection,comparison in cases:
            with self.subTest(detection=detection),self.assertRaises(ValueError):release.propose('ARG DSH_VERSION=0.2.1\n',detection,comparison)


if __name__=='__main__':unittest.main()
