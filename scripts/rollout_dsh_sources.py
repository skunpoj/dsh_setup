"""Roll the DSH gateway, capacity controller or LiteLLM sidecar onto source built from git.

The gateway and controller run code mounted from immutable, hash-named
ConfigMaps. This builds that ConfigMap from the repository, switches the one
Deployment volume to it, waits for the rollout, verifies it, and switches back
automatically on any failure. Dry run by default; --apply changes the cluster.

Nothing else is edited: no image, replicas, policy, inventory, users, storage
or other volume. Old ConfigMaps are kept, so every rollout can be reverted.
The `litellm-sidecar` component (Deployment litellm, context_forwarder.py and
long_context_callbacks.py) is checked against litellm-sidecar-baseline.json and
refuses to apply while long requests run or inside a no-deploy window.
Strict TLS only; the token is read from a file or the environment, never logged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

# ConfigMap key -> repository path. Every key the live ConfigMap carries must be
# listed; an unknown key fails closed instead of being silently dropped.
SOURCES = {
    'agent_task_gateway.js': 'scripts/agent_task_gateway.js',
    'app-supervisor.py': 'container/app-supervisor.py',
    'app_signin.js': 'scripts/app_signin.js',
    'auth_proxy.js': 'scripts/auth_proxy.js',
    'bot_platform.css': 'scripts/bot_platform.css',
    'capacity-token-exporter.py': 'container/capacity-token-exporter.py',
    'capacity_controller.py': 'scripts/capacity_controller.py',
    'capacity_kube.py': 'scripts/capacity_kube.py',
    'capacity_planner.py': 'scripts/capacity_planner.py',
    'capacity_policy.js': 'scripts/capacity_policy.js',
    'capacity_report.py': 'scripts/capacity_report.py',
    'capacity_session.py': 'scripts/capacity_session.py',
    'capacity_worker.py': 'scripts/capacity_worker.py',
    'course_files.js': 'scripts/course_files.js',
    'credential_broker.js': 'scripts/credential_broker.js',
    'credential_gateway.js': 'scripts/credential_gateway.js',
    'credential_identity.js': 'scripts/credential_identity.js',
    'deploy_app_supervision.py': 'scripts/deploy_app_supervision.py',
    'dsh-connection.cjs': 'container/dsh-connection.cjs',
    'external_dns.js': 'scripts/external_dns.js',
    'external_upstream.js': 'scripts/external_upstream.js',
    'gradio_alias.js': 'scripts/gradio_alias.js',
    'identity_auth.js': 'scripts/identity_auth.js',
    'jupyter_launcher.py': 'scripts/jupyter_launcher.py',
    'jupyter_on_demand.js': 'scripts/jupyter_on_demand.js',
    'ldap_auth.js': 'scripts/ldap_auth.js',
    'ldapts-LICENSE': 'vendor/ldapts/LICENSE',
    'ldapts.cjs': 'vendor/ldapts/ldapts.cjs',
    'local_shared_proxy.js': 'scripts/local_shared_proxy.js',
    'package_controller.py': 'scripts/package_controller.py',
    'package_portal.js': 'scripts/package_portal.js',
    'package_task.py': 'container/package_task.py',
    'password_store.js': 'scripts/password_store.js',
    'platform_ui.js': 'scripts/platform_ui.js',
    'prepare_signup_pool.py': 'scripts/prepare_signup_pool.py',
    'session_demand.js': 'scripts/session_demand.js',
    'session_store.js': 'scripts/session_store.js',
    'signup_admission.js': 'scripts/signup_admission.js',
}

COMPONENTS = {
    'gateway': {'deployment': 'dsh-environment-gateway', 'volume': 'gateway-source', 'prefix': 'dsh-gateway-src-',
                'required': ['session_demand.js']},
    'controller': {'deployment': 'dsh-cap-live-controller', 'volume': 'source', 'prefix': 'dsh-cap-src-',
                   'required': ['capacity_session.py']},
}

# First-come sessions: the controller starts and stops private runtimes.
CONTROLLER_RULES = [
    {'apiGroups': ['apps'], 'resources': ['deployments'], 'verbs': ['get', 'list', 'create']},
    {'apiGroups': ['apps'], 'resources': ['deployments/scale'], 'verbs': ['get', 'patch']},
]


import re as _re

_REQUIRE = _re.compile(r"require\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)")


def unresolved_relative_requires(data, component='gateway'):
    """A ConfigMap is a flat directory. Return every relative require in its JavaScript files that cannot resolve there.

    A require on a line marked `cm-optional` is allowed: the module is loaded only behind a flag and has a stub.
    """
    missing = []
    for key, text in sorted(data.items()):
        # Only the gateway ConfigMap runs JavaScript; the controller's copy of auth_proxy.js is read for its hash, never executed.
        if component != 'gateway' or not key.endswith(('.js', '.cjs', '.mjs')):
            continue
        for line in text.split(chr(10)):
            if 'cm-optional' in line:
                continue
            for target in _REQUIRE.findall(line):
                name = target[2:] if target.startswith('./') else None
                ok = bool(name) and '/' not in name and any(
                    c in data for c in (name, name + '.js', name + '.cjs', name + '.mjs', name + '.json'))
                if not ok:
                    missing.append(key + ' requires ' + target)
    return missing


_PY_IMPORT = _re.compile(r"^(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", _re.M)


def unresolved_python_siblings(data, root=ROOT):
    """A Python file in a ConfigMap may import only sibling modules that are in the same ConfigMap (names that exist in the repo's scripts or container folders)."""
    repo_modules = set()
    for folder in ('scripts', 'container'):
        repo_modules |= {p.stem for p in (root / folder).glob('*.py')}
    missing = []
    for key, text in sorted(data.items()):
        if not key.endswith('.py'):
            continue
        for module in sorted(set(_PY_IMPORT.findall(text))):
            if module in repo_modules and (module + '.py') not in data and module != key[:-3]:
                missing.append(key + ' imports ' + module)
    return missing


def expand_dependency_keys(component, keys, root=ROOT):
    """Add repository-mapped sibling modules required by the selected sources."""
    expanded = set(keys)
    while True:
        added = set()
        for key in sorted(expanded):
            if key not in SOURCES:
                continue
            path = root / SOURCES[key]
            if not path.is_file():
                continue
            text = path.read_text(encoding='utf-8')
            if component == 'gateway' and key.endswith(('.js', '.cjs', '.mjs')):
                for line in text.splitlines():
                    if 'cm-optional' in line:
                        continue
                    for target in _REQUIRE.findall(line):
                        name = target[2:] if target.startswith('./') else ''
                        if not name or '/' in name:
                            continue
                        for candidate in (name, name + '.js', name + '.cjs', name + '.mjs', name + '.json'):
                            if candidate in SOURCES:
                                added.add(candidate)
                                break
            elif component == 'controller' and key.endswith('.py'):
                for module in _PY_IMPORT.findall(text):
                    candidate = module + '.py'
                    if candidate in SOURCES:
                        added.add(candidate)
        added -= expanded
        if not added:
            return expanded
        expanded |= added


def build_bundle(component, live_keys, root=ROOT, commit=''):
    """Return (name, ConfigMap document) built only from repository files."""
    spec = COMPONENTS[component]
    keys = sorted(expand_dependency_keys(component, set(live_keys) | set(spec['required']), root))
    unknown = [k for k in keys if k not in SOURCES]
    if unknown:
        raise ValueError('Live source keys have no repository mapping: ' + ', '.join(unknown))
    data = {}
    for key in keys:
        path = root / SOURCES[key]
        if not path.is_file():
            raise ValueError('Missing repository source: ' + SOURCES[key])
        data[key] = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    unresolved = unresolved_relative_requires(data, component) + (unresolved_python_siblings(data, root) if component == 'controller' else [])
    if unresolved:
        raise ValueError('ConfigMap files with a relative require that is not in the same ConfigMap: ' + '; '.join(unresolved))
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    name = spec['prefix'] + digest[:12]
    document = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
                'metadata': {'name': name, 'labels': {'app.kubernetes.io/part-of': 'dsh', 'app.kubernetes.io/component': component + '-source'},
                             'annotations': {'dsh.example.com/source-data-sha256': digest, 'dsh.example.com/git-commit': commit[:40]}},
                'data': data}
    return name, document


def volume_patch(component, config_map, source_digest='', commit=''):
    spec = COMPONENTS[component]
    prefix = 'gateway' if component == 'gateway' else 'controller'
    annotations = {
        f'dsh.example.com/{prefix}-source-configmap': config_map,
        'dsh.example.com/source-git-commit': commit[:40],
    }
    template_annotations = {
        f'dsh.example.com/{prefix}-source-sha256': source_digest,
        'dsh.example.com/source-git-commit': commit[:40],
    }
    return {
        'metadata': {'annotations': annotations},
        'spec': {'template': {
            'metadata': {'annotations': template_annotations},
            'spec': {'volumes': [{'name': spec['volume'], 'configMap': {'name': config_map}}]},
        }},
    }


def merged_rules(rules):
    """Add the controller's scaling rules without removing any existing rule."""
    result = [dict(r) for r in rules]
    for wanted in CONTROLLER_RULES:
        if not any(set(wanted['verbs']) <= set(r.get('verbs', [])) and r.get('apiGroups') == wanted['apiGroups'] and
                   set(wanted['resources']) <= set(r.get('resources', [])) for r in result):
            result.append(wanted)
    return result


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

    def patch_deployment(self, name, patch):
        return self.call('PATCH', f'/apis/apps/v1/namespaces/{self.namespace}/deployments/{name}', patch,
                         'application/strategic-merge-patch+json')

    def role(self, name):
        return self.call('GET', f'/apis/rbac.authorization.k8s.io/v1/namespaces/{self.namespace}/roles/{name}')

    def patch_role_rules(self, name, rules):
        return self.call('PATCH', f'/apis/rbac.authorization.k8s.io/v1/namespaces/{self.namespace}/roles/{name}',
                         {'rules': rules}, 'application/merge-patch+json')

    def text(self, path, limit=8 * 1024 * 1024):
        """GET a text body (pod logs). 404 is None. A body above the limit raises: a cut log could hide recent events."""
        request = urllib.request.Request(self.base + path, headers={'Authorization': 'Bearer ' + self.token})
        try:
            with urllib.request.urlopen(request, context=self.tls, timeout=60) as response:
                body = response.read(limit + 1)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise RuntimeError('GET ' + path.split('?')[0] + ': HTTP ' + str(error.code)) from None
        if len(body) > limit:
            raise RuntimeError('GET ' + path.split('?')[0] + ': body larger than %d bytes' % limit)
        return body.decode('utf-8', 'replace')

    def pods(self, selector):
        return self.call('GET', f'/api/v1/namespaces/{self.namespace}/pods?labelSelector=' + urllib.parse.quote(selector, safe=''))

    def pod_log(self, pod, container, since_seconds):
        return self.text(f'/api/v1/namespaces/{self.namespace}/pods/{pod}/log?container={container}&sinceSeconds={int(since_seconds)}')


def current_source(deployment, component):
    volume = COMPONENTS[component]['volume']
    matches = [v for v in deployment['spec']['template']['spec']['volumes'] if v['name'] == volume and 'configMap' in v]
    if len(matches) != 1:
        raise ValueError('Expected exactly one source volume ' + volume)
    return matches[0]['configMap']['name']


def current_volume_source(deployment, volume):
    matches = [v for v in deployment['spec']['template']['spec']['volumes'] if v['name'] == volume and 'configMap' in v]
    if len(matches) != 1:
        raise ValueError('Expected exactly one source volume ' + volume)
    return matches[0]['configMap']['name']


def wait_ready(api, name, timeout=420, settle=45):
    """Wait until the new revision is the only one and stays ready without restarts."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        d = api.deployment(name)
        s, want = d.get('status', {}), d['spec'].get('replicas', 1)
        if (s.get('observedGeneration', 0) >= d['metadata']['generation'] and s.get('updatedReplicas', 0) == want and
                s.get('readyReplicas', 0) == want and s.get('replicas', 0) == want and s.get('unavailableReplicas', 0) == 0):
            time.sleep(settle)
            d = api.deployment(name)
            s = d.get('status', {})
            if s.get('readyReplicas', 0) == want and s.get('unavailableReplicas', 0) == 0:
                return True
        time.sleep(5)
    return False


def http_ok(url, expect_json=False, ca_file=None):
    tls = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'Accept': 'application/json' if expect_json else 'text/html'}),
                                    context=tls, timeout=20) as response:
            body = response.read(262144)
            if response.status != 200:
                return False
            if expect_json:
                json.loads(body)
            return True
    except (urllib.error.URLError, ValueError, OSError):
        return False


def verify(component, args):
    if component != 'gateway' or not args.public_url:
        return True
    base = args.public_url.rstrip('/')
    return all(http_ok(base + path, path.startswith('/api/'), args.public_ca_file) for path in ['/login', '/api/status', '/api/signup-capacity'])


def rollout(api, component, args, log=print):
    spec = COMPONENTS[component]
    deployment = api.deployment(spec['deployment'])
    if not deployment:
        raise RuntimeError('Deployment not found: ' + spec['deployment'])
    previous = current_source(deployment, component)
    live = api.config_map(previous)
    if not live:
        raise RuntimeError('Current source ConfigMap is missing')
    name, document = build_bundle(component, live['data'].keys(), commit=args.commit)
    changed = sorted(k for k in document['data'] if live['data'].get(k, '').replace('\r\n', '\n') != document['data'][k])
    log(json.dumps({'component': component, 'deployment': spec['deployment'], 'from': previous, 'to': name,
                    'changedFiles': changed, 'apply': args.apply}))
    if name == previous:
        log('Already running this source; nothing to do.')
        return 0
    if not args.apply:
        return 0
    if component == 'controller':
        role = api.role(spec['deployment'])
        if role is None:
            raise RuntimeError('Controller Role not found')
        rules = merged_rules(role.get('rules', []))
        if rules != role.get('rules', []):
            api.patch_role_rules(spec['deployment'], rules)
            log('Controller Role: added deployments list and deployments/scale get/patch.')
    existing = api.config_map(name)
    if existing is None:
        api.create_config_map(document)
    elif existing.get('data') != document['data']:
        raise RuntimeError('A different ConfigMap already uses this name')
    source_digest = document['metadata']['annotations']['dsh.example.com/source-data-sha256']
    api.patch_deployment(spec['deployment'], volume_patch(component, name, source_digest, args.commit))
    if wait_ready(api, spec['deployment'], settle=args.settle) and verify(component, args):
        log(f'Rolled out {spec["deployment"]} to {name}. Previous source {previous} is kept for rollback.')
        return 0
    log(f'Rollout failed verification; switching {spec["deployment"]} back to {previous}.')
    previous_annotations = live.get('metadata', {}).get('annotations', {})
    api.patch_deployment(spec['deployment'], volume_patch(
        component, previous,
        previous_annotations.get('dsh.example.com/source-data-sha256', ''),
        previous_annotations.get('dsh.example.com/git-commit', ''),
    ))
    restored = wait_ready(api, spec['deployment'], settle=args.settle)
    log('Rollback ' + ('completed.' if restored else 'did NOT become ready; investigate now.'))
    return 1

# ---------------------------------------------------------------------------
# LiteLLM sidecar source (context_forwarder.py, long_context_callbacks.py)
#
# Deployment `litellm` mounts these two files from an immutable ConfigMap
# (volume `config`). Same job as scripts/rollout_interactive_scheduling.py (the
# manual one-off of 9 Nov 2026) and the same ConfigMap name rule, but through
# the REST API only: there is no pod exec here, so the lock probe, the mounted-
# file read and the sidecar /health call are replaced by log, pod and ConfigMap
# checks (weaker, and written down in the design). Every other key of the live
# ConfigMap is kept unchanged. Strict reviewed baseline: the live files must be
# the ones listed in litellm-sidecar-baseline.json, or nothing is applied.
# ---------------------------------------------------------------------------
SIDECAR = {
    'deployment': 'litellm', 'volume': 'config', 'prefix': 'litellm-interactive-',
    'files': {'context_forwarder.py': 'scripts/context_forwarder.py',
              'long_context_callbacks.py': 'scripts/long_context_callbacks.py'},
    'containers': ['litellm', 'context-forwarder'], 'forwarder_container': 'context-forwarder',
    'baseline': 'litellm-sidecar-baseline.json',
}
# Wed 11 Nov 2026 17:00-20:30 ICT: iommu=pt / DeepEP window. Repeatable --no-deploy-window and
# DSH_NO_DEPLOY_WINDOWS (comma separated START/END, UTC) add more. Applies to the sidecar only.
DEFAULT_NO_DEPLOY_WINDOWS = ['2026-11-11T10:00:00Z/2026-11-11T13:30:00Z']
WINDOW_MARGIN_SECONDS = 900
LONG_LOG_SECONDS = 3900  # a long request may run up to 3600 s [REPO: dispatch timeout]
SECRET_NAME = _re.compile(r'(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)', _re.I)


def lf(text):
    return text.replace('\r\n', '\n')


def text_sha256(text):
    return hashlib.sha256(lf(text).encode('utf-8')).hexdigest()


def load_baseline(root=ROOT):
    path = root / SIDECAR['baseline']
    document = json.loads(path.read_text(encoding='utf-8'))
    files = document.get('files') if isinstance(document, dict) else None
    if not isinstance(files, dict) or sorted(files) != sorted(SIDECAR['files']):
        raise ValueError('Baseline must list exactly ' + ', '.join(sorted(SIDECAR['files'])))
    for key, value in files.items():
        if not _re.fullmatch(r'[0-9a-f]{64}', str(value)):
            raise ValueError('Baseline value for ' + key + ' is not a sha256')
    return files


def build_sidecar_bundle(live_data, root=ROOT, commit=''):
    """Return (name, ConfigMap document, changed keys). Same name rule as rollout_interactive_scheduling.py."""
    missing = [k for k in SIDECAR['files'] if k not in live_data]
    if missing:
        raise ValueError('Live sidecar ConfigMap lacks: ' + ', '.join(missing))
    data = dict(live_data)
    for key, rel in SIDECAR['files'].items():
        path = root / rel
        if not path.is_file():
            raise ValueError('Missing repository source: ' + rel)
        data[key] = lf(path.read_text(encoding='utf-8'))
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    name = SIDECAR['prefix'] + digest[:12]
    changed = sorted(k for k in SIDECAR['files'] if lf(live_data[k]) != data[k])
    document = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
                'metadata': {'name': name, 'labels': {'app.kubernetes.io/part-of': 'dsh', 'app.kubernetes.io/component': 'litellm-sidecar-source'},
                             'annotations': {'dsh.example.com/source-data-sha256': digest, 'dsh.example.com/git-commit': commit[:40]}},
                'data': data}
    return name, document, changed


def sidecar_volume_patch(config_map, source_digest='', commit=''):
    return {
        'metadata': {'annotations': {'dsh.example.com/litellm-sidecar-source-configmap': config_map,
                                     'dsh.example.com/source-git-commit': commit[:40]}},
        'spec': {'template': {
            'metadata': {'annotations': {'dsh.example.com/litellm-sidecar-source-sha256': source_digest,
                                         'dsh.example.com/source-git-commit': commit[:40]}},
            'spec': {'volumes': [{'name': SIDECAR['volume'], 'configMap': {'name': config_map}}]},
        }},
    }


def no_deploy_windows(extra=()):
    windows = list(DEFAULT_NO_DEPLOY_WINDOWS)
    windows += [w.strip() for w in os.environ.get('DSH_NO_DEPLOY_WINDOWS', '').split(',') if w.strip()]
    windows += [w for w in (extra or []) if w]
    return windows


def blocking_window(now, windows, run_seconds=WINDOW_MARGIN_SECONDS):
    """The first window that the next run_seconds overlap, or None. A malformed window refuses (fail closed)."""
    import calendar
    for spec in windows:
        try:
            start, end = [calendar.timegm(time.strptime(x, '%Y-%m-%dT%H:%M:%SZ')) for x in spec.split('/', 1)]
        except Exception:
            return 'unparseable window ' + repr(spec)
        if now < end and now + run_seconds > start:
            return spec
    return None


def open_long_work(log_text):
    """From the context-forwarder log: long requests admitted but not finished, and cache references opened but not closed."""
    started, finished, refs_open, refs_closed = {}, set(), {}, set()
    for line in log_text.splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get('event')
        if kind == 'dsh_long_admission_started':
            started[event.get('requestId')] = True
        elif kind == 'dsh_request_timing':
            finished.add(event.get('requestId'))
        elif kind == 'dsh_cache_reference_started':
            refs_open[event.get('sessionId')] = True
        elif kind in ('dsh_cache_reference_closed', 'dsh_cache_reference_close_failed'):
            refs_closed.add(event.get('sessionId'))
    return (sorted(str(r) for r in started if r not in finished),
            sorted(str(s) for s in refs_open if s not in refs_closed))


def sidecar_pods(api, deployment):
    labels = (deployment['spec'].get('selector') or {}).get('matchLabels') or {}
    if not labels:
        raise RuntimeError('Deployment has no selector.matchLabels')
    selector = ','.join(k + '=' + v for k, v in sorted(labels.items()))
    items = (api.pods(selector) or {}).get('items', [])
    return [p for p in items if not p.get('metadata', {}).get('deletionTimestamp')]


def pod_state(pods, config_map):
    """(ok, detail). Exactly one live pod, Running, every container ready, mounting the expected ConfigMap."""
    detail = {'pods': [p['metadata']['name'] for p in pods]}
    if len(pods) != 1:
        return False, dict(detail, problem='expected exactly one pod, found %d' % len(pods))
    pod = pods[0]
    statuses = {c['name']: c for c in pod.get('status', {}).get('containerStatuses', [])}
    detail['restarts'] = {n: s.get('restartCount') for n, s in sorted(statuses.items())}
    volumes = {v['name']: v.get('configMap', {}).get('name') for v in pod['spec'].get('volumes', [])}
    detail['mountedConfigMap'] = volumes.get(SIDECAR['volume'])
    ok = (pod.get('status', {}).get('phase') == 'Running' and all(statuses.get(c, {}).get('ready') for c in SIDECAR['containers']) and
          detail['mountedConfigMap'] == config_map)
    return ok, detail


def redact_deployment(deployment):
    document = json.loads(json.dumps(deployment))
    for container in document.get('spec', {}).get('template', {}).get('spec', {}).get('containers', []):
        for env in container.get('env', []) or []:
            if 'value' in env and SECRET_NAME.search(env.get('name', '')):
                env['value'] = '<redacted>'
    return document


def verify_sidecar(api, deployment_name, config_map, document, settle=45, sleep=time.sleep, log=print):
    """REST-only checks after the rollout. Returns (ok, evidence)."""
    evidence = {}
    stored = api.config_map(config_map)
    evidence['configMapDataEqual'] = bool(stored) and stored.get('data') == document['data']
    deployment = api.deployment(deployment_name)
    ok, first = pod_state(sidecar_pods(api, deployment), config_map)
    evidence['podFirst'] = first
    if ok:
        sleep(settle)
        ok, second = pod_state(sidecar_pods(api, api.deployment(deployment_name)), config_map)
        evidence['podAfterSettle'] = second
        ok = ok and first.get('restarts') == second.get('restarts') and first.get('pods') == second.get('pods')
    evidence['podsStable'] = ok
    scan = {'traceback': None, 'contextPreparationFailed': None}
    if ok:
        pod = evidence['podAfterSettle']['pods'][0]
        text = api.pod_log(pod, SIDECAR['forwarder_container'], 600) or ''
        scan = {'traceback': 'Traceback (most recent call last)' in text,
                'contextPreparationFailed': '"dsh_context_preparation_failed"' in text, 'lines': len(text.splitlines())}
    evidence['logScan'] = scan
    result = bool(evidence['configMapDataEqual'] and ok and not scan['traceback'] and not scan['contextPreparationFailed'])
    log(json.dumps({'sidecarVerification': result, **evidence}))
    return result, evidence


def _write_evidence(directory, name, payload):
    if not directory:
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')


def rollout_sidecar(api, args, log=print, now=None, sleep=time.sleep):
    spec = SIDECAR
    evidence_dir = getattr(args, 'evidence_dir', None)
    deployment = api.deployment(spec['deployment'])
    if not deployment:
        raise RuntimeError('Deployment not found: ' + spec['deployment'])
    previous = current_volume_source(deployment, spec['volume'])
    live = api.config_map(previous)
    if not live:
        raise RuntimeError('Current source ConfigMap is missing')
    live_data = live['data']
    name, document, changed = build_sidecar_bundle(live_data, commit=args.commit)
    baseline = load_baseline()
    live_hashes = {k: text_sha256(live_data[k]) for k in spec['files'] if k in live_data}
    baseline_match = live_hashes == baseline
    shape = {'replicas': deployment['spec'].get('replicas'), 'strategy': (deployment['spec'].get('strategy') or {}).get('type'),
             'containers': sorted(c['name'] for c in deployment['spec']['template']['spec'].get('containers', []))}
    shape_ok = shape['replicas'] == 1 and shape['strategy'] == 'Recreate' and all(c in shape['containers'] for c in spec['containers'])
    when = time.time() if now is None else now
    window = blocking_window(when, no_deploy_windows(getattr(args, 'no_deploy_windows', None)))
    long_check = {}
    try:
        pods = sidecar_pods(api, deployment)
        if len(pods) == 1:
            text = api.pod_log(pods[0]['metadata']['name'], spec['forwarder_container'], LONG_LOG_SECONDS)
            if text is None:
                long_check = {'available': False, 'reason': 'log not found'}
            else:
                requests_open, refs_open = open_long_work(text)
                long_check = {'available': True, 'openLongRequests': requests_open, 'openCacheReferences': refs_open}
        else:
            long_check = {'available': False, 'reason': 'expected exactly one pod, found %d' % len(pods)}
    except RuntimeError as error:
        long_check = {'available': False, 'reason': str(error)[:160]}
    plan = {'component': 'litellm-sidecar', 'deployment': spec['deployment'], 'from': previous, 'to': name, 'changedFiles': changed,
            'baselineMatch': baseline_match, 'liveFileHashes': live_hashes, 'deploymentShape': shape, 'deploymentShapeOk': shape_ok,
            'noDeployWindow': window, 'longRequestCheck': long_check, 'apply': bool(args.apply),
            'note': 'Recreate: LiteLLM is unavailable for about 44 s and in-flight requests drop'}
    log(json.dumps(plan))
    _write_evidence(evidence_dir, 'plan.json', plan)
    if name == previous:
        log('Already running this source; nothing to do.')
        return 0
    if not args.apply:
        return 0
    problems = []
    if window:
        problems.append('inside or near a no-deploy window: ' + str(window))
    if not baseline_match:
        problems.append('Unreviewed source baseline: the live files are not the ones in ' + spec['baseline'])
    if not shape_ok:
        problems.append('Deployment shape is not replicas 1, strategy Recreate with containers ' + ', '.join(spec['containers']))
    if not long_check.get('available'):
        problems.append('cannot check for running long requests: ' + str(long_check.get('reason')))
    elif long_check['openLongRequests'] or long_check['openCacheReferences']:
        problems.append('long work is still running: %d request(s), %d cache reference(s)' % (
            len(long_check['openLongRequests']), len(long_check['openCacheReferences'])))
    if problems:
        log('REFUSED: ' + '; '.join(problems))
        _write_evidence(evidence_dir, 'refused.json', {'problems': problems})
        return 1
    _write_evidence(evidence_dir, 'deployment-before.json', redact_deployment(deployment))
    existing = api.config_map(name)
    if existing is None:
        api.create_config_map(document)
    elif existing.get('data') != document['data']:
        raise RuntimeError('A different ConfigMap already uses this name')
    digest = document['metadata']['annotations']['dsh.example.com/source-data-sha256']
    api.patch_deployment(spec['deployment'], sidecar_volume_patch(name, digest, args.commit))
    good = wait_ready(api, spec['deployment'], settle=args.settle)
    evidence = {}
    if good:
        good, evidence = verify_sidecar(api, spec['deployment'], name, document, settle=args.settle, sleep=sleep, log=log)
    _write_evidence(evidence_dir, 'verification.json', {'passed': bool(good), 'previousConfigMap': previous, 'configMap': name, **evidence})
    if good:
        _write_evidence(evidence_dir, 'deployment-after.json', redact_deployment(api.deployment(spec['deployment'])))
        log(f'Rolled out {spec["deployment"]} to {name}. Previous source {previous} is kept for rollback.')
        return 0
    log(f'Rollout failed verification; switching {spec["deployment"]} back to {previous}.')
    previous_annotations = live.get('metadata', {}).get('annotations', {})
    api.patch_deployment(spec['deployment'], sidecar_volume_patch(
        previous, previous_annotations.get('dsh.example.com/source-data-sha256', ''),
        previous_annotations.get('dsh.example.com/git-commit', '')))
    restored = wait_ready(api, spec['deployment'], settle=args.settle)
    log('Rollback ' + ('completed.' if restored else 'did NOT become ready; investigate now.'))
    _write_evidence(evidence_dir, 'rollback.json', {'restored': bool(restored), 'configMap': previous})
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['controller', 'gateway', 'both', 'litellm-sidecar'])
    parser.add_argument('--apply', action='store_true', help='Change the cluster. Without it, only report the plan.')
    parser.add_argument('--api', default=os.environ.get('DSH_K8S_API', ''), help='Kubernetes API base URL (for example the Rancher cluster proxy).')
    parser.add_argument('--token-file', default=os.environ.get('DSH_K8S_TOKEN_FILE', ''))
    parser.add_argument('--ca-file', default=os.environ.get('DSH_K8S_CA_FILE') or None)
    parser.add_argument('--namespace', default='llm')
    parser.add_argument('--public-url', default=os.environ.get('DSH_PUBLIC_URL', ''))
    parser.add_argument('--public-ca-file', default=os.environ.get('DSH_PUBLIC_CA_FILE') or None)
    parser.add_argument('--commit', default=os.environ.get('BUILD_SOURCEVERSION', ''))
    parser.add_argument('--settle', type=int, default=45)
    parser.add_argument('--evidence-dir', default='', help='litellm-sidecar: write plan, before/after and verification JSON here (env values of secret-like names are redacted).')
    parser.add_argument('--no-deploy-window', action='append', dest='no_deploy_windows', metavar='START/END',
                        help='litellm-sidecar: refuse --apply inside this UTC window (repeatable; DSH_NO_DEPLOY_WINDOWS also works).')
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text().strip() if args.token_file else os.environ.get('DSH_K8S_TOKEN', '').strip()
    if not args.api.startswith('https://') or len(token) < 20:
        raise SystemExit('An https Kubernetes API URL and a deploy token are required.')
    api = Api(args.api, token, args.namespace, args.ca_file)
    # Controller first: with no gateway demand file yet it starts and stops nothing.
    if args.component == 'litellm-sidecar':
        return rollout_sidecar(api, args)
    for component in (['controller', 'gateway'] if args.component == 'both' else [args.component]):
        if rollout(api, component, args) != 0:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
