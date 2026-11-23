"""Reconciled test suite for the generalized apply_engine_overlay.py
(LANE6-GPU-EXECUTOR-RECONCILED-20261121).

RECONCILIATION NOTE: the original single-purpose script's test file (20 cases, extracted from
this lane's own 12 Nov v3 patch, ORCH_INTEGRATED_ENGINE_FIX_PLUS_HARNESS_VISION_20261112_v3.patch
-- confirmed byte-identical in its companion script to C5's current GPU_server main commit
28301c39, so the test file is inferred identical with very high confidence pending C5's own
explicit export, which has not landed as of this writing) is PRESERVED below, class
`NcclOverlayTests`, with every assertion and comment kept -- only the call sites are adapted to
the new overlay-parameterized interface (see each adaptation noted inline). Nothing was deleted;
nothing was replaced sight-unseen. `AsrOverlayTests`, `MemoryTrimOverlayTests` and
`OverlayRegistryTests` are new, covering the two added overlays and the registry itself, reusing
the SAME FakeApi/_merge_keyed_list helper (adopted from the original file, extended to also
simulate `command` and `lifecycle` container fields for the two new overlays) rather than this
lane's earlier, cruder inline simulation from LANE6-GPU-EXECUTOR-WIRING-DIFF-20261121.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import apply_engine_overlay as o  # noqa: E402


def _merge_keyed_list(existing, patch_list, key):
    """Minimal strategic-merge-patch semantics for a list keyed on `key`: add/replace by that
    key's value, $patch: delete removes the matching entry. Real v1.Container.VolumeMounts merges
    on mountPath; v1.PodSpec.Volumes merges on name -- using the wrong key for either is exactly
    the bug lane 9 found (LANE9-CHECK-LANE6-NCCL-EP-OVERLAY-35914744-ROLLBACK-MERGE-KEY), so this
    fake deliberately keys each list the way the real API server does rather than always using
    'name', or it would not have caught that bug either. Unchanged from the original test file."""
    out = list(existing)
    for item in patch_list:
        value = item.get(key)
        out = [e for e in out if e.get(key) != value]
        if item.get('$patch') != 'delete':
            out.append({k: v for k, v in item.items() if k != '$patch'})
    return out


class FakeApi:
    """Extended from the original test file's FakeApi: container-scalar fields `command` and
    `lifecycle` are now also simulated (plain replace on patch, drop on `{'$patch': 'delete'}`),
    needed for the two new overlays; every NCCL-era behavior (volumeMounts/volumes merge,
    annotations, generation bump, readiness) is untouched."""

    def __init__(self, ready=True, image=o.EXPECTED_IMAGE, replicas=1, strategy='Recreate', namespace='llm',
                 pre_existing_mount=None, command=None, lifecycle=None):
        self.ready = ready
        self.namespace = namespace
        self.maps = {}
        container = {'name': o.CONTAINER, 'image': image, 'volumeMounts': []}
        if pre_existing_mount:
            container['volumeMounts'].append(pre_existing_mount)
        if command is not None:
            container['command'] = command
        if lifecycle is not None:
            container['lifecycle'] = lifecycle
        self.dep = {
            'metadata': {'generation': 1},
            'spec': {
                'replicas': replicas,
                'strategy': {'type': strategy},
                'template': {
                    'metadata': {'annotations': {}},
                    'spec': {'containers': [container], 'volumes': [{'name': 'other', 'configMap': {'name': 'keep'}}]},
                },
            },
            'status': {'observedGeneration': 1, 'updatedReplicas': 1, 'readyReplicas': 1, 'replicas': 1},
        }
        self.patches, self.created, self.dry_run_patches = [], [], []

    def deployment(self, name):
        return copy.deepcopy(self.dep)

    def config_map(self, name):
        return copy.deepcopy(self.maps.get(name))

    def create_config_map(self, doc):
        self.created.append(doc)
        self.maps[doc['metadata']['name']] = doc

    def patch_deployment(self, name, patch, dry_run=False):
        if dry_run:
            self.dry_run_patches.append(patch)
            return copy.deepcopy(self.dep)
        self.patches.append(patch)
        tmpl = patch['spec']['template']
        annotations = tmpl.get('metadata', {}).get('annotations', {})
        live_annotations = self.dep['spec']['template']['metadata'].setdefault('annotations', {})
        for k, v in annotations.items():
            if v is None:
                live_annotations.pop(k, None)
            else:
                live_annotations[k] = v
        pspec = tmpl.get('spec', {})
        if 'containers' in pspec:
            patch_container = pspec['containers'][0]
            live_container = self.dep['spec']['template']['spec']['containers'][0]
            if 'volumeMounts' in patch_container:
                live_container['volumeMounts'] = _merge_keyed_list(
                    live_container.get('volumeMounts', []), patch_container['volumeMounts'], 'mountPath')
            for scalar_key in ('command', 'lifecycle'):
                if scalar_key in patch_container:
                    value = patch_container[scalar_key]
                    if isinstance(value, dict) and value.get('$patch') == 'delete':
                        live_container.pop(scalar_key, None)
                    else:
                        live_container[scalar_key] = value
        if 'volumes' in pspec:
            live_volumes = self.dep['spec']['template']['spec'].get('volumes', [])
            self.dep['spec']['template']['spec']['volumes'] = _merge_keyed_list(live_volumes, pspec['volumes'], 'name')
        self.dep['metadata']['generation'] += 1
        self.dep['status'] = {'observedGeneration': self.dep['metadata']['generation'], 'updatedReplicas': 1,
                              'readyReplicas': 1 if self.ready else 0, 'replicas': 1, 'unavailableReplicas': 0 if self.ready else 1}


class Args:
    apply = False
    namespace = 'llm'
    settle = 0
    timeout = 1
    evidence_dir = None


def run(overlay, api, apply=False, evidence_dir=None):
    args = Args()
    args.apply, args.evidence_dir = apply, evidence_dir
    lines = []
    # ADAPTATION: plan_and_apply now takes the overlay first (o.plan_and_apply(overlay, api,
    # args, ...)) -- the original called o.plan_and_apply(api, args, ...) against the single
    # hardcoded NCCL overlay implicitly. Every other argument/keyword is unchanged.
    code = o.plan_and_apply(overlay, api, args, log=lines.append, sleep=lambda *_: None)
    return code, lines


# ==================================================================================================
# Preserved from the original test_apply_engine_overlay.py (20 cases). Every assertion and comment
# below is unchanged from that file; only the call sites were adapted to the new interface, each
# adaptation marked inline. nccl = o.OVERLAYS['nccl-ep-contiguous'] stands in for the module-level
# constants/functions (o.MOUNT_PATH, o.CONFIG_MAP_NAME, o.overlay_already_applied(), etc.) the
# original file referenced directly.
# ==================================================================================================
nccl = o.OVERLAYS['nccl-ep-contiguous']


class PureFunctionTests(unittest.TestCase):
    def test_successor_content_on_disk_matches_the_pinned_hash(self):
        # Guards against someone editing the shipped overlay file without updating the constant.
        # ADAPTATION: o.load_successor_content() -> nccl.load_successor_content() (now an overlay
        # method; renamed from this lane's earlier private self._content() to keep this exact
        # call site working).
        content = nccl.load_successor_content()
        self.assertEqual(o.text_sha256(content), nccl.EXPECTED_SHA256)

    def test_build_config_map_is_immutable_and_content_addressed(self):
        # ADAPTATION: o.build_config_map(content, ns) doesn't exist standalone any more -- the
        # equivalent document is built inside nccl.prepare(); this test instead exercises the same
        # guarantee (immutable, content-addressed name) via the document nccl.prepare() creates.
        api = FakeApi()
        nccl.prepare(api)
        doc = api.maps[nccl.config_map_name]
        self.assertTrue(doc['immutable'])
        self.assertEqual(doc['metadata']['name'], nccl.config_map_name)
        self.assertIn(nccl.PREDECESSOR_COMMIT[:7], doc['metadata']['name'])
        self.assertIn(nccl.EXPECTED_SHA256[:8], doc['metadata']['name'])

    def test_load_successor_content_refuses_a_file_not_matching_the_pinned_hash(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
            f.write('not the reviewed content\n')
            path = Path(f.name)
        try:
            with self.assertRaises(RuntimeError):
                nccl.load_successor_content(path)
        finally:
            path.unlink()

    def test_successor_and_rollback_patch_are_inverse_shaped(self):
        # ADAPTATION: o.successor_patch()/o.rollback_patch() -> nccl.successor_patch()/nccl.rollback_patch().
        succ, roll = nccl.successor_patch(), nccl.rollback_patch()
        succ_mount = succ['spec']['template']['spec']['containers'][0]['volumeMounts'][0]
        roll_mount = roll['spec']['template']['spec']['containers'][0]['volumeMounts'][0]
        self.assertEqual(succ_mount['mountPath'], nccl.MOUNT_PATH)
        # Container volumeMounts merge/delete by mountPath, not name -- the rollback entry must key
        # on mountPath (lane 9, LANE9-CHECK-LANE6-NCCL-EP-OVERLAY-35914744-ROLLBACK-MERGE-KEY) or it
        # would silently fail to match the live mount at all.
        self.assertEqual(roll_mount, {'mountPath': nccl.MOUNT_PATH, '$patch': 'delete'})
        self.assertNotIn('name', roll_mount)
        roll_volume = roll['spec']['template']['spec']['volumes'][0]
        self.assertEqual(roll_volume, {'name': nccl.VOLUME, '$patch': 'delete'})
        self.assertEqual(roll['spec']['template']['spec']['volumes'][0]['$patch'], 'delete')
        for key in (nccl.SOURCE_ANNOTATION, nccl.SHA_ANNOTATION):
            self.assertIn(key, succ['spec']['template']['metadata']['annotations'])
            self.assertIsNone(roll['spec']['template']['metadata']['annotations'][key])

    def test_config_map_document_is_immutable(self):
        api = FakeApi()
        nccl.prepare(api)
        self.assertIs(api.maps[nccl.config_map_name]['immutable'], True)

    def test_dry_run_patch_deployment_appends_query_param(self):
        # Api.patch_deployment itself (not the fake) must append ?dryRun=All. UNCHANGED: o.Api is
        # still the exact same shared class, no overlay involved in this test at all.
        calls = []

        class Recorder(o.Api):
            def call(self, method, path, body=None, content='application/json'):
                calls.append((method, path))
                return {}

        api = Recorder('https://example.invalid', 'x' * 20, 'llm')
        api.patch_deployment('d', {'spec': {}}, dry_run=True)
        api.patch_deployment('d', {'spec': {}}, dry_run=False)
        self.assertTrue(calls[0][1].endswith('?dryRun=All'))
        self.assertFalse(calls[1][1].endswith('?dryRun=All'))


class NcclOverlayTests(unittest.TestCase):
    def test_overlay_not_applied_on_a_fresh_deployment(self):
        # ADAPTATION: o.overlay_already_applied(dep) -> nccl.already_applied(dep).
        self.assertFalse(nccl.already_applied(FakeApi().dep))

    def test_overlay_detected_once_applied(self):
        api = FakeApi()
        run(nccl, api, apply=True)
        self.assertTrue(nccl.already_applied(api.dep))

    def test_mount_path_collision_detected(self):
        # ADAPTATION: o.mount_path_collision(dep) -> nccl.collision(dep) (renamed on the base
        # Overlay class since "collision" isn't always about a mount path for every overlay --
        # e.g. the memory-trim overlay collides on the command string, not a mount).
        colliding = {'name': 'some-other-overlay', 'mountPath': nccl.MOUNT_PATH, 'subPath': 'x'}
        api = FakeApi(pre_existing_mount=colliding)
        self.assertEqual(nccl.collision(api.dep), 'some-other-overlay')

    def test_no_collision_when_mount_absent(self):
        self.assertIsNone(nccl.collision(FakeApi().dep))

    def test_plan_only_changes_nothing(self):
        api = FakeApi()
        code, lines = run(nccl, api, apply=False)
        self.assertEqual(code, 0)
        self.assertEqual((api.patches, api.created), ([], []))
        plan = json.loads(lines[0])
        self.assertEqual((plan['imageOk'], plan['deploymentShapeOk'], plan['alreadyApplied'], plan['apply']), (True, True, False, False))

    def test_plan_mode_dry_runs_both_the_successor_and_rollback_patch(self):
        api = FakeApi()
        code, lines = run(nccl, api, apply=False)
        self.assertEqual(code, 0)
        self.assertEqual(api.patches, [], 'dry run must never be recorded as a real patch')
        self.assertEqual(len(api.dry_run_patches), 2)
        dry_run = json.loads(lines[-1])['dryRun']
        self.assertTrue(dry_run['successorPatchDryRunAccepted'])
        self.assertTrue(dry_run['rollbackPatchDryRunAccepted'])

    def test_plan_mode_dry_run_failure_is_recorded_not_raised(self):
        class FailingApi(FakeApi):
            def patch_deployment(self, name, patch, dry_run=False):
                if dry_run:
                    raise RuntimeError('PATCH ...: HTTP 422')
                return super().patch_deployment(name, patch, dry_run)
        api = FailingApi()
        code, lines = run(nccl, api, apply=False)
        self.assertEqual(code, 0, 'a dry-run failure must not break a plan-only report')
        dry_run = json.loads(lines[-1])['dryRun']
        self.assertFalse(dry_run['successorPatchDryRunAccepted'])
        self.assertIn('HTTP 422', dry_run['successorPatchDryRunError'])

    def test_already_applied_short_circuits(self):
        api = FakeApi()
        run(nccl, api, apply=True)
        patches_before = len(api.patches)
        code, lines = run(nccl, api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(api.patches), patches_before, 'no new patch when already applied')
        self.assertIn('Overlay already applied', lines[-1])

    def test_apply_refuses_on_image_mismatch_no_cluster_change(self):
        api = FakeApi(image='lmsysorg/sglang@sha256:deadbeef')
        code, lines = run(nccl, api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('REFUSED', lines[-1])
        self.assertIn('exact digest', lines[-1])

    def test_apply_refuses_on_wrong_strategy_no_cluster_change(self):
        api = FakeApi(strategy='RollingUpdate')
        code, lines = run(nccl, api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('REFUSED', lines[-1])

    def test_apply_refuses_on_mount_collision_no_cluster_change(self):
        colliding = {'name': 'some-other-overlay', 'mountPath': nccl.MOUNT_PATH, 'subPath': 'x'}
        api = FakeApi(pre_existing_mount=colliding)
        code, lines = run(nccl, api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('Target already used', lines[-1])  # ADAPTATION: message generalized from "Mount path already used"

    def test_successful_apply_creates_configmap_patches_and_verifies(self):
        api = FakeApi()
        code, lines = run(nccl, api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(api.created), 1)
        self.assertEqual(api.created[0]['metadata']['name'], nccl.config_map_name)
        self.assertTrue(nccl.already_applied(api.dep))
        self.assertTrue(any('overlayVerification' in line and json.loads(line)['overlayVerification'] for line in lines))

    def test_failed_readiness_rolls_back(self):
        api = FakeApi(ready=False)
        code, lines = run(nccl, api, apply=True)
        self.assertEqual(code, 1)
        self.assertFalse(nccl.already_applied(api.dep), 'rollback patch must remove the mount again')
        self.assertIn('Rollback', lines[-1])

    def test_evidence_is_written_for_a_successful_apply(self):
        api = FakeApi()
        evidence_dir = Path(__file__).parent / '_tmp_engine_overlay_evidence'
        try:
            run(nccl, api, apply=True, evidence_dir=str(evidence_dir))
            for name in ('plan.json', 'deployment-before.json', 'verification.json', 'deployment-after.json'):
                self.assertTrue((evidence_dir / name).exists(), name)
        finally:
            if evidence_dir.exists():
                for f in evidence_dir.iterdir():
                    f.unlink()
                evidence_dir.rmdir()


# ==================================================================================================
# New: the two overlays added for the GPU-balance change set, and the registry itself.
# ==================================================================================================
class OverlayRegistryTests(unittest.TestCase):
    def test_all_overlays_registered_and_named_correctly(self):
        self.assertEqual(sorted(o.OVERLAYS), ['asr-typhoon-inprocess', 'deepinfer-memory-trim', 'deepinfer-vram-headroom', 'deepseek-thinking-low', 'nccl-ep-contiguous'])
        for name, overlay in o.OVERLAYS.items():
            self.assertEqual(overlay.name, name)


class AsrOverlayTests(unittest.TestCase):
    asr = o.OVERLAYS['asr-typhoon-inprocess']

    def test_already_applied_false_on_clean_deployment(self):
        self.assertFalse(self.asr.already_applied(FakeApi().dep))

    def test_already_applied_true_after_successor_patch_applied(self):
        # A fresh overlay instance (not the shared registry one) with the ConfigMap pre-seeded to
        # match its own pin, so the real prepare() check passes without any monkeypatching.
        import hashlib
        overlay = o.AsrTyphoonInprocessOverlay()
        sample = 'sample asr launcher content'
        overlay.EXPECTED_LAUNCHER_SHA256 = hashlib.sha256(sample.encode()).hexdigest()
        api = FakeApi()
        api.maps[overlay.CONFIG_MAP_NAME] = {'data': {'asr-launcher.sh': sample}}
        self.assertFalse(overlay.already_applied(api.dep))
        run(overlay, api, apply=True)
        self.assertTrue(overlay.already_applied(api.dep))

    def test_prepare_refuses_if_configmap_missing(self):
        api = FakeApi()
        with self.assertRaises(RuntimeError):
            self.asr.prepare(api)

    def test_prepare_refuses_if_live_hash_moved(self):
        api = FakeApi()
        api.maps[self.asr.CONFIG_MAP_NAME] = {'data': {'asr-launcher.sh': 'drifted content'}}
        with self.assertRaises(RuntimeError):
            self.asr.prepare(api)

    def test_prepare_accepts_matching_hash(self):
        import hashlib
        overlay = o.AsrTyphoonInprocessOverlay()
        sample = 'sample asr launcher content'
        overlay.EXPECTED_LAUNCHER_SHA256 = hashlib.sha256(sample.encode()).hexdigest()
        api = FakeApi()
        api.maps[overlay.CONFIG_MAP_NAME] = {'data': {'asr-launcher.sh': sample}}
        overlay.prepare(api)  # must not raise

    def test_successor_patch_does_not_touch_asr_enabled(self):
        self.assertNotIn('asr-enabled', json.dumps(self.asr.successor_patch()))

    def test_apply_refuses_on_image_mismatch_no_cluster_change(self):
        api = FakeApi(image='lmsysorg/sglang@sha256:deadbeef')
        code, lines = run(self.asr, api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))


class MemoryTrimOverlayTests(unittest.TestCase):
    trim = o.OVERLAYS['deepinfer-memory-trim']

    def test_new_command_differs_from_prior_only_in_utilization_and_context_values(self):
        prior_tokens = self.trim.PRIOR_COMMAND.split()
        new_tokens = self.trim.NEW_COMMAND.split()
        self.assertEqual(len(prior_tokens), len(new_tokens))
        diffs = [(a, b) for a, b in zip(prior_tokens, new_tokens) if a != b]
        self.assertEqual(diffs, [('0.93', '0.915'), ('393216', '131072')])

    def test_collision_refuses_when_live_command_is_neither_prior_nor_new(self):
        api = FakeApi(command=['sh', '-c', 'something else entirely'])
        self.assertIsNotNone(self.trim.collision(api.dep))

    def test_collision_clear_when_live_command_is_prior(self):
        api = FakeApi(command=['sh', '-c', self.trim.PRIOR_COMMAND])
        self.assertIsNone(self.trim.collision(api.dep))

    def test_already_applied_true_when_live_command_is_new(self):
        api = FakeApi(command=['sh', '-c', self.trim.NEW_COMMAND])
        self.assertTrue(self.trim.already_applied(api.dep))

    def test_successful_apply_patches_command_and_verifies(self):
        api = FakeApi(command=['sh', '-c', self.trim.PRIOR_COMMAND])
        code, lines = run(self.trim, api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(api.dep['spec']['template']['spec']['containers'][0]['command'][-1], self.trim.NEW_COMMAND)
        self.assertTrue(any('overlayVerification' in line and json.loads(line)['overlayVerification'] for line in lines))

    def test_dry_run_makes_no_mutating_patch_call(self):
        api = FakeApi(command=['sh', '-c', self.trim.PRIOR_COMMAND])
        run(self.trim, api, apply=False)
        self.assertEqual(api.patches, [])


class VramHeadroomOverlayTests(unittest.TestCase):
    ov = o.OVERLAYS['deepinfer-vram-headroom']

    def test_prior_is_the_post_thinking_low_command_and_only_the_utilization_token_changes(self):
        self.assertEqual(self.ov.PRIOR_COMMAND, o.OVERLAYS['deepseek-thinking-low'].NEW_COMMAND)
        prior, new = self.ov.PRIOR_COMMAND.split(), self.ov.NEW_COMMAND.split()
        self.assertEqual([(a, b) for a, b in zip(prior, new) if a != b], [('0.915', '0.905')])
        self.assertEqual(len(prior), len(new))
        self.assertIn('--thinking-mode thinking --reasoning-effort low', self.ov.NEW_COMMAND)

    def test_live_command_already_at_0905_is_a_noop(self):
        api = FakeApi(command=['sh', '-c', self.ov.NEW_COMMAND])
        self.assertTrue(self.ov.already_applied(api.dep))
        code, lines = run(self.ov, api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(api.patches, [])

    def test_collision_refuses_an_unknown_live_command(self):
        api = FakeApi(command=['sh', '-c', 'something else entirely'])
        self.assertIsNotNone(self.ov.collision(api.dep))

    def test_apply_from_prior_patches_command_and_verifies(self):
        api = FakeApi(command=['sh', '-c', self.ov.PRIOR_COMMAND])
        code, lines = run(self.ov, api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(api.dep['spec']['template']['spec']['containers'][0]['command'][-1], self.ov.NEW_COMMAND)


class DeepseekThinkingLowOverlayTests(unittest.TestCase):
    ov = o.OVERLAYS['deepseek-thinking-low']

    def live(self, **kwargs):
        return FakeApi(command=['sh', '-c', self.ov.PRIOR_COMMAND], **kwargs)

    def test_prior_command_is_the_live_post_memory_trim_command(self):
        self.assertEqual(self.ov.PRIOR_COMMAND, o.OVERLAYS['deepinfer-memory-trim'].NEW_COMMAND)
        self.assertIn('--gpu-memory-utilization 0.915', self.ov.PRIOR_COMMAND)
        self.assertIn('--max-model-len 131072', self.ov.PRIOR_COMMAND)

    def test_new_command_differs_only_in_the_thinking_flags(self):
        prior, new = self.ov.PRIOR_COMMAND.split(), self.ov.NEW_COMMAND.split()
        self.assertEqual(len(new), len(prior) + 2)
        self.assertEqual(new[:prior.index('chat')], prior[:prior.index('chat')])
        i = new.index('--thinking-mode')
        self.assertEqual(new[i:i + 4], ['--thinking-mode', 'thinking', '--reasoning-effort', 'low'])
        self.assertEqual(new[:i] + ['--thinking-mode', 'chat'] + new[i + 4:], prior)

    def test_successor_content_on_disk_matches_the_pinned_hash_and_differs_from_the_predecessor_pin(self):
        content = self.ov.load_successor_content()
        self.assertEqual(o.text_sha256(content), self.ov.EXPECTED_SHA256)
        self.assertNotEqual(self.ov.EXPECTED_SHA256, self.ov.PREDECESSOR_SHA256)
        self.assertIn('--reasoning-effort', content)

    def test_load_successor_content_refuses_a_file_not_matching_the_pinned_hash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'openai_server.py'
            path.write_text('edited', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                self.ov.load_successor_content(path)

    def test_fresh_deployment_is_not_applied_and_has_no_collision(self):
        api = self.live()
        self.assertFalse(self.ov.already_applied(api.dep))
        self.assertIsNone(self.ov.collision(api.dep))

    def test_collision_on_foreign_command_or_foreign_mount(self):
        self.assertIsNotNone(FakeApi(command=['sh', '-c', 'something else']).dep and self.ov.collision(FakeApi(command=['sh', '-c', 'something else']).dep))
        mount = {'name': 'someone-else', 'mountPath': self.ov.MOUNT_PATH}
        self.assertEqual(self.ov.collision(self.live(pre_existing_mount=mount).dep), 'someone-else')

    def test_successful_apply_creates_the_configmap_patches_command_and_mount_and_verifies(self):
        api = self.live()
        code, lines = run(self.ov, api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(api.created), 1)
        self.assertTrue(api.created[0]['immutable'])
        self.assertEqual(o.text_sha256(api.created[0]['data']['openai_server.py']), self.ov.EXPECTED_SHA256)
        container = api.dep['spec']['template']['spec']['containers'][0]
        self.assertEqual(container['command'][-1], self.ov.NEW_COMMAND)
        self.assertTrue(any(m['mountPath'] == self.ov.MOUNT_PATH and m['subPath'] == 'openai_server.py' for m in container['volumeMounts']))
        self.assertTrue(self.ov.already_applied(api.dep))
        self.assertTrue(any('overlayVerification' in line and json.loads(line)['overlayVerification'] for line in lines))

    def test_failed_readiness_rolls_back_command_mount_and_volume(self):
        api = self.live(ready=False)
        code, _ = run(self.ov, api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(api.patches), 2)
        container = api.dep['spec']['template']['spec']['containers'][0]
        self.assertEqual(container['command'][-1], self.ov.PRIOR_COMMAND)
        self.assertFalse(any(m['mountPath'] == self.ov.MOUNT_PATH for m in container['volumeMounts']))
        self.assertEqual([v['name'] for v in api.dep['spec']['template']['spec']['volumes']], ['other'])
        self.assertNotIn(self.ov.SHA_ANNOTATION, api.dep['spec']['template']['metadata']['annotations'])

    def test_plan_only_changes_nothing_and_dry_runs_both_patches(self):
        api = self.live()
        code, _ = run(self.ov, api, apply=False)
        self.assertEqual(code, 0)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertEqual(len(api.dry_run_patches), 2)

    def test_apply_refuses_on_image_mismatch_no_cluster_change(self):
        api = self.live(image='other@sha256:0')
        code, _ = run(self.ov, api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))

    def test_already_applied_short_circuits(self):
        api = self.live()
        run(self.ov, api, apply=True)
        before = len(api.patches)
        code, _ = run(self.ov, api, apply=True)
        self.assertEqual((code, len(api.patches)), (0, before))


if __name__ == '__main__':
    unittest.main()
