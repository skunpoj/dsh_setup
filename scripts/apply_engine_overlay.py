"""Apply a named, reviewed engine overlay to the live deepinfer-v4-1-flash Deployment through the
pipeline's own k8s_token route. AGENTS.md forbids kubectl as the release mechanism for the running
engine, so this never shells out to kubectl: every call is a plain REST request against the
Kubernetes API (or its Rancher cluster proxy), the same way scripts/rollout_dsh_sources.py already
talks to the cluster for the other DSH components.

GENERALIZED from the single-purpose nccl_ep.py-only script (commit 28301c39, sha256 cd741320...)
to a small registry of named overlays, selected with --overlay. This was required because that
script hardcoded the NCCL overlay's source file, Deployment, container, volume, mount path and
ConfigMap name as module-level constants with no way to add a second overlay (ledger
CODEX-C5-ASR-OVERLAY-FIXED-EXECUTOR-EXACT-ANSWER-20261121: "Adding a folder or one array line will
NOT apply our changes"). Behaviour preservation: the 'nccl-ep-contiguous' overlay below reproduces
every constant, hash pin, patch shape and verification check from the original script byte-for-byte
in meaning -- see the inline note at NcclEpContiguousOverlay. Two new overlays are added for the
GPU-balance change set (LANE6-GPU-BALANCE-CHANGESET-READY-20261121, sha256 08bed5de...):
'asr-typhoon-inprocess' (ASR launcher + mounts, postStart hook, asr-enabled left untouched) and
'deepinfer-memory-trim' (the --gpu-memory-utilization 0.93 -> 0.915 command change).

Dry run by default; --apply changes the cluster. In plan mode, both the successor patch and the
rollback patch are additionally sent to the API server with dryRun=All (the REST equivalent of
kubectl's --dry-run=server), so the rollback is proven well-formed before it is ever needed, not
only discovered after a failed apply. Refuses (no cluster change) unless: the live image digest and
Deployment shape are exactly what the selected overlay was written against, the overlay is not
already applied, and nothing else already occupies the target mount path / command slot. On any
verification failure after applying, automatically re-patches the Deployment to remove the overlay
and waits for that rollback to become Ready too -- the same shape as
scripts/rollout_dsh_sources.py's litellm-sidecar rollback, and the same shape the original
single-purpose script used.

One overlay per invocation, by design: --overlay is required and takes exactly one of the names in
OVERLAYS below. This mirrors the existing per-stage, per-flag pattern in azure-pipelines.yml
(one commit-message flag gates one stage gates one overlay) rather than introducing a new
multi-overlay-per-run mode this change set does not need.
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
NAMESPACE_DEFAULT = 'llm'
DEPLOYMENT = 'deepinfer-v4-1-flash'
CONTAINER = 'deepinfer'
EXPECTED_IMAGE = 'lmsysorg/sglang@sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860'

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


def redact_deployment(deployment: dict) -> dict:
    document = json.loads(json.dumps(deployment))
    for container in document.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
        for env in container.get('env', []) or []:
            if 'value' in env and SECRET_NAME.search(env.get('name', '')):
                env['value'] = '<redacted>'
    return document


def wait_ready(api: Api, name: str, timeout: int = 1200, settle: int = 60, sleep=time.sleep) -> bool:
    """Wait until the new revision is the only one and stays ready without restarts. Unchanged from
    the original single-purpose script -- shared by every overlay, not overlay-specific."""
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


# --------------------------------------------------------------------------------------------
# Overlay interface. Each overlay owns its own pinned identities, its own successor/rollback
# patch shape, its own "already applied" / "collision" / "verify" checks -- deliberately NOT a
# fully generic "any JSON patch" system, so every overlay keeps the same safety guarantees the
# original script had (image pin, shape check, content/command hash pin, immutable-ConfigMap
# naming where applicable) rather than trading them away for genericity.
# --------------------------------------------------------------------------------------------
class Overlay:
    name: str

    def already_applied(self, deployment: dict) -> bool:
        raise NotImplementedError

    def collision(self, deployment: dict) -> str | None:
        return None

    def prepare(self, api: Api) -> None:
        """Side-effect-free pre-apply step (e.g. ensure a content-addressed ConfigMap exists).
        Overlays that reuse an existing, externally-managed ConfigMap (ASR) override this to a
        no-op plus an existence/hash check instead of creating anything."""
        return None

    def successor_patch(self) -> dict:
        raise NotImplementedError

    def rollback_patch(self) -> dict:
        raise NotImplementedError

    def verify(self, api: Api, log=print) -> tuple[bool, dict]:
        raise NotImplementedError

    def plan_extra(self, deployment: dict) -> dict:
        return {}


class NcclEpContiguousOverlay(Overlay):
    """Byte-identical in meaning to the original single-purpose script: same constants, same hash
    pins, same patch shapes (single-file subPath mount + content-addressed immutable ConfigMap),
    same verify_rollout checks. Only the names changed from module-level globals to attributes, so
    this class can live next to the two new overlays below without colliding."""
    name = 'nccl-ep-contiguous'

    SOURCE_FILE = ROOT / 'gpu-stack' / 'runtime-overlays' / 'deepinfer-nccl-ep-contiguous' / 'nccl_ep.py'
    VOLUME = 'nccl-ep-contiguous-successor'
    MOUNT_PATH = '/work/runtime/deepinfer/model_executor/parallel_utils/nccl_ep.py'
    SUBPATH = 'nccl_ep.py'
    PREDECESSOR_COMMIT = 'a06c8ff46d390d462466deac588e24766cd67b97'
    EXPECTED_SHA256 = '885c972713d6783862c9cb337ff5b373c095e089d3ec2bb12f5fe780122339df'
    SOURCE_ANNOTATION = 'dsh.bot.or.th/nccl-ep-contiguous-source'
    SHA_ANNOTATION = 'dsh.bot.or.th/nccl-ep-contiguous-sha256'

    @property
    def config_map_name(self) -> str:
        return 'deepinfer-nccl-ep-contiguous-%s-%s' % (self.PREDECESSOR_COMMIT[:7], self.EXPECTED_SHA256[:8])

    def load_successor_content(self, path: Path | None = None) -> str:
        # Name kept from the original single-purpose script's module-level function
        # (reconciled with the existing test_apply_engine_overlay.py, which calls this directly
        # to guard against someone editing the shipped overlay file without updating the hash).
        content = (path or self.SOURCE_FILE).read_text(encoding='utf-8')
        digest = text_sha256(content)
        if digest != self.EXPECTED_SHA256:
            raise RuntimeError(
                f'{path or self.SOURCE_FILE} does not match the reviewed successor hash: got {digest}, '
                f'expected {self.EXPECTED_SHA256}. Refusing: this script is stale relative to the '
                'overlay it ships next to.')
        return content

    def already_applied(self, deployment: dict) -> bool:
        container = find_container(deployment, CONTAINER)
        if not container:
            return False
        mounts = [m for m in (container.get('volumeMounts') or []) if m.get('name') == self.VOLUME]
        volumes = [v for v in deployment['spec']['template']['spec'].get('volumes', []) if v.get('name') == self.VOLUME]
        if not mounts or not volumes:
            return False
        return (mounts[0].get('mountPath') == self.MOUNT_PATH and mounts[0].get('subPath') == self.SUBPATH and
                volumes[0].get('configMap', {}).get('name') == self.config_map_name)

    def collision(self, deployment: dict) -> str | None:
        container = find_container(deployment, CONTAINER)
        if not container:
            return None
        for mount in container.get('volumeMounts') or []:
            if mount.get('mountPath') == self.MOUNT_PATH and mount.get('name') != self.VOLUME:
                return mount.get('name')
        return None

    def prepare(self, api: Api) -> None:
        content = self.load_successor_content()
        document = {
            'apiVersion': 'v1', 'kind': 'ConfigMap',
            'metadata': {'name': self.config_map_name, 'namespace': api.namespace,
                         'annotations': {self.SOURCE_ANNOTATION: self.PREDECESSOR_COMMIT, self.SHA_ANNOTATION: self.EXPECTED_SHA256}},
            'immutable': True, 'data': {self.SUBPATH: content},
        }
        existing = api.config_map(self.config_map_name)
        if existing is None:
            api.create_config_map(document)
        elif existing.get('data') != document['data']:
            raise RuntimeError('A different ConfigMap already uses this content-addressed name')

    def successor_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: self.PREDECESSOR_COMMIT, self.SHA_ANNOTATION: self.EXPECTED_SHA256}},
            'spec': {'containers': [{'name': CONTAINER, 'volumeMounts': [
                        {'name': self.VOLUME, 'mountPath': self.MOUNT_PATH, 'subPath': self.SUBPATH, 'readOnly': True}]}],
                     'volumes': [{'name': self.VOLUME, 'configMap': {'name': self.config_map_name, 'defaultMode': 292}}]}}}}

    def rollback_patch(self) -> dict:
        # v1.Container.VolumeMounts' strategic-merge patchMergeKey is mountPath, not name (only
        # v1.PodSpec.Volumes merges by name) -- unchanged from the original script's own comment
        # (lane 9's review, LANE9-CHECK-LANE6-NCCL-EP-OVERLAY-35914744-ROLLBACK-MERGE-KEY).
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: None, self.SHA_ANNOTATION: None}},
            'spec': {'containers': [{'name': CONTAINER, 'volumeMounts': [{'mountPath': self.MOUNT_PATH, '$patch': 'delete'}]}],
                     'volumes': [{'name': self.VOLUME, '$patch': 'delete'}]}}}}

    def verify(self, api: Api, log=print) -> tuple[bool, dict]:
        evidence: dict = {}
        deployment = api.deployment(DEPLOYMENT)
        container = find_container(deployment, CONTAINER)
        evidence['imageUnchanged'] = bool(container) and container.get('image') == EXPECTED_IMAGE
        evidence['imageSeen'] = container.get('image') if container else None
        mount = next((m for m in (container.get('volumeMounts') or []) if m.get('name') == self.VOLUME), None) if container else None
        evidence['mountWiredCorrectly'] = bool(
            mount and mount.get('mountPath') == self.MOUNT_PATH and mount.get('subPath') == self.SUBPATH and mount.get('readOnly') is True)
        volume = next((v for v in deployment['spec']['template']['spec'].get('volumes', []) if v.get('name') == self.VOLUME), None)
        evidence['podReferencesExpectedConfigMap'] = bool(volume and volume.get('configMap', {}).get('name') == self.config_map_name)
        stored = api.config_map(self.config_map_name)
        stored_sha = text_sha256(stored['data'][self.SUBPATH]) if stored and self.SUBPATH in (stored.get('data') or {}) else None
        evidence['storedConfigMapShaMatches'] = stored_sha == self.EXPECTED_SHA256
        evidence['storedConfigMapImmutable'] = bool(stored and stored.get('immutable') is True)
        result = all([evidence['imageUnchanged'], evidence['mountWiredCorrectly'],
                       evidence['podReferencesExpectedConfigMap'], evidence['storedConfigMapShaMatches'],
                       evidence['storedConfigMapImmutable']])
        log(json.dumps({'overlayVerification': result, **evidence}))
        return result, evidence

    def plan_extra(self, deployment: dict) -> dict:
        return {'configMap': self.config_map_name, 'mountPath': self.MOUNT_PATH, 'successorSha256': self.EXPECTED_SHA256}


class AsrTyphoonInprocessOverlay(Overlay):
    """ASR launcher + mounts (LANE6-ASR-1315-DIFF-20261121 / LANE6-GPU-BALANCE-CHANGESET-READY-
    20261121 section 2b). Reuses the EXISTING, externally-managed ConfigMap asr-worker-20261113
    (created 2026-11-13T03:30:56Z, toggled by the operator's own kubectl-apply pattern, not
    content-addressed) -- prepare() is a read-only existence+hash CHECK, never a create/own, since
    this script must not take over a ConfigMap another process owns and mutates (asr-enabled)."""
    name = 'asr-typhoon-inprocess'

    CONFIG_MAP_NAME = 'asr-worker-4w-afffd322'  # 24 Nov 2026: four-worker launcher; predecessor asr-worker-20261113 (two workers)
    PVC_NAME = 'asr-nas-record-prod'
    CONFIGMAP_VOLUME = 'asr-worker-successor'
    PVC_VOLUME = 'asr-record-successor'
    MOUNT_PATH = '/app-asr'
    PVC_MOUNT_PATH = '/1213'
    SOURCE_ANNOTATION = 'dsh.bot.or.th/asr-typhoon-inprocess-source'
    SHA_ANNOTATION = 'dsh.bot.or.th/asr-typhoon-inprocess-sha256'
    # Pin: confirmed identical to the live ConfigMap content, OPERATOR-DEEPSEEK-LIVE-ARGS-20261121.
    EXPECTED_LAUNCHER_SHA256 = '74a0e9db4762f6eade24370ee0e0ac4e17ec9943fcc91b8ff3966eb2772559dc'
    SOURCE_COMMIT = '2e3deed2d399f51c1b39789ae036055b64e94caf'
    POSTSTART_COMMAND = ['sh', '-c', 'sh /app-asr/asr-launcher.sh >/proc/1/fd/1 2>&1 &']

    def already_applied(self, deployment: dict) -> bool:
        container = find_container(deployment, CONTAINER)
        if not container:
            return False
        has_lifecycle = (container.get('lifecycle') or {}).get('postStart', {}).get('exec', {}).get('command') == self.POSTSTART_COMMAND
        mounts = {m.get('name'): m for m in (container.get('volumeMounts') or [])}
        return bool(has_lifecycle and self.CONFIGMAP_VOLUME in mounts and self.PVC_VOLUME in mounts)

    def collision(self, deployment: dict) -> str | None:
        container = find_container(deployment, CONTAINER)
        if not container:
            return None
        for mount in container.get('volumeMounts') or []:
            if mount.get('mountPath') in (self.MOUNT_PATH, self.PVC_MOUNT_PATH) and mount.get('name') not in (self.CONFIGMAP_VOLUME, self.PVC_VOLUME):
                return mount.get('name')
        existing = (container.get('lifecycle') or {}).get('postStart')
        if existing and existing.get('exec', {}).get('command') != self.POSTSTART_COMMAND:
            return 'existing postStart hook (not this overlay\'s)'
        return None

    def prepare(self, api: Api) -> None:
        stored = api.config_map(self.CONFIG_MAP_NAME)
        if stored is None:
            raise RuntimeError(f'ConfigMap {self.CONFIG_MAP_NAME} not found -- this overlay reuses an '
                                'externally-managed ConfigMap and will not create one.')
        data = stored.get('data') or {}
        if 'asr-launcher.sh' not in data:
            raise RuntimeError(f'ConfigMap {self.CONFIG_MAP_NAME} has no asr-launcher.sh key.')
        got = text_sha256(data['asr-launcher.sh'])
        if got != self.EXPECTED_LAUNCHER_SHA256:
            raise RuntimeError(f'Live ConfigMap asr-launcher.sh sha256 {got} does not match the '
                                f'pinned {self.EXPECTED_LAUNCHER_SHA256} -- refusing to wire a mount to '
                                'content that moved since this overlay was reviewed.')

    def successor_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: self.SOURCE_COMMIT, self.SHA_ANNOTATION: self.EXPECTED_LAUNCHER_SHA256}},
            'spec': {'containers': [{'name': CONTAINER,
                        'lifecycle': {'postStart': {'exec': {'command': self.POSTSTART_COMMAND}}},
                        'volumeMounts': [
                            {'name': self.CONFIGMAP_VOLUME, 'mountPath': self.MOUNT_PATH, 'readOnly': True},
                            {'name': self.PVC_VOLUME, 'mountPath': self.PVC_MOUNT_PATH, 'readOnly': True}]}],
                     'volumes': [
                        {'name': self.CONFIGMAP_VOLUME, 'configMap': {'name': self.CONFIG_MAP_NAME}},
                        {'name': self.PVC_VOLUME, 'persistentVolumeClaim': {'claimName': self.PVC_NAME, 'readOnly': True}}]}}}}

    def rollback_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: None, self.SHA_ANNOTATION: None}},
            'spec': {'containers': [{'name': CONTAINER,
                        'lifecycle': {'$patch': 'delete'},
                        'volumeMounts': [{'mountPath': self.MOUNT_PATH, '$patch': 'delete'},
                                          {'mountPath': self.PVC_MOUNT_PATH, '$patch': 'delete'}]}],
                     'volumes': [{'name': self.CONFIGMAP_VOLUME, '$patch': 'delete'},
                                 {'name': self.PVC_VOLUME, '$patch': 'delete'}]}}}}

    def verify(self, api: Api, log=print) -> tuple[bool, dict]:
        evidence: dict = {}
        deployment = api.deployment(DEPLOYMENT)
        container = find_container(deployment, CONTAINER)
        evidence['imageUnchanged'] = bool(container) and container.get('image') == EXPECTED_IMAGE
        evidence['postStartWired'] = bool(container) and (container.get('lifecycle') or {}).get('postStart', {}).get('exec', {}).get('command') == self.POSTSTART_COMMAND
        mounts = {m.get('name'): m for m in (container.get('volumeMounts') or [])} if container else {}
        evidence['configMapMountWired'] = bool(mounts.get(self.CONFIGMAP_VOLUME, {}).get('mountPath') == self.MOUNT_PATH)
        evidence['pvcMountWired'] = bool(mounts.get(self.PVC_VOLUME, {}).get('mountPath') == self.PVC_MOUNT_PATH)
        stored = api.config_map(self.CONFIG_MAP_NAME)
        got_sha = text_sha256(stored['data']['asr-launcher.sh']) if stored and 'asr-launcher.sh' in (stored.get('data') or {}) else None
        evidence['liveConfigMapShaStillMatches'] = got_sha == self.EXPECTED_LAUNCHER_SHA256
        result = all([evidence['imageUnchanged'], evidence['postStartWired'], evidence['configMapMountWired'],
                       evidence['pvcMountWired'], evidence['liveConfigMapShaStillMatches']])
        log(json.dumps({'overlayVerification': result, **evidence}))
        return result, evidence

    def plan_extra(self, deployment: dict) -> dict:
        return {'configMap': self.CONFIG_MAP_NAME, 'mountPath': self.MOUNT_PATH,
                'note': 'asr-enabled is NOT touched by this overlay; it stays at its current ConfigMap value'}


class DeepinferMemoryTrimOverlay(Overlay):
    """--gpu-memory-utilization 0.93 -> 0.915 (LANE6-GPU-BALANCE-CHANGESET-READY-20261121 section
    2a). Unlike the other two overlays, there is no existing source location for this flag to
    diff against (confirmed: the live Deployment base manifest is not in the GPU_server export at
    all) -- the ONLY safe mechanism is a full `command` replacement, verified byte-for-byte against
    a live readback before being pinned here, not derived from a stale snapshot."""
    name = 'deepinfer-memory-trim'

    SOURCE_ANNOTATION = 'dsh.bot.or.th/deepinfer-memory-trim-source'
    SHA_ANNOTATION = 'dsh.bot.or.th/deepinfer-memory-trim-sha256'
    # Pinned verbatim from OPERATOR-DEEPSEEK-LIVE-ARGS-20261121 (outputs/lane2-deepseek-live-args-
    # 20261121/RAW_FINDINGS.txt), confirmed byte-exact except the one flag value (see
    # LANE6-GPU-BALANCE-CHANGESET-READY-20261121's own diff verification).
    PRIOR_COMMAND = (
        "exec python3 -u serve/openai_server.py --model /models/huggingface/hub/models--deepseek-ai--"
        "DeepSeek-V4.1-Flash-1017/snapshots/1bae0e1088993b9b82de08f59de5be5a34e42170 --served-model-name "
        "deepseek-v4.1-flash --dp 4 --port 8000 --hicache-size-gb 0 --gpu-memory-utilization 0.93 "
        "--max-num-batched-tokens 1024 --thinking-mode chat --yoco-keep-tokens 0 --prefill-any-interval 2 "
        "--max-model-len 393216 --max-num-seqs 4 --rank-heartbeat-timeout 120 --routing least-loaded")
    # ORCH-GO-OPTION-A-0915-CTX-131072-ONE-ATTEMPT: 0.915 alone leaves a ~0.98 GiB KV pool (needs 12,294 blocks at ctx 393216,
    # gets 9,226); with --max-model-len 131072 the vote needs 4,102 blocks, so the pool fits.
    NEW_COMMAND = PRIOR_COMMAND.replace('--gpu-memory-utilization 0.93', '--gpu-memory-utilization 0.915').replace(
        '--max-model-len 393216', '--max-model-len 131072')
    EXPECTED_PRIOR_SHA256 = hashlib.sha256(PRIOR_COMMAND.encode()).hexdigest()
    EXPECTED_NEW_SHA256 = hashlib.sha256(NEW_COMMAND.encode()).hexdigest()
    SOURCE_COMMIT = '2e3deed2d399f51c1b39789ae036055b64e94caf'

    def already_applied(self, deployment: dict) -> bool:
        container = find_container(deployment, CONTAINER)
        if not container:
            return False
        command = container.get('command') or []
        return len(command) == 3 and command[-1] == self.NEW_COMMAND

    def collision(self, deployment: dict) -> str | None:
        container = find_container(deployment, CONTAINER)
        if not container:
            return None
        command = container.get('command') or []
        current = command[-1] if command else None
        if current not in (self.PRIOR_COMMAND, self.NEW_COMMAND):
            return 'live command does not match the pinned prior string -- refusing a blind command replacement'
        return None

    def successor_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: self.SOURCE_COMMIT, self.SHA_ANNOTATION: self.EXPECTED_NEW_SHA256}},
            'spec': {'containers': [{'name': CONTAINER, 'command': ['sh', '-c', self.NEW_COMMAND]}]}}}}

    def rollback_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: None, self.SHA_ANNOTATION: None}},
            'spec': {'containers': [{'name': CONTAINER, 'command': ['sh', '-c', self.PRIOR_COMMAND]}]}}}}

    def verify(self, api: Api, log=print) -> tuple[bool, dict]:
        evidence: dict = {}
        deployment = api.deployment(DEPLOYMENT)
        container = find_container(deployment, CONTAINER)
        evidence['imageUnchanged'] = bool(container) and container.get('image') == EXPECTED_IMAGE
        command = (container.get('command') or []) if container else []
        evidence['commandMatchesNew'] = bool(command) and command[-1] == self.NEW_COMMAND
        evidence['readyRanksFour'] = None  # filled by the caller's own /health check; this script makes no exec/HTTP call into the container itself
        result = all([evidence['imageUnchanged'], evidence['commandMatchesNew']])
        log(json.dumps({'overlayVerification': result, **evidence}))
        return result, evidence

    def plan_extra(self, deployment: dict) -> dict:
        return {'flagChange': '--gpu-memory-utilization 0.93 -> 0.915', 'newCommandSha256': self.EXPECTED_NEW_SHA256,
                'note': 'Pod restart required (command change); confirm ready_ranks:4 and run '
                        'LANE6-GPU-POSTAPPLY-CHECKS-20261121 after this overlay, not just this script\'s own verify()'}


class DeepseekThinkingLowOverlay(Overlay):
    """DeepSeek default = thinking ON at LOW reasoning effort (ORCH-DEEPSEEK-DEFAULT-CHANGE-AND-DOCS-ORDER; verified
    in LANE6-DEEPSEEK-VISION-LOW-THINKING-VERIFY-20261122). Vision needs NO change: the checkpoint's ViT is already
    served. Two changes in ONE patch (one pod recreation):
      1. serve/openai_server.py is replaced through a content-addressed immutable ConfigMap + single-file subPath mount
         (the NcclEp pattern): the successor only adds --reasoning-effort (default "high" = today's behaviour) and passes
         reasoning_effort to the checkpoint's encode_messages; the PREDECESSOR is the live file, sha256 pinned below.
      2. the container command: '--thinking-mode chat' -> '--thinking-mode thinking --reasoning-effort low' (every other
         token pinned to the live post-memory-trim command, byte for byte).
    A request that sends chat_template_kwargs.thinking=false (SMP does) still gets plain chat mode."""
    name = 'deepseek-thinking-low'

    SOURCE_FILE = ROOT / 'gpu-stack' / 'runtime-overlays' / 'deepinfer-reasoning-effort' / 'openai_server.py'
    VOLUME = 'reasoning-effort-successor'
    MOUNT_PATH = '/work/runtime/serve/openai_server.py'
    SUBPATH = 'openai_server.py'
    PREDECESSOR_SHA256 = 'fa20ca45acc7f561aa6106d68792933376a0daada8f14ad3bc91051f8e42cfde'
    EXPECTED_SHA256 = '68d6776843dff30f58f99234d14852fbe8fef03cc97f53382402e0e3901113fb'
    SOURCE_ANNOTATION = 'dsh.bot.or.th/reasoning-effort-source-predecessor-sha256'
    SHA_ANNOTATION = 'dsh.bot.or.th/reasoning-effort-sha256'
    PRIOR_COMMAND = DeepinferMemoryTrimOverlay.NEW_COMMAND
    NEW_COMMAND = PRIOR_COMMAND.replace('--thinking-mode chat', '--thinking-mode thinking --reasoning-effort low')
    EXPECTED_NEW_COMMAND_SHA256 = hashlib.sha256(NEW_COMMAND.encode()).hexdigest()

    @property
    def config_map_name(self) -> str:
        return 'deepinfer-reasoning-effort-%s-%s' % (self.PREDECESSOR_SHA256[:8], self.EXPECTED_SHA256[:8])

    def load_successor_content(self, path: Path | None = None) -> str:
        content = (path or self.SOURCE_FILE).read_text(encoding='utf-8')
        digest = text_sha256(content)
        if digest != self.EXPECTED_SHA256:
            raise RuntimeError(f'{path or self.SOURCE_FILE} does not match the reviewed successor hash: got {digest}, '
                               f'expected {self.EXPECTED_SHA256}. Refusing: this script is stale relative to the overlay it ships next to.')
        return content

    def _command(self, deployment: dict):
        container = find_container(deployment, CONTAINER)
        command = (container.get('command') or []) if container else []
        return command[-1] if len(command) == 3 else None

    def _mount_wired(self, deployment: dict) -> bool:
        container = find_container(deployment, CONTAINER)
        if not container:
            return False
        mounts = [m for m in (container.get('volumeMounts') or []) if m.get('name') == self.VOLUME]
        volumes = [v for v in deployment['spec']['template']['spec'].get('volumes', []) if v.get('name') == self.VOLUME]
        return bool(mounts and volumes and mounts[0].get('mountPath') == self.MOUNT_PATH and mounts[0].get('subPath') == self.SUBPATH
                    and volumes[0].get('configMap', {}).get('name') == self.config_map_name)

    def already_applied(self, deployment: dict) -> bool:
        return self._mount_wired(deployment) and self._command(deployment) == self.NEW_COMMAND

    def collision(self, deployment: dict) -> str | None:
        container = find_container(deployment, CONTAINER)
        if not container:
            return None
        for mount in container.get('volumeMounts') or []:
            if mount.get('mountPath') == self.MOUNT_PATH and mount.get('name') != self.VOLUME:
                return mount.get('name')
        if self._command(deployment) not in (self.PRIOR_COMMAND, self.NEW_COMMAND):
            return 'live command does not match the pinned prior string -- refusing a blind command replacement'
        return None

    def prepare(self, api: Api) -> None:
        content = self.load_successor_content()
        document = {
            'apiVersion': 'v1', 'kind': 'ConfigMap',
            'metadata': {'name': self.config_map_name, 'namespace': api.namespace,
                         'annotations': {self.SOURCE_ANNOTATION: self.PREDECESSOR_SHA256, self.SHA_ANNOTATION: self.EXPECTED_SHA256}},
            'immutable': True, 'data': {self.SUBPATH: content},
        }
        existing = api.config_map(self.config_map_name)
        if existing is None:
            api.create_config_map(document)
        elif existing.get('data') != document['data']:
            raise RuntimeError('A different ConfigMap already uses this content-addressed name')

    def successor_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: self.PREDECESSOR_SHA256, self.SHA_ANNOTATION: self.EXPECTED_SHA256}},
            'spec': {'containers': [{'name': CONTAINER, 'command': ['sh', '-c', self.NEW_COMMAND], 'volumeMounts': [
                        {'name': self.VOLUME, 'mountPath': self.MOUNT_PATH, 'subPath': self.SUBPATH, 'readOnly': True}]}],
                     'volumes': [{'name': self.VOLUME, 'configMap': {'name': self.config_map_name, 'defaultMode': 292}}]}}}}

    def rollback_patch(self) -> dict:
        # volumeMounts merge on mountPath, volumes merge on name (see NcclEpContiguousOverlay.rollback_patch).
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: None, self.SHA_ANNOTATION: None}},
            'spec': {'containers': [{'name': CONTAINER, 'command': ['sh', '-c', self.PRIOR_COMMAND],
                                     'volumeMounts': [{'mountPath': self.MOUNT_PATH, '$patch': 'delete'}]}],
                     'volumes': [{'name': self.VOLUME, '$patch': 'delete'}]}}}}

    def verify(self, api: Api, log=print) -> tuple[bool, dict]:
        evidence: dict = {}
        deployment = api.deployment(DEPLOYMENT)
        container = find_container(deployment, CONTAINER)
        evidence['imageUnchanged'] = bool(container) and container.get('image') == EXPECTED_IMAGE
        evidence['mountWiredCorrectly'] = self._mount_wired(deployment)
        evidence['commandMatchesNew'] = self._command(deployment) == self.NEW_COMMAND
        stored = api.config_map(self.config_map_name)
        stored_sha = text_sha256(stored['data'][self.SUBPATH]) if stored and self.SUBPATH in (stored.get('data') or {}) else None
        evidence['storedConfigMapShaMatches'] = stored_sha == self.EXPECTED_SHA256
        evidence['storedConfigMapImmutable'] = bool(stored and stored.get('immutable') is True)
        evidence['readyRanksFour'] = None  # confirmed by the caller's /health check (ready_ranks:4); this script makes no call into the container
        result = all([evidence['imageUnchanged'], evidence['mountWiredCorrectly'], evidence['commandMatchesNew'],
                      evidence['storedConfigMapShaMatches'], evidence['storedConfigMapImmutable']])
        log(json.dumps({'overlayVerification': result, **evidence}))
        return result, evidence

    def plan_extra(self, deployment: dict) -> dict:
        return {'configMap': self.config_map_name, 'mountPath': self.MOUNT_PATH, 'predecessorSha256': self.PREDECESSOR_SHA256,
                'successorSha256': self.EXPECTED_SHA256, 'newCommandSha256': self.EXPECTED_NEW_COMMAND_SHA256,
                'flagChange': '--thinking-mode chat -> thinking, + --reasoning-effort low',
                'note': 'Pod recreation required; confirm ready_ranks:4, re-place ASR workers and send one thinking:false and one default request after this overlay'}


class DeepinferVramHeadroomOverlay(Overlay):
    """--gpu-memory-utilization 0.915 -> 0.905 on the live post-thinking-low command (LANE6-DEEPSEEK-VRAM-HEADROOM-PROPOSAL-
    20261123). Reason: the Typhoon ASR workers co-located on GPU0/GPU2 saw only 1.4-1.8 GiB free against their 1.0 GiB guard
    floor and paused (503 'paused: GPU memory guard'); 0.905 leaves about 4.5 GiB free. The live Deployment was already
    patched with the same single-token change on 23 Nov 2026 13:55 ICT (ORCH-GO + LANE6-DEEPSEEK-VRAM-0905-GO-20261123);
    this overlay records that change in source so the next pipeline run does not revert it: against the live Deployment
    it is `already_applied` (a no-op). Full `command` replacement, pinned byte for byte to the previous overlay's output."""
    name = 'deepinfer-vram-headroom'

    SOURCE_ANNOTATION = 'dsh.bot.or.th/deepinfer-vram-headroom-source'
    SHA_ANNOTATION = 'dsh.bot.or.th/deepinfer-vram-headroom-sha256'
    PRIOR_COMMAND = DeepseekThinkingLowOverlay.NEW_COMMAND
    NEW_COMMAND = PRIOR_COMMAND.replace('--gpu-memory-utilization 0.915', '--gpu-memory-utilization 0.905')
    EXPECTED_PRIOR_SHA256 = hashlib.sha256(PRIOR_COMMAND.encode()).hexdigest()
    EXPECTED_NEW_SHA256 = hashlib.sha256(NEW_COMMAND.encode()).hexdigest()
    SOURCE_COMMIT = 'LANE6-DEEPSEEK-VRAM-0905-READBACK-20261123'

    def _command(self, deployment: dict):
        container = find_container(deployment, CONTAINER)
        command = (container.get('command') or []) if container else []
        return command[-1] if len(command) == 3 else None

    def already_applied(self, deployment: dict) -> bool:
        return self._command(deployment) == self.NEW_COMMAND

    def collision(self, deployment: dict) -> str | None:
        if self._command(deployment) not in (self.PRIOR_COMMAND, self.NEW_COMMAND):
            return 'live command does not match the pinned prior string -- refusing a blind command replacement'
        return None

    def successor_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: self.SOURCE_COMMIT, self.SHA_ANNOTATION: self.EXPECTED_NEW_SHA256}},
            'spec': {'containers': [{'name': CONTAINER, 'command': ['sh', '-c', self.NEW_COMMAND]}]}}}}

    def rollback_patch(self) -> dict:
        return {'spec': {'template': {
            'metadata': {'annotations': {self.SOURCE_ANNOTATION: None, self.SHA_ANNOTATION: None}},
            'spec': {'containers': [{'name': CONTAINER, 'command': ['sh', '-c', self.PRIOR_COMMAND]}]}}}}

    def verify(self, api: Api, log=print) -> tuple[bool, dict]:
        deployment = api.deployment(DEPLOYMENT)
        container = find_container(deployment, CONTAINER)
        evidence = {'imageUnchanged': bool(container) and container.get('image') == EXPECTED_IMAGE,
                    'commandMatchesNew': self._command(deployment) == self.NEW_COMMAND}
        result = all(evidence.values())
        log(json.dumps({'overlayVerification': result, **evidence}))
        return result, evidence

    def plan_extra(self, deployment: dict) -> dict:
        return {'flagChange': '--gpu-memory-utilization 0.915 -> 0.905', 'newCommandSha256': self.EXPECTED_NEW_SHA256,
                'note': 'Pod restart required if not already applied; live was patched to 0.905 on 23 Nov 2026 so this is a no-op there'}


OVERLAYS: dict[str, Overlay] = {o.name: o for o in (
    NcclEpContiguousOverlay(), AsrTyphoonInprocessOverlay(), DeepinferMemoryTrimOverlay(), DeepseekThinkingLowOverlay(),
    DeepinferVramHeadroomOverlay(),
)}


def dry_run_patches(overlay: Overlay, api: Api, log=print) -> dict:
    result: dict = {}
    for label, patch in (('successorPatchDryRunAccepted', overlay.successor_patch()), ('rollbackPatchDryRunAccepted', overlay.rollback_patch())):
        try:
            api.patch_deployment(DEPLOYMENT, patch, dry_run=True)
            result[label] = True
        except Exception as error:  # noqa: BLE001 - recorded, never raised, from inside a plan-only report
            result[label] = False
            result[label.replace('Accepted', 'Error')] = str(error)[:300]
    log(json.dumps({'dryRun': result}))
    return result


def plan_and_apply(overlay: Overlay, api: Api, args, log=print, sleep=time.sleep) -> int:
    evidence_dir = getattr(args, 'evidence_dir', None)
    deployment = api.deployment(DEPLOYMENT)
    if not deployment:
        raise RuntimeError('Deployment not found: ' + DEPLOYMENT)
    already = overlay.already_applied(deployment)
    collision = overlay.collision(deployment)
    container = find_container(deployment, CONTAINER)
    image_ok = bool(container) and container.get('image') == EXPECTED_IMAGE
    shape = deployment_shape(deployment)
    shape_ok = shape['replicas'] == 1 and shape['strategy'] == 'Recreate' and CONTAINER in shape['containers']
    plan = {
        'overlay': overlay.name, 'deployment': DEPLOYMENT, 'imageOk': image_ok,
        'deploymentShape': shape, 'deploymentShapeOk': shape_ok, 'alreadyApplied': already,
        'collision': collision, 'apply': bool(args.apply),
        'note': 'Recreate: this change recreates the pod; expect ~7-8 min outage, same as the admin restart control quotes',
        **overlay.plan_extra(deployment),
    }
    log(json.dumps(plan))
    _write_evidence(evidence_dir, 'plan.json', plan)
    if not args.apply:
        dry_run = dry_run_patches(overlay, api, log=log)
        _write_evidence(evidence_dir, 'dry-run.json', dry_run)
        if already:
            log('Overlay already applied as expected; nothing to do.')
        return 0
    if already:
        log('Overlay already applied as expected; nothing to do.')
        return 0
    problems = []
    if not image_ok:
        problems.append('Live image is not the exact digest this script was written against: ' + str(container.get('image') if container else None))
    if not shape_ok:
        problems.append('Deployment shape is not replicas 1, strategy Recreate with container ' + CONTAINER)
    if collision:
        problems.append('Target already used by something else: ' + collision)
    if problems:
        log('REFUSED: ' + '; '.join(problems))
        _write_evidence(evidence_dir, 'refused.json', {'problems': problems})
        return 1
    _write_evidence(evidence_dir, 'deployment-before.json', redact_deployment(deployment))
    overlay.prepare(api)
    timeout = getattr(args, 'timeout', 1200)
    api.patch_deployment(DEPLOYMENT, overlay.successor_patch())
    good = wait_ready(api, DEPLOYMENT, timeout=timeout, settle=args.settle, sleep=sleep)
    evidence: dict = {}
    if good:
        good, evidence = overlay.verify(api, log=log)
    _write_evidence(evidence_dir, 'verification.json', {'passed': bool(good), 'overlay': overlay.name, **evidence})
    if good:
        _write_evidence(evidence_dir, 'deployment-after.json', redact_deployment(api.deployment(DEPLOYMENT)))
        log(f'Applied the {overlay.name} overlay to {DEPLOYMENT}.')
        return 0
    log(f'Rollout failed verification; removing the {overlay.name} overlay from {DEPLOYMENT}.')
    api.patch_deployment(DEPLOYMENT, overlay.rollback_patch())
    restored = wait_ready(api, DEPLOYMENT, timeout=timeout, settle=args.settle, sleep=sleep)
    log('Rollback ' + ('completed.' if restored else 'did NOT become ready; investigate now.'))
    _write_evidence(evidence_dir, 'rollback.json', {'restored': bool(restored)})
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--overlay', required=True, choices=sorted(OVERLAYS),
                        help='Exactly one named overlay to plan or apply.')
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
    return plan_and_apply(OVERLAYS[args.overlay], api, args)


if __name__ == '__main__':
    raise SystemExit(main())
