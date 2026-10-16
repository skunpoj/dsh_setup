import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('upstream',Path(__file__).resolve().parents[1]/'scripts/check_upstream.py')
upstream=importlib.util.module_from_spec(spec);spec.loader.exec_module(upstream)


class UpstreamCheckTests(unittest.TestCase):
    def run_check(self,extra=()):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);docker=root/'Dockerfile';docker.write_text('ARG DSH_VERSION=0.2.0-rc.2\n')
            def get(url,timeout):
                value={'latest':'0.2.0-rc.2','alpha':'0.2.1-alpha.4'} if url.endswith('/dist-tags') else {'version':url.rsplit('/',1)[1],'dist':{'integrity':'sha512-fixture'}}
                return contextlib.closing(io.BytesIO(json.dumps(value).encode()))
            with patch.object(upstream,'ROOT',root),patch.object(upstream.urllib.request,'urlopen',side_effect=get),patch.object(upstream.subprocess,'check_output',return_value='a'*40+'\trefs/heads/master\n'),patch('sys.argv',['check','--output',str(root/'result.json'),*extra]),contextlib.redirect_stdout(io.StringIO()):
                upstream.main()
            return json.loads((root/'result.json').read_text()),docker.read_text()

    def test_default_channel_does_not_upgrade_to_alpha(self):
        result,docker=self.run_check()
        self.assertFalse(result['candidateChangeRequired']);self.assertIn('0.2.0-rc.2',docker)

    def test_explicit_preview_changes_only_candidate_pin(self):
        result,docker=self.run_check(['--candidate','0.2.1-alpha.4','--prepare-candidate'])
        self.assertTrue(result['candidateChangeRequired']);self.assertFalse(result['productionChanged'])
        self.assertEqual(docker,'ARG DSH_VERSION=0.2.1-alpha.4\n')

    def test_shell_payload_version_rejected(self):
        with self.assertRaises(ValueError):self.run_check(['--candidate','1.2.3;echo unsafe'])


if __name__=='__main__':unittest.main()
