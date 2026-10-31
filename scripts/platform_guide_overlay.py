"""Compose a qualified readonly guide overlay with an existing private runtime.

Callers must preflight the installed TrueForge files against HASHES using
configure_platform_guide.trueforge_patch. This helper never accesses credentials,
changes an image, reallocates storage or restarts a workload itself.
"""
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = '/usr/local/lib/node_modules/@truefoundry/trueforge/node_modules/@truefoundry/trueforge-core/dist/agent-session'


def with_deployment_context(guide, context=None):
    """Keep deployment availability explicit without changing the shared core."""
    if context is None:
        return guide
    if not context.startswith('## Current deployment profile\n') or len(context.encode('utf-8')) > 8192:
        raise ValueError('A bounded operator deployment profile is required')
    matches = list(re.finditer(r'^Guide version: [^\n]+\n', guide, re.MULTILINE))
    if len(matches) != 1:
        raise ValueError('Exactly one shared guide version is required')
    end = matches[0].end()
    return guide[:end] + '\n' + context.rstrip() + '\n\n' + guide[end:]


def source_data(originals, deployment_context=None):
    from configure_platform_guide import trueforge_patch
    data = {name: trueforge_patch(raw, name).decode('utf-8') for name, raw in originals.items()}
    if set(data) != {'TurnResourceResolver.js', 'TurnResourceResolver.mjs'}:
        raise ValueError('Both reviewed TrueForge instruction boundaries required')
    for name in ['PLATFORM_GUIDE.md', 'platform_guide.cjs', 'platform_guide.mjs']:
        data[name] = (ROOT / 'container' / name).read_text(encoding='utf-8')
    data['PLATFORM_GUIDE.md'] = with_deployment_context(data['PLATFORM_GUIDE.md'], deployment_context)
    data['CLAUDE.md'] = data['PLATFORM_GUIDE.md']
    data['configure_platform_guide.py'] = (ROOT / 'scripts/configure_platform_guide.py').read_text(encoding='utf-8')
    policy = json.loads((ROOT / 'container/kilo-managed.json').read_text(encoding='utf-8'))
    policy['instructions'] = ['/opt/dsh/container/PLATFORM_GUIDE.md']
    data['kilo.json'] = json.dumps(policy, indent=2) + '\n'
    return data


def configmap(data, namespace):
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return {'apiVersion': 'v1', 'kind': 'ConfigMap', 'immutable': True,
            'metadata': {'name': 'dsh-platform-guide-' + digest[:12], 'namespace': namespace}, 'data': data}


def transform(specification, configmap_name):
    spec = copy.deepcopy(specification)
    pod = spec['template']['spec']
    workers = [c for c in pod['containers'] if c['name'] == 'dsh']
    if len(workers) != 1 or pod.get('automountServiceAccountToken') is not False:
        raise ValueError('Only a private DSH execution workload is eligible')
    worker = workers[0]
    volumes, mounts = pod['volumes'], worker['volumeMounts']
    if any(v['name'] == 'platform-guide' for v in volumes):
        raise ValueError('Guide overlay already present; review its version before replacement')
    if worker.get('lifecycle', {}).get('postStart'):
        raise ValueError('Preserve and explicitly compose the existing startup hook')
    files = {name: '/opt/dsh/container/' + name for name in ['PLATFORM_GUIDE.md', 'platform_guide.cjs', 'platform_guide.mjs']}
    files.update({name: CORE + '/' + name for name in ['TurnResourceResolver.js', 'TurnResourceResolver.mjs']})
    files.update({'CLAUDE.md': '/etc/claude-code/CLAUDE.md', 'kilo.json': '/etc/kilo/kilo.json',
                  'configure_platform_guide.py': '/opt/dsh/scripts/configure_platform_guide.py'})
    if any(v.get('mountPath') in files.values() for v in mounts):
        raise ValueError('Conflicting instruction mount')
    volumes.append({'name': 'platform-guide', 'configMap': {'name': configmap_name, 'defaultMode': 0o444}})
    mounts.extend({'name': 'platform-guide', 'mountPath': target, 'subPath': name, 'readOnly': True}
                  for name, target in files.items())
    worker.setdefault('lifecycle', {})['postStart'] = {'exec': {'command': ['python3',
        '/opt/dsh/scripts/configure_platform_guide.py', '--state', '/state', '--workspace', '/workspace']}}
    return spec
