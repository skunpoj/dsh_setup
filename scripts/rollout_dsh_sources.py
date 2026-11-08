"""Roll the DSH gateway or capacity controller onto source built from git.

The gateway and controller run code mounted from immutable, hash-named
ConfigMaps. This builds that ConfigMap from the repository, switches the one
Deployment volume to it, waits for the rollout, verifies it, and switches back
automatically on any failure. Dry run by default; --apply changes the cluster.

Nothing else is edited: no image, replicas, policy, inventory, users, storage
or other volume. Old ConfigMaps are kept, so every rollout can be reverted.
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
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

# ConfigMap key -> repository path. Every key the live ConfigMap carries must be
# listed; an unknown key fails closed instead of being silently dropped.
SOURCES = {
    'app-supervisor.py': 'container/app-supervisor.py',
    'app_signin.js': 'scripts/app_signin.js',
    'auth_proxy.js': 'scripts/auth_proxy.js',
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
    'platform.css': 'scripts/platform.css',
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


def build_bundle(component, live_keys, root=ROOT, commit=''):
    """Return (name, ConfigMap document) built only from repository files."""
    spec = COMPONENTS[component]
    keys = sorted(set(live_keys) | set(spec['required']))
    unknown = [k for k in keys if k not in SOURCES]
    if unknown:
        raise ValueError('Live source keys have no repository mapping: ' + ', '.join(unknown))
    data = {}
    for key in keys:
        path = root / SOURCES[key]
        if not path.is_file():
            raise ValueError('Missing repository source: ' + SOURCES[key])
        data[key] = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    name = spec['prefix'] + digest[:12]
    document = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
                'metadata': {'name': name, 'labels': {'app.kubernetes.io/part-of': 'dsh', 'app.kubernetes.io/component': component + '-source'},
                             'annotations': {'dsh.example.com/source-data-sha256': digest, 'dsh.example.com/git-commit': commit[:40]}},
                'data': data}
    return name, document


def volume_patch(component, config_map):
    spec = COMPONENTS[component]
    return {'spec': {'template': {'spec': {'volumes': [{'name': spec['volume'], 'configMap': {'name': config_map}}]}}}}


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


def current_source(deployment, component):
    volume = COMPONENTS[component]['volume']
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
    api.patch_deployment(spec['deployment'], volume_patch(component, name))
    if wait_ready(api, spec['deployment'], settle=args.settle) and verify(component, args):
        log(f'Rolled out {spec["deployment"]} to {name}. Previous source {previous} is kept for rollback.')
        return 0
    log(f'Rollout failed verification; switching {spec["deployment"]} back to {previous}.')
    api.patch_deployment(spec['deployment'], volume_patch(component, previous))
    restored = wait_ready(api, spec['deployment'], settle=args.settle)
    log('Rollback ' + ('completed.' if restored else 'did NOT become ready; investigate now.'))
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['controller', 'gateway', 'both'])
    parser.add_argument('--apply', action='store_true', help='Change the cluster. Without it, only report the plan.')
    parser.add_argument('--api', default=os.environ.get('DSH_K8S_API', ''), help='Kubernetes API base URL.')
    parser.add_argument('--token-file', default=os.environ.get('DSH_K8S_TOKEN_FILE', ''))
    parser.add_argument('--ca-file', default=os.environ.get('DSH_K8S_CA_FILE') or None)
    parser.add_argument('--namespace', default='llm')
    parser.add_argument('--public-url', default=os.environ.get('DSH_PUBLIC_URL', ''))
    parser.add_argument('--public-ca-file', default=os.environ.get('DSH_PUBLIC_CA_FILE') or None)
    parser.add_argument('--commit', default=os.environ.get('BUILD_SOURCEVERSION', ''))
    parser.add_argument('--settle', type=int, default=45)
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text().strip() if args.token_file else os.environ.get('DSH_K8S_TOKEN', '').strip()
    if not args.api.startswith('https://') or len(token) < 20:
        raise SystemExit('An https Kubernetes API URL and a deploy token are required.')
    api = Api(args.api, token, args.namespace, args.ca_file)
    # Controller first: with no gateway demand file yet it starts and stops nothing.
    for component in (['controller', 'gateway'] if args.component == 'both' else [args.component]):
        if rollout(api, component, args) != 0:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
