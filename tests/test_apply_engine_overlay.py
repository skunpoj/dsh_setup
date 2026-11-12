import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import apply_engine_overlay as o  # noqa: E402


def _merge_keyed_list(existing, patch_list, key):
    """Minimal strategic-merge-patch semantics for a list keyed on `key`: add/replace by that
    key's value, $patch: delete removes the matching entry. Real v1.Container.VolumeMounts merges
    on mountPath; v1.PodSpec.Volumes merges on name -- using the wrong key for either is exactly
    the bug lane 9 found (LANE9-CHECK-LANE6-NCCL-EP-OVERLAY-35914744-ROLLBACK-MERGE-KEY), so this
    fake deliberately keys each list the way the real API server does rather than always using
    'name', or it would not have caught that bug either."""
    out = list(existing)
    for item in patch_list:
        value = item.get(key)
        out = [e for e in out if e.get(key) != value]
        if item.get('$patch') != 'delete':
            out.append({k: v for k, v in item.items() if k != '$patch'})
    return out


class FakeApi:
    def __init__(self, ready=True, image=o.EXPECTED_IMAGE, replicas=1, strategy='Recreate',
                 pre_existing_mount=None):
        self.ready = ready
        self.maps = {}
        container = {'name': o.CONTAINER, 'image': image, 'volumeMounts': []}
        if pre_existing_mount:
            container['volumeMounts'].append(pre_existing_mount)
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
            # A real dryRun=All PATCH is still schema-validated server-side but never persisted;
            # the fake mirrors that by recording the attempt and returning without mutating state.
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


def run(api, apply=False, evidence_dir=None):
    args = Args()
    args.apply, args.evidence_dir = apply, evidence_dir
    lines = []
    code = o.plan_and_apply(api, args, log=lines.append, sleep=lambda *_: None)
    return code, lines


class PureFunctionTests(unittest.TestCase):
    def test_successor_content_on_disk_matches_the_pinned_hash(self):
        # Guards against someone editing the shipped overlay file without updating the constant.
        content = o.load_successor_content()
        self.assertEqual(o.text_sha256(content), o.EXPECTED_SHA256)

    def test_build_config_map_is_immutable_and_content_addressed(self):
        doc = o.build_config_map('x' * 10, 'llm')
        self.assertTrue(doc['immutable'])
        self.assertEqual(doc['metadata']['name'], o.CONFIG_MAP_NAME)
        self.assertIn(o.PREDECESSOR_COMMIT[:7], doc['metadata']['name'])
        self.assertIn(o.EXPECTED_SHA256[:8], doc['metadata']['name'])

    def test_load_successor_content_refuses_a_file_not_matching_the_pinned_hash(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.py', delete=False) as f:
            f.write('not the reviewed content\n')
            path = Path(f.name)
        try:
            with self.assertRaises(RuntimeError):
                o.load_successor_content(path)
        finally:
            path.unlink()

    def test_successor_and_rollback_patch_are_inverse_shaped(self):
        succ, roll = o.successor_patch(), o.rollback_patch()
        succ_mount = succ['spec']['template']['spec']['containers'][0]['volumeMounts'][0]
        roll_mount = roll['spec']['template']['spec']['containers'][0]['volumeMounts'][0]
        self.assertEqual(succ_mount['mountPath'], o.MOUNT_PATH)
        # Container volumeMounts merge/delete by mountPath, not name -- the rollback entry must key
        # on mountPath (lane 9, LANE9-CHECK-LANE6-NCCL-EP-OVERLAY-35914744-ROLLBACK-MERGE-KEY) or it
        # would silently fail to match the live mount at all.
        self.assertEqual(roll_mount, {'mountPath': o.MOUNT_PATH, '$patch': 'delete'})
        self.assertNotIn('name', roll_mount)
        roll_volume = roll['spec']['template']['spec']['volumes'][0]
        self.assertEqual(roll_volume, {'name': o.VOLUME, '$patch': 'delete'})
        self.assertEqual(roll['spec']['template']['spec']['volumes'][0]['$patch'], 'delete')
        for key in (o.SOURCE_ANNOTATION, o.SHA_ANNOTATION):
            self.assertIn(key, succ['spec']['template']['metadata']['annotations'])
            self.assertIsNone(roll['spec']['template']['metadata']['annotations'][key])

    def test_config_map_document_is_immutable(self):
        self.assertIs(o.build_config_map('x' * 10, 'llm')['immutable'], True)

    def test_dry_run_patch_deployment_appends_query_param(self):
        # Api.patch_deployment itself (not the fake) must append ?dryRun=All.
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


class DetectionTests(unittest.TestCase):
    def test_overlay_not_applied_on_a_fresh_deployment(self):
        self.assertFalse(o.overlay_already_applied(FakeApi().dep))

    def test_overlay_detected_once_applied(self):
        api = FakeApi()
        run(api, apply=True)
        self.assertTrue(o.overlay_already_applied(api.dep))

    def test_mount_path_collision_detected(self):
        colliding = {'name': 'some-other-overlay', 'mountPath': o.MOUNT_PATH, 'subPath': 'x'}
        api = FakeApi(pre_existing_mount=colliding)
        self.assertEqual(o.mount_path_collision(api.dep), 'some-other-overlay')

    def test_no_collision_when_mount_absent(self):
        self.assertIsNone(o.mount_path_collision(FakeApi().dep))


class PlanAndApplyTests(unittest.TestCase):
    def test_plan_only_changes_nothing(self):
        api = FakeApi()
        code, lines = run(api, apply=False)
        self.assertEqual(code, 0)
        self.assertEqual((api.patches, api.created), ([], []))
        plan = json.loads(lines[0])
        self.assertEqual((plan['imageOk'], plan['deploymentShapeOk'], plan['alreadyApplied'], plan['apply']), (True, True, False, False))

    def test_plan_mode_dry_runs_both_the_successor_and_rollback_patch(self):
        api = FakeApi()
        code, lines = run(api, apply=False)
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
        code, lines = run(api, apply=False)
        self.assertEqual(code, 0, 'a dry-run failure must not break a plan-only report')
        dry_run = json.loads(lines[-1])['dryRun']
        self.assertFalse(dry_run['successorPatchDryRunAccepted'])
        self.assertIn('HTTP 422', dry_run['successorPatchDryRunError'])

    def test_already_applied_short_circuits(self):
        api = FakeApi()
        run(api, apply=True)
        patches_before = len(api.patches)
        code, lines = run(api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(api.patches), patches_before, 'no new patch when already applied')
        self.assertIn('Overlay already applied', lines[-1])

    def test_apply_refuses_on_image_mismatch_no_cluster_change(self):
        api = FakeApi(image='lmsysorg/sglang@sha256:deadbeef')
        code, lines = run(api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('REFUSED', lines[-1])
        self.assertIn('exact digest', lines[-1])

    def test_apply_refuses_on_wrong_strategy_no_cluster_change(self):
        api = FakeApi(strategy='RollingUpdate')
        code, lines = run(api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('REFUSED', lines[-1])

    def test_apply_refuses_on_mount_collision_no_cluster_change(self):
        colliding = {'name': 'some-other-overlay', 'mountPath': o.MOUNT_PATH, 'subPath': 'x'}
        api = FakeApi(pre_existing_mount=colliding)
        code, lines = run(api, apply=True)
        self.assertEqual(code, 1)
        self.assertEqual((api.patches, api.created), ([], []))
        self.assertIn('Mount path already used', lines[-1])

    def test_successful_apply_creates_configmap_patches_and_verifies(self):
        api = FakeApi()
        code, lines = run(api, apply=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(api.created), 1)
        self.assertEqual(api.created[0]['metadata']['name'], o.CONFIG_MAP_NAME)
        self.assertTrue(o.overlay_already_applied(api.dep))
        self.assertTrue(any('overlayVerification' in line and json.loads(line)['overlayVerification'] for line in lines))

    def test_failed_readiness_rolls_back(self):
        api = FakeApi(ready=False)
        code, lines = run(api, apply=True)
        self.assertEqual(code, 1)
        self.assertFalse(o.overlay_already_applied(api.dep), 'rollback patch must remove the mount again')
        self.assertIn('Rollback', lines[-1])

    def test_evidence_is_written_for_a_successful_apply(self):
        api = FakeApi()
        evidence_dir = Path(__file__).parent / '_tmp_engine_overlay_evidence'
        try:
            run(api, apply=True, evidence_dir=str(evidence_dir))
            for name in ('plan.json', 'deployment-before.json', 'verification.json', 'deployment-after.json'):
                self.assertTrue((evidence_dir / name).exists(), name)
        finally:
            if evidence_dir.exists():
                for f in evidence_dir.iterdir():
                    f.unlink()
                evidence_dir.rmdir()


if __name__ == '__main__':
    unittest.main()
