"""Apply the nccl_ep.py contiguity fix to the live deepinfer-v4-1-flash engine as a single-file,
immutable ConfigMap overlay (gpu-stack/runtime-overlays/deepinfer-nccl-ep-contiguous), through the
pipeline's own k8s_token route. AGENTS.md forbids kubectl as the release mechanism for the running
engine, so this never shells out to kubectl: every call is a plain REST request against the
Kubernetes API (or its Rancher cluster proxy), the same way scripts/rollout_dsh_sources.py already
talks to the cluster for the other DSH components.

Root cause and test coverage: ledger LANE6-CRASHLOOP-ROOTCAUSE-20261112 and
LANE6-NCCL-EP-CONTIGUOUS-FIX-20261112 (NcclEPBuffer._all_to_all crashed with "Tensors must be
contiguous" on a small/irregular batch; a CPU-only Job later confirmed the new regression test
fails on the unpatched file and passes on the patched one, 6 existing cases unaffected either way;
see LANE6-NCCL-EP-OVERLAY-AND-TEST-CONFIRM-20261112).

Dry run by default; --apply changes the cluster. In plan mode, both the successor patch (02) and
the rollback patch (03) are additionally sent to the API server with dryRun=All (the REST
equivalent of kubectl's --dry-run=server), so the rollback is proven well-formed before it is ever
needed, not only discovered after a failed apply. Refuses (no cluster change) unless: the live
image digest and Deployment shape are exactly what this script was written against, the overlay
is not already applied, and nothing else already occupies the target mount path. On any
verification failure after applying, automatically re-patches the Deployment to remove the
overlay and waits for that rollback to become Ready too -- the same shape as
scripts/rollout_dsh_sources.py's litellm-sidecar rollback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / 'gpu-stack' / 'runtime-overlays' / 'deepinfer-nccl-ep-contiguous' / 'nccl_ep.py'

NAMESPACE_DEFAULT = 'llm'
DEPLOYMENT = 'deepinfer-v4-1-flash'
CONTAINER = 'deepinfer'
VOLUME = 'nccl-ep-contiguous-successor'
MOUNT_PATH = '/work/runtime/deepinfer/model_executor/parallel_utils/nccl_ep.py'
SUBPATH = 'nccl_ep.py'

# Pinned identities (ledger LANE6-NCCL-EP-OVERLAY-AND-TEST-CONFIRM-20261112). A mismatch between
# EXPECTED_SHA256 and the file actually on disk refuses before touching the cluster: it means this
# script is stale relative to the overlay directory it ships next to.
PREDECESSOR_COMMIT = 'a06c8ff46d390d462466deac588e24766cd67b97'
EXPECTED_SHA256 = '885c972713d6783862c9cb337ff5b373c095e089d3ec2bb12f5fe780122339df'
EXPECTED_IMAGE = 'lmsysorg/sglang@sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860'
CONFIG_MAP_NAME = 'deepinfer-nccl-ep-contiguous-%s-%s' % (PREDECESSOR_COMMIT[:7], EXPECTED_SHA256[:8])
SOURCE_ANNOTATION = 'dsh.bot.or.th/nccl-ep-contiguous-source'
SHA_ANNOTATION = 'dsh.bot.or.th/nccl-ep-contiguous-sha256'

SECRET_NAME = re.compile(r'TOKEN|SECRET|PASSWORD|KEY|CRED', re.IGNORECASE)


class Api:
    def __init__(self, base, token, namespace, ca_file=None):
        self.base, self.token, self.namespace = base.rstrip('/'), token, namespace
        self.tls = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()

    def call(self, method, path, body=None, content='application/json'):
        request = urllib.request.Request(self.base + path, method=method,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': content})
        try:
            with urllib.request.urlopen(request, context=self.tls, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and method == 'GET':
                return None
            raise RuntimeError(method + ' ' + path.split('?')[0] + ': HTTP ' + str(error.code)) from None

    def deployment(self, name):
        return self.call('GET', f'/apis/apps/v1/namespaces/{self.namespace}/deployments/{name}')

    def config_map(self, name):
        return self.call('GET', f'/api/v1/namespaces/{self.namespace}/configmaps/{name}')

    def create_config_map(self, document):
        return self.call('POST', f'/api/v1/namespaces/{self.namespace}/configmaps', document)

    def patch_deployment(self, name, patch, dry_run=False):
        path = f'/apis/apps/v1/namespaces/{self.namespace}/deployments/{name}'
        if dry_run:
            path += '?dryRun=All'
        return self.call('PATCH', path, patch, 'application/strategic-merge-patch+json')


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load_successor_content(path: Path = SOURCE_FILE) -> str:
    content = path.read_text(encoding='utf-8')
    digest = text_sha256(content)
    if digest != EXPECTED_SHA256:
        raise RuntimeError(
            f'{path} does not match the reviewed successor hash: got {digest}, expected {EXPECTED_SHA256}. '
            'Refusing: this script is stale relative to the overlay it ships next to.')
    return content


def build_config_map(content: str, namespace: str) -> dict:
    return {
        'apiVersion': 'v1',
        'kind': 'ConfigMap',
        'metadata': {
            'name': CONFIG_MAP_NAME,
            'namespace': namespace,
            'annotations': {SOURCE_ANNOTATION: PREDECESSOR_COMMIT, SHA_ANNOTATION: EXPECTED_SHA256},
        },
        'immutable': True,
        'data': {SUBPATH: content},
    }


def successor_patch() -> dict:
    return {
        'spec': {
            'template': {
                'metadata': {'annotations': {SOURCE_ANNOTATION: PREDECESSOR_COMMIT, SHA_ANNOTATION: EXPECTED_SHA256}},
                'spec': {
                    'containers': [{
                        'name': CONTAINER,
                        'volumeMounts': [{'name': VOLUME, 'mountPath': MOUNT_PATH, 'subPath': SUBPATH, 'readOnly': True}],
                    }],
                    'volumes': [{'name': VOLUME, 'configMap': {'name': CONFIG_MAP_NAME, 'defaultMode': 292}}],
                },
            },
        },
    }


def rollback_patch() -> dict:
    return {
        'spec': {
            'template': {
                'metadata': {'annotations': {SOURCE_ANNOTATION: None, SHA_ANNOTATION: None}},
                'spec': {
                    # v1.Container.VolumeMounts' strategic-merge patchMergeKey is mountPath, not
                    # name (only v1.PodSpec.Volumes merges by name) -- a name-keyed delete entry
                    # here would not match the live mount at all. Found by lane 9's review,
                    # LANE9-CHECK-LANE6-NCCL-EP-OVERLAY-35914744-ROLLBACK-MERGE-KEY.
                    'containers': [{'name': CONTAINER, 'volumeMounts': [{'mountPath': MOUNT_PATH, '$patch': 'delete'}]}],
                    'volumes': [{'name': VOLUME, '$patch': 'delete'}],
                },
            },
        },
    }


def redact_deployment(deployment: dict) -> dict:
    document = json.loads(json.dumps(deployment))
    for container in document.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
        for env in container.get('env', []) or []:
            if 'value' in env and SECRET_NAME.search(env.get('name', '')):
                env['value'] = '<redacted>'
    return document


def find_container(deployment: dict, name: str) -> dict | None:
    for container in deployment['spec']['template']['spec'].get('containers', []):
        if container['name'] == name:
            return container
    return None


def deployment_shape(deployment: dict) -> dict:
    spec = deployment['spec']
    return {
        'replicas': spec.get('replicas'),
        'strategy': (spec.get('strategy') or {}).get('type'),
        'containers': sorted(c['name'] for c in spec['template']['spec'].get('containers', [])),
    }


def overlay_already_applied(deployment: dict) -> bool:
    container = find_container(deployment, CONTAINER)
    if not container:
        return False
    mounts = [m for m in (container.get('volumeMounts') or []) if m.get('name') == VOLUME]
    volumes = [v for v in deployment['spec']['template']['spec'].get('volumes', []) if v.get('name') == VOLUME]
    if not mounts or not volumes:
        return False
    return (mounts[0].get('mountPath') == MOUNT_PATH and mounts[0].get('subPath') == SUBPATH and
            volumes[0].get('configMap', {}).get('name') == CONFIG_MAP_NAME)


def mount_path_collision(deployment: dict) -> str | None:
    """Another volumeMount already at MOUNT_PATH under a different name -- a different overlay or hand
    edit already lives there, and this script must not silently pile another mount on top of it."""
    container = find_container(deployment, CONTAINER)
    if not container:
        return None
    for mount in container.get('volumeMounts') or []:
        if mount.get('mountPath') == MOUNT_PATH and mount.get('name') != VOLUME:
            return mount.get('name')
    return None


def wait_ready(api: Api, name: str, timeout: int = 1200, settle: int = 60, sleep=time.sleep) -> bool:
    """Wait until the new revision is the only one and stays ready without restarts."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = api.deployment(name)
        s, want = d.get('status', {}), d['spec'].get('replicas', 1)
        if (s.get('observedGeneration', 0) >= d['metadata']['generation'] and s.get('updatedReplicas', 0) == want and
                s.get('readyReplicas', 0) == want and s.get('replicas', 0) == want and s.get('unavailableReplicas', 0) == 0):
            sleep(settle)
            d = api.deployment(name)
            s = d.get('status', {})
            if s.get('readyReplicas', 0) == want and s.get('unavailableReplicas', 0) == 0:
                return True
        sleep(5)
    return False


def _write_evidence(directory: str, name: str, payload: dict) -> None:
    if not directory:
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')


def verify_rollout(api: Api, log=print) -> tuple[bool, dict]:
    """REST-only checks after the rollout: no exec, no reading the container filesystem. The
    ConfigMap's name is content-addressed and immutable, so confirming the pod spec references
    that exact name is, together with an independent re-hash of the stored ConfigMap data, as good
    a guarantee of the mounted bytes as reading the file from inside the container would be."""
    evidence: dict = {}
    deployment = api.deployment(DEPLOYMENT)
    container = find_container(deployment, CONTAINER)
    evidence['imageUnchanged'] = bool(container) and container.get('image') == EXPECTED_IMAGE
    evidence['imageSeen'] = container.get('image') if container else None
    mounts = [m for m in (container.get('volumeMounts') or [])] if container else []
    mount = next((m for m in mounts if m.get('name') == VOLUME), None)
    evidence['mountWiredCorrectly'] = bool(
        mount and mount.get('mountPath') == MOUNT_PATH and mount.get('subPath') == SUBPATH and mount.get('readOnly') is True)
    volumes = deployment['spec']['template']['spec'].get('volumes', [])
    volume = next((v for v in volumes if v.get('name') == VOLUME), None)
    evidence['podReferencesExpectedConfigMap'] = bool(volume and volume.get('configMap', {}).get('name') == CONFIG_MAP_NAME)
    stored = api.config_map(CONFIG_MAP_NAME)
    stored_sha = text_sha256(stored['data'][SUBPATH]) if stored and SUBPATH in (stored.get('data') or {}) else None
    evidence['storedConfigMapShaMatches'] = stored_sha == EXPECTED_SHA256
    evidence['storedConfigMapImmutable'] = bool(stored and stored.get('immutable') is True)
    result = all([evidence['imageUnchanged'], evidence['mountWiredCorrectly'],
                   evidence['podReferencesExpectedConfigMap'], evidence['storedConfigMapShaMatches'],
                   evidence['storedConfigMapImmutable']])
    log(json.dumps({'overlayVerification': result, **evidence}))
    return result, evidence


def dry_run_patches(api: Api, log=print) -> dict:
    """Server-side dry run (dryRun=All, the REST equivalent of kubectl's --dry-run=server) of both
    02-successor-patch and 03-rollback-patch against the live Deployment, proving the rollback
    patch is well-formed and accepted BEFORE it is ever needed, not only after a failed apply.
    Nothing is persisted either way; a failure here is recorded, never raised, since this runs
    inside plan mode and must never block a plan-only report."""
    result: dict = {}
    for label, patch in (('successorPatchDryRunAccepted', successor_patch()), ('rollbackPatchDryRunAccepted', rollback_patch())):
        try:
            api.patch_deployment(DEPLOYMENT, patch, dry_run=True)
            result[label] = True
        except Exception as error:  # noqa: BLE001 - recorded, never raised, from inside a plan-only report
            result[label] = False
            result[label.replace('Accepted', 'Error')] = str(error)[:300]
    log(json.dumps({'dryRun': result}))
    return result


def plan_and_apply(api: Api, args, log=print, sleep=time.sleep) -> int:
    evidence_dir = getattr(args, 'evidence_dir', None)
    deployment = api.deployment(DEPLOYMENT)
    if not deployment:
        raise RuntimeError('Deployment not found: ' + DEPLOYMENT)
    content = load_successor_content()
    already = overlay_already_applied(deployment)
    collision = mount_path_collision(deployment)
    container = find_container(deployment, CONTAINER)
    image_ok = bool(container) and container.get('image') == EXPECTED_IMAGE
    shape = deployment_shape(deployment)
    shape_ok = shape['replicas'] == 1 and shape['strategy'] == 'Recreate' and CONTAINER in shape['containers']
    plan = {
        'deployment': DEPLOYMENT, 'configMap': CONFIG_MAP_NAME, 'mountPath': MOUNT_PATH,
        'successorSha256': EXPECTED_SHA256, 'expectedImage': EXPECTED_IMAGE, 'imageSeen': container.get('image') if container else None,
        'imageOk': image_ok, 'deploymentShape': shape, 'deploymentShapeOk': shape_ok,
        'alreadyApplied': already, 'mountPathCollision': collision, 'apply': bool(args.apply),
        'note': 'Recreate: a new volumeMount recreates the pod; expect ~7-8 min outage, same as the admin restart control quotes',
    }
    log(json.dumps(plan))
    _write_evidence(evidence_dir, 'plan.json', plan)
    if not args.apply:
        dry_run = dry_run_patches(api, log=log)
        _write_evidence(evidence_dir, 'dry-run.json', dry_run)
        if already:
            log('Overlay already applied with the expected ConfigMap and mount; nothing to do.')
        return 0
    if already:
        log('Overlay already applied with the expected ConfigMap and mount; nothing to do.')
        return 0
    problems = []
    if not image_ok:
        problems.append('Live image is not the exact digest this script was written against: ' + str(container.get('image') if container else None))
    if not shape_ok:
        problems.append('Deployment shape is not replicas 1, strategy Recreate with container ' + CONTAINER)
    if collision:
        problems.append('Mount path already used by a different volume: ' + collision)
    if problems:
        log('REFUSED: ' + '; '.join(problems))
        _write_evidence(evidence_dir, 'refused.json', {'problems': problems})
        return 1
    _write_evidence(evidence_dir, 'deployment-before.json', redact_deployment(deployment))
    document = build_config_map(content, args.namespace)
    existing = api.config_map(CONFIG_MAP_NAME)
    if existing is None:
        api.create_config_map(document)
    elif existing.get('data') != document['data']:
        raise RuntimeError('A different ConfigMap already uses this content-addressed name')
    timeout = getattr(args, 'timeout', 1200)
    api.patch_deployment(DEPLOYMENT, successor_patch())
    good = wait_ready(api, DEPLOYMENT, timeout=timeout, settle=args.settle, sleep=sleep)
    evidence: dict = {}
    if good:
        good, evidence = verify_rollout(api, log=log)
    _write_evidence(evidence_dir, 'verification.json', {'passed': bool(good), 'configMap': CONFIG_MAP_NAME, **evidence})
    if good:
        _write_evidence(evidence_dir, 'deployment-after.json', redact_deployment(api.deployment(DEPLOYMENT)))
        log(f'Applied the nccl_ep.py contiguity overlay to {DEPLOYMENT}.')
        return 0
    log(f'Rollout failed verification; removing the overlay from {DEPLOYMENT}.')
    api.patch_deployment(DEPLOYMENT, rollback_patch())
    restored = wait_ready(api, DEPLOYMENT, timeout=timeout, settle=args.settle, sleep=sleep)
    log('Rollback ' + ('completed.' if restored else 'did NOT become ready; investigate now.'))
    _write_evidence(evidence_dir, 'rollback.json', {'restored': bool(restored)})
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Change the cluster. Without it, only report the plan.')
    parser.add_argument('--api', default=os.environ.get('DSH_K8S_API', ''),
                        help='Kubernetes API base URL (for example the Rancher cluster proxy).')
    parser.add_argument('--token-file', default=os.environ.get('DSH_K8S_TOKEN_FILE', ''))
    parser.add_argument('--ca-file', default=os.environ.get('DSH_K8S_CA_FILE') or None)
    parser.add_argument('--namespace', default=NAMESPACE_DEFAULT)
    parser.add_argument('--settle', type=int, default=60)
    parser.add_argument('--timeout', type=int, default=1200, help='Seconds to wait for the rollout (and the rollback) to become Ready.')
    parser.add_argument('--evidence-dir', default='',
                        help='Write plan, before/after and verification JSON here (secret-like env values redacted).')
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text().strip() if args.token_file else os.environ.get('DSH_K8S_TOKEN', '').strip()
    if not args.api.startswith('https://') or len(token) < 20:
        raise SystemExit('An https Kubernetes API URL and a deploy token are required.')
    api = Api(args.api, token, args.namespace, args.ca_file)
    return plan_and_apply(api, args)


if __name__ == '__main__':
    raise SystemExit(main())
