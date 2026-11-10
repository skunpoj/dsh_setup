import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import rollout_dsh_sources as r

GATEWAY_KEYS = ['auth_proxy.js', 'capacity_policy.js', 'platform_ui.js', 'ldapts-LICENSE', 'app-supervisor.py']


class FakeApi:
    def __init__(self, ready=True):
        self.ready = ready
        self.maps = {'dsh-login-recovery-old': {'data': {k: 'old' for k in GATEWAY_KEYS}}}
        self.dep = {'metadata': {'generation': 1}, 'spec': {'replicas': 1, 'template': {'spec': {'volumes': [
            {'name': 'gateway-source', 'configMap': {'name': 'dsh-login-recovery-old'}}, {'name': 'routing', 'configMap': {'name': 'keep'}}]}}},
            'status': {'observedGeneration': 1, 'updatedReplicas': 1, 'readyReplicas': 1, 'replicas': 1}}
        self.patches, self.created = [], []

    def deployment(self, name): return copy.deepcopy(self.dep)
    def config_map(self, name): return self.maps.get(name)
    def create_config_map(self, doc): self.created.append(doc); self.maps[doc['metadata']['name']] = {'data': doc['data']}
    def patch_deployment(self, name, patch):
        self.patches.append(patch)
        self.dep['metadata'].setdefault('annotations', {}).update(patch.get('metadata', {}).get('annotations', {}))
        self.dep['spec']['template'].setdefault('metadata', {}).setdefault('annotations', {}).update(
            patch['spec']['template'].get('metadata', {}).get('annotations', {}))
        volume = patch['spec']['template']['spec']['volumes'][0]
        for v in self.dep['spec']['template']['spec']['volumes']:
            if v['name'] == volume['name']:
                v['configMap'] = volume['configMap']
        self.dep['metadata']['generation'] += 1
        self.dep['status'] = {'observedGeneration': self.dep['metadata']['generation'], 'updatedReplicas': 1,
                              'readyReplicas': 1 if self.ready or len(self.patches) > 1 else 0, 'replicas': 1}


class Args:
    apply, commit, settle, public_url, public_ca_file = False, 'abc123', 0, '', None


class RolloutTests(unittest.TestCase):
    def test_bundle_comes_only_from_repo_and_adds_new_modules(self):
        name, doc = r.build_bundle('gateway', GATEWAY_KEYS)
        self.assertTrue(name.startswith('dsh-gateway-src-'))
        self.assertIn('session_demand.js', doc['data'])
        self.assertIn('course_files.js', doc['data'])
        self.assertIn('signup_admission.js', doc['data'])
        self.assertTrue(doc['immutable'])
        self.assertEqual(doc['data']['ldapts-LICENSE'], (r.ROOT / 'vendor/ldapts/LICENSE').read_text(encoding='utf-8').replace('\r\n', '\n'))
        self.assertEqual(name, r.build_bundle('gateway', GATEWAY_KEYS)[0], 'Same source, same name')
        self.assertIn('capacity_session.py', r.build_bundle('controller', ['capacity_controller.py'])[1]['data'])

    def test_unknown_live_key_fails_closed(self):
        with self.assertRaises(ValueError):
            r.build_bundle('gateway', GATEWAY_KEYS + ['unreviewed.js'])

    def test_dry_run_changes_nothing(self):
        api = FakeApi()
        self.assertEqual(r.rollout(api, 'gateway', Args(), log=lambda *_: None), 0)
        self.assertEqual((api.patches, api.created), ([], []))

    def test_apply_switches_only_the_source_volume(self):
        api, args = FakeApi(), Args()
        args.apply = True
        self.assertEqual(r.rollout(api, 'gateway', args, log=lambda *_: None), 0)
        self.assertEqual(len(api.created), 1)
        vols = {v['name']: v['configMap']['name'] for v in api.dep['spec']['template']['spec']['volumes']}
        self.assertTrue(vols['gateway-source'].startswith('dsh-gateway-src-'))
        self.assertEqual(vols['routing'], 'keep')
        source = api.created[0]
        digest = source['metadata']['annotations']['dsh.example.com/source-data-sha256']
        self.assertEqual(api.dep['metadata']['annotations']['dsh.example.com/gateway-source-configmap'],
                         vols['gateway-source'])
        self.assertEqual(api.dep['spec']['template']['metadata']['annotations']['dsh.example.com/gateway-source-sha256'],
                         digest)
        self.assertEqual(api.dep['metadata']['annotations']['dsh.example.com/source-git-commit'], 'abc123')

    def test_failed_rollout_switches_back(self):
        api, args = FakeApi(ready=False), Args()
        args.apply = True
        r.wait_ready_original = r.wait_ready
        try:
            r.wait_ready = lambda api_, name, timeout=0, settle=0: api_.dep['status']['readyReplicas'] == 1
            self.assertEqual(r.rollout(api, 'gateway', args, log=lambda *_: None), 1)
        finally:
            r.wait_ready = r.wait_ready_original
        self.assertEqual(api.dep['spec']['template']['spec']['volumes'][0]['configMap']['name'], 'dsh-login-recovery-old')
        self.assertIn('dsh-login-recovery-old', api.maps, 'The previous source is never deleted')

    def test_role_rules_are_only_added(self):
        existing = [{'apiGroups': [''], 'resources': ['services'], 'verbs': ['get', 'create']},
                    {'apiGroups': ['apps'], 'resources': ['deployments'], 'verbs': ['get', 'create']}]
        merged = r.merged_rules(existing)
        self.assertEqual(merged[:2], existing)
        self.assertIn({'apiGroups': ['apps'], 'resources': ['deployments/scale'], 'verbs': ['get', 'patch']}, merged)
        self.assertEqual(r.merged_rules(merged), merged, 'Idempotent')

    def test_requires_https_and_token(self):
        with self.assertRaises(SystemExit):
            r.main(['gateway', '--api', 'http://insecure.example'])


# ---------------------------------------------------------------------------
# LiteLLM sidecar component (REST only; fake API, no network, no cluster)
# ---------------------------------------------------------------------------
import calendar
import hashlib
import json
import tempfile
import time
from unittest import mock

OLD_FORWARDER = 'old forwarder\n'
OLD_CALLBACKS = 'old callbacks\n'
OLD_GUARD = 'old guard\n'
LIVE_DATA = {'context_forwarder.py': OLD_FORWARDER, 'long_context_callbacks.py': OLD_CALLBACKS,
             'gateway_output_guard.py': OLD_GUARD, 'context_envelope.py': 'kept as it is\n'}
OLD_HASHES = {'context_forwarder.py': r.text_sha256(OLD_FORWARDER), 'long_context_callbacks.py': r.text_sha256(OLD_CALLBACKS),
              'gateway_output_guard.py': r.text_sha256(OLD_GUARD)}
NOW = calendar.timegm(time.strptime('2026-11-09T12:00:00Z', '%Y-%m-%dT%H:%M:%SZ'))
QUIET_LOG = '\n'.join([
    '{"event": "dsh_long_admission_started", "requestId": "a", "inputTokens": 128028, "waitBudgetSeconds": 1500}',
    '{"event": "dsh_cache_reference_started", "sessionId": "s1"}',
    '{"event": "dsh_cache_reference_closed", "sessionId": "s1"}',
    '{"event": "dsh_request_timing", "requestId": "a", "long": true}',
    'INFO:     127.0.0.1 - "POST /v1/chat/completions HTTP/1.1" 200 OK', ''])


class SidecarApi:
    def __init__(self, live_data=None, name='litellm-interactive-live', strategy='Recreate', replicas=1, log=QUIET_LOG,
                 log_error=None, pods_ready=True, restart_drift=False, new_log=''):
        self.name, self.log, self.log_error, self.pods_ready, self.restart_drift, self.new_log = name, log, log_error, pods_ready, restart_drift, new_log
        self.maps = {name: {'data': dict(live_data or LIVE_DATA), 'metadata': {'annotations': {}}}}
        self.dep = {'metadata': {'generation': 1}, 'spec': {
            'replicas': replicas, 'strategy': {'type': strategy}, 'selector': {'matchLabels': {'app': 'litellm'}},
            'template': {'spec': {
                'containers': [{'name': 'litellm', 'env': [{'name': 'LITELLM_MASTER_KEY', 'value': 'sk-do-not-print'}, {'name': 'PORT', 'value': '4000'}]},
                               {'name': 'context-forwarder'}],
                'volumes': [{'name': 'config', 'configMap': {'name': name}}, {'name': 'routing', 'configMap': {'name': 'keep'}}]}}},
            'status': {'observedGeneration': 1, 'updatedReplicas': 1, 'readyReplicas': 1, 'replicas': 1}}
        self.patches, self.created, self.pod_calls, self.log_calls, self.calls_after_patch = [], [], 0, [], 0

    def deployment(self, name): return copy.deepcopy(self.dep)
    def config_map(self, name): return copy.deepcopy(self.maps.get(name))

    def create_config_map(self, doc):
        self.created.append(doc)
        self.maps[doc['metadata']['name']] = {'data': doc['data'], 'metadata': doc['metadata']}

    def patch_deployment(self, name, patch):
        self.patches.append(patch)
        volume = patch['spec']['template']['spec']['volumes'][0]
        for v in self.dep['spec']['template']['spec']['volumes']:
            if v['name'] == volume['name']:
                v['configMap'] = volume['configMap']
        self.dep.setdefault('metadata', {}).setdefault('annotations', {}).update(patch['metadata']['annotations'])
        self.dep['metadata']['generation'] += 1
        self.dep['status'] = {'observedGeneration': self.dep['metadata']['generation'], 'updatedReplicas': 1, 'readyReplicas': 1, 'replicas': 1}
        self.calls_after_patch = 0

    def pods(self, selector):
        self.pod_calls += 1
        self.calls_after_patch += 1
        self.selector = selector
        mounted = {v['name']: v['configMap']['name'] for v in self.dep['spec']['template']['spec']['volumes']}['config']
        ready = self.pods_ready or mounted == self.name
        restarts = 1 if (self.restart_drift and self.calls_after_patch >= 2 and mounted != self.name) else 0
        return {'items': [{'metadata': {'name': 'litellm-abc'}, 'spec': {'volumes': [{'name': 'config', 'configMap': {'name': mounted}}]},
                           'status': {'phase': 'Running', 'containerStatuses': [
                               {'name': 'litellm', 'ready': ready, 'restartCount': 0},
                               {'name': 'context-forwarder', 'ready': ready, 'restartCount': restarts}]}}]}

    def pod_log(self, pod, container, since_seconds):
        if self.log_error:
            raise RuntimeError(self.log_error)
        self.log_calls.append((pod, container, since_seconds))
        mounted = {v['name']: v['configMap']['name'] for v in self.dep['spec']['template']['spec']['volumes']}['config']
        return self.new_log if (self.new_log and mounted != self.name) else self.log


class SidecarArgs:
    apply, commit, settle, evidence_dir, no_deploy_windows = False, 'abc123def', 0, None, None


def run_sidecar(api, apply=False, now=NOW, hashes=None, evidence_dir=None, windows=None):
    args = SidecarArgs()
    args.apply, args.evidence_dir, args.no_deploy_windows = apply, evidence_dir, windows
    lines = []
    with mock.patch.object(r, 'load_baseline', return_value=hashes if hashes is not None else OLD_HASHES):
        code = r.rollout_sidecar(api, args, log=lines.append, now=now, sleep=lambda *_: None)
    return code, lines


class SidecarTests(unittest.TestCase):
    def test_name_rule_is_the_manual_scripts_rule_and_other_keys_are_kept(self):
        name, doc, changed = r.build_sidecar_bundle(LIVE_DATA, commit='abc')
        data = dict(LIVE_DATA)
        for key, rel in r.SIDECAR['files'].items():
            data[key] = (r.ROOT / rel).read_text(encoding='utf-8')
        expected = 'litellm-interactive-' + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
        self.assertEqual(name, expected)
        self.assertEqual(doc['data'], data)
        self.assertEqual(doc['data']['context_envelope.py'], 'kept as it is\n')
        self.assertTrue(doc['immutable'])
        self.assertEqual(changed, ['context_forwarder.py', 'gateway_output_guard.py', 'long_context_callbacks.py'])
        self.assertEqual(name, r.build_sidecar_bundle(LIVE_DATA)[0], 'Same source, same name')

    def test_missing_live_key_fails_closed(self):
        with self.assertRaises(ValueError):
            r.build_sidecar_bundle({'context_forwarder.py': 'x'})

    def test_baseline_file_is_valid(self):
        files = r.load_baseline()
        self.assertEqual(sorted(files), sorted(r.SIDECAR['files']))

    def test_baseline_covers_gateway_output_guard_and_matches_the_confirmed_live_hash(self):
        # The live ConfigMap was read read-only on 2026-11-10 (LANE6-SAFEGUARDS-DEPLOY-STAGE-GAP-FOUND)
        # and gateway_output_guard.py's content hashed to exactly this value, matching main's
        # pre-fix source. The baseline must record that so a real rollout refuses unless the
        # live file still matches (or is explicitly re-reviewed).
        files = r.load_baseline()
        self.assertIn('gateway_output_guard.py', files)
        self.assertEqual(files['gateway_output_guard.py'],
                          '97f822e003df5f1e9101cc0b02183929131872546cd2c4cc695a09e73399d36d')

    def test_repository_gateway_output_guard_now_differs_from_the_recorded_baseline(self):
        # This fix changes gateway_output_guard.py, so a real rollout must see it as changed
        # (and therefore actually deploy it) rather than silently carrying the old content.
        live_hash = r.load_baseline()['gateway_output_guard.py']
        repo_hash = r.text_sha256((r.ROOT / r.SIDECAR['files']['gateway_output_guard.py']).read_text(encoding='utf-8'))
        self.assertNotEqual(live_hash, repo_hash)

    def test_plan_only_changes_nothing_and_reports_the_plan(self):
        api = SidecarApi()
        code, lines = run_sidecar(api)
        self.assertEqual(code, 0)
        self.assertEqual((api.patches, api.created), ([], []))
        plan = json.loads(lines[0])
        self.assertEqual((plan['from'], plan['baselineMatch'], plan['deploymentShapeOk'], plan['apply']), ('litellm-interactive-live', True, True, False))
        self.assertTrue(plan['to'].startswith('litellm-interactive-'))
        self.assertEqual(plan['longRequestCheck'], {'available': True, 'openLongRequests': [], 'openCacheReferences': []})
        self.assertEqual(api.selector, 'app=litellm')

    def test_already_running_source_does_nothing(self):
        name, doc, _ = r.build_sidecar_bundle(LIVE_DATA)
        live = dict(doc['data'])
        again = r.build_sidecar_bundle(live)[0]
        api = SidecarApi(live_data=live, name=again)
        code, lines = run_sidecar(api, apply=True, hashes={'context_forwarder.py': 'f' * 64, 'long_context_callbacks.py': 'f' * 64})
        self.assertEqual(code, 0)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('Already running', lines[-1])

    def test_apply_switches_only_the_config_volume_and_writes_redacted_evidence(self):
        api = SidecarApi()
        with tempfile.TemporaryDirectory() as tmp:
            code, lines = run_sidecar(api, apply=True, evidence_dir=tmp)
            self.assertEqual(code, 0, lines)
            written = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(written, ['deployment-after.json', 'deployment-before.json', 'plan.json', 'verification.json'])
            before = (Path(tmp) / 'deployment-before.json').read_text(encoding='utf-8')
            self.assertNotIn('sk-do-not-print', before)
            self.assertIn('<redacted>', before)
            self.assertIn('"4000"', before)
            self.assertTrue(json.loads((Path(tmp) / 'verification.json').read_text(encoding='utf-8'))['passed'])
        self.assertEqual(len(api.created), 1)
        vols = {v['name']: v['configMap']['name'] for v in api.dep['spec']['template']['spec']['volumes']}
        self.assertTrue(vols['config'].startswith('litellm-interactive-') and vols['config'] != 'litellm-interactive-live')
        self.assertEqual(vols['routing'], 'keep')
        self.assertIn('litellm-interactive-live', api.maps, 'The previous source is never deleted')
        self.assertEqual(api.dep['metadata']['annotations']['dsh.example.com/source-git-commit'], 'abc123def')

    def test_unreviewed_baseline_is_refused(self):
        api = SidecarApi()
        code, lines = run_sidecar(api, apply=True, hashes={'context_forwarder.py': 'a' * 64, 'long_context_callbacks.py': OLD_HASHES['long_context_callbacks.py']})
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('Unreviewed source baseline', lines[-1])

    def test_running_long_work_is_refused_but_finished_work_is_not(self):
        started = '{"event": "dsh_long_admission_started", "requestId": "b", "inputTokens": 100000}\n'
        for log in (QUIET_LOG + started, QUIET_LOG + '{"event": "dsh_cache_reference_started", "sessionId": "s2"}\n'):
            api = SidecarApi(log=log)
            code, lines = run_sidecar(api, apply=True)
            self.assertEqual(code, 1)
            self.assertEqual((api.patches, api.created), ([], []))
            self.assertIn('long work is still running', lines[-1])
        self.assertEqual(r.open_long_work(QUIET_LOG), ([], []))
        self.assertEqual(r.open_long_work(QUIET_LOG + started), (['b'], []))
        self.assertEqual(r.open_long_work('not json {\n{"event": 1\n\n'), ([], []))

    def test_unreadable_log_blocks_apply_but_not_the_plan(self):
        api = SidecarApi(log_error='GET /api/v1/namespaces/llm/pods/x/log: HTTP 403')
        code, lines = run_sidecar(api)
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(lines[0])['longRequestCheck']['available'])
        code, lines = run_sidecar(api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('cannot check for running long requests', lines[-1])

    def test_no_deploy_window_refuses_inside_and_just_before_and_on_bad_input(self):
        start = calendar.timegm(time.strptime('2026-11-11T10:00:00Z', '%Y-%m-%dT%H:%M:%SZ'))
        for now in (start + 600, start - 300):
            api = SidecarApi()
            code, lines = run_sidecar(api, apply=True, now=now)
            self.assertEqual(code, 1, now)
            self.assertEqual((api.patches, api.created), ([], []))
            self.assertIn('no-deploy window', lines[-1])
        api = SidecarApi()
        self.assertEqual(run_sidecar(api, apply=True, now=start - 3600)[0], 0, 'An hour before the window is allowed')
        api = SidecarApi()
        self.assertEqual(run_sidecar(api, apply=True, windows=['garbage'])[0], 1, 'A malformed window refuses')
        extra = '2026-11-09T11:30:00Z/2026-11-09T12:30:00Z'
        self.assertEqual(run_sidecar(SidecarApi(), apply=True, windows=[extra])[0], 1, 'An extra window from the command line applies')
        with mock.patch.dict('os.environ', {'DSH_NO_DEPLOY_WINDOWS': extra}):
            self.assertEqual(run_sidecar(SidecarApi(), apply=True)[0], 1, 'DSH_NO_DEPLOY_WINDOWS applies')
        self.assertIsNone(r.blocking_window(NOW, r.no_deploy_windows()))

    def test_wrong_deployment_shape_is_refused(self):
        for kwargs in ({'strategy': 'RollingUpdate'}, {'replicas': 2}):
            api = SidecarApi(**kwargs)
            code, lines = run_sidecar(api, apply=True)
            self.assertEqual(code, 1)
            self.assertEqual((api.patches, api.created), ([], []))
            self.assertIn('Deployment shape', lines[-1])

    def test_pods_that_do_not_become_ready_roll_back(self):
        api = SidecarApi(pods_ready=False)
        code, lines = run_sidecar(api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(api.patches), 2)
        vols = {v['name']: v['configMap']['name'] for v in api.dep['spec']['template']['spec']['volumes']}
        self.assertEqual(vols['config'], 'litellm-interactive-live')
        self.assertIn('litellm-interactive-live', api.maps)
        self.assertTrue(any('Rollout failed verification' in l for l in lines))

    def test_restart_while_settling_rolls_back(self):
        api = SidecarApi(restart_drift=True)
        code, _ = run_sidecar(api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual({v['name']: v['configMap']['name'] for v in api.dep['spec']['template']['spec']['volumes']}['config'], 'litellm-interactive-live')

    def test_traceback_in_the_new_log_rolls_back(self):
        api = SidecarApi(new_log='Traceback (most recent call last):\n  File "x"\nValueError\n')
        code, _ = run_sidecar(api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(api.patches), 2)

    def test_log_is_read_for_the_forwarder_container_over_the_long_request_window(self):
        api = SidecarApi()
        run_sidecar(api)
        self.assertEqual(api.log_calls, [('litellm-abc', 'context-forwarder', r.LONG_LOG_SECONDS)])
        self.assertGreaterEqual(r.LONG_LOG_SECONDS, 3600)

    def test_main_accepts_the_component_and_still_needs_https(self):
        with self.assertRaises(SystemExit):
            r.main(['litellm-sidecar', '--api', 'http://insecure.example'])


if __name__ == '__main__':
    unittest.main()
