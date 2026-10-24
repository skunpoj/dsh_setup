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
    def run_check(self,extra=(),package_override=None,latest='0.2.0-rc.2'):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);docker=root/'Dockerfile';docker.write_text('ARG DSH_VERSION=0.2.0-rc.2\n')
            (root/'scripts').mkdir()
            (root/'scripts/upstream_patch_contract.json').write_text(json.dumps({'baselineVersion':'0.2.0-rc.2','targets':[]}))
            def get(url,limit):
                value={'latest':latest,'alpha':'0.2.1-alpha.4'} if url.endswith('/dist-tags') else {'name':'@deepseek-ai/dsh','version':url.rsplit('/',1)[1],'dist':{'integrity':'sha512-'+'A'*86+'=='}}
                if not url.endswith('/dist-tags') and package_override:value.update(package_override)
                return json.dumps(value).encode()
            with patch.object(upstream,'ROOT',root),patch.object(upstream,'fetch',side_effect=get),patch.object(upstream.subprocess,'check_output',return_value='a'*40+'\trefs/heads/master\n'),patch('sys.argv',['check','--output',str(root/'result.json'),*extra]),contextlib.redirect_stdout(io.StringIO()):
                upstream.main()
            return json.loads((root/'result.json').read_text()),docker.read_text()

    def test_default_channel_does_not_upgrade_to_alpha(self):
        result,docker=self.run_check()
        self.assertFalse(result['candidateChangeRequired']);self.assertIn('0.2.0-rc.2',docker)

    def test_unreviewed_preview_pin_preparation_refused(self):
        with self.assertRaisesRegex(ValueError,'reviewed complete source port'):
            self.run_check(['--candidate','0.2.1-alpha.4','--prepare-candidate'])

    def test_reviewed_pin_preparation(self):
        result,docker=self.run_check(['--prepare-candidate'])
        self.assertTrue(result['candidatePinPrepared'])
        self.assertEqual(docker,'ARG DSH_VERSION=0.2.0-rc.2\n')

    def test_push_and_pull_request_keep_source_pin_when_latest_changes(self):
        for event in ('push', 'pull_request'):
            with self.subTest(event=event):
                result,docker=self.run_check(['--event',event],latest='0.2.1-rc.2')
                self.assertEqual(result['candidateVersion'],'0.2.0-rc.2')
                self.assertEqual(result['candidateSelection'],'checked-out-source-pin')
                self.assertTrue(result['defaultChannelUpdateAvailable'])
                self.assertFalse(result['candidateChangeRequired'])
                self.assertEqual(docker,'ARG DSH_VERSION=0.2.0-rc.2\n')

    def test_scheduled_and_manual_discovery_still_track_latest(self):
        for event in ('schedule', 'workflow_dispatch'):
            with self.subTest(event=event):
                result,docker=self.run_check(['--event',event],latest='0.2.1-rc.2')
                self.assertEqual(result['candidateVersion'],'0.2.1-rc.2')
                self.assertEqual(result['candidateSelection'],'npm-latest')
                self.assertTrue(result['candidateChangeRequired'])
                self.assertEqual(docker,'ARG DSH_VERSION=0.2.0-rc.2\n')

    def test_manual_preview_override_is_preserved(self):
        result,_=self.run_check(['--event','workflow_dispatch','--candidate','0.2.1-alpha.4'])
        self.assertEqual(result['candidateVersion'],'0.2.1-alpha.4')
        self.assertEqual(result['candidateSelection'],'explicit-version')

    def test_source_ci_cannot_substitute_another_candidate(self):
        with self.assertRaisesRegex(ValueError,'checked-out Dockerfile pin'):
            self.run_check(['--event','push','--candidate','0.2.1-alpha.4'])

    def test_workflow_supplies_trigger_to_the_selector(self):
        workflow=(upstream.ROOT/'.github/workflows/upstream-candidate.yml').read_text(encoding='utf-8')
        self.assertIn('args=(--event "$EVENT_NAME")',workflow)
        self.assertIn('args+=(--candidate "$CANDIDATE_VERSION")',workflow)
        self.assertIn('python3 scripts/check_upstream.py',workflow)

    def test_shell_payload_version_rejected(self):
        with self.assertRaises(ValueError):self.run_check(['--candidate','1.2.3;echo unsafe'])

    def test_wrong_package_identity_refused(self):
        with self.assertRaisesRegex(ValueError,'package identity'):
            self.run_check(package_override={'name':'other-package'})

    def test_missing_integrity_refused(self):
        with self.assertRaisesRegex(ValueError,'SHA512'):
            self.run_check(package_override={'dist':{}})

    def test_registry_version_mismatch_refused(self):
        with self.assertRaisesRegex(ValueError,'version mismatch'):
            self.run_check(package_override={'version':'9.9.9'})


if __name__=='__main__':unittest.main()
