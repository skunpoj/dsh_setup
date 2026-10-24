"""Prepare an immutable future-worker overlay; never restart existing users."""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = '/usr/local/lib/node_modules/@truefoundry/trueforge/node_modules/@truefoundry/trueforge-core/dist/agent-session'
MARKER = '// DSH private workspace tools v1\n'
TARGET = '    const modelName = agentInfo?.model ?? spec.model.name;'
INSERT = '''    toolSets.push(new import_ToolSet.ToolSet({
      source: await this.getOrCreateToolSource({id: 'dsh-workspace', create: async () => workspaceSource()}),
      selectors: {enableTools: ['read_file', 'write_file', 'list_directory'], requireApprovalForTools: []},
      preload: true, approvalPolicies: undefined
    }));
'''


def patch_resolver(raw, name):
    from configure_platform_guide import trueforge_patch
    prefix = ("import {createRequire as dshCreateRequire} from 'node:module';\n"
              "const {workspaceSource} = dshCreateRequire(import.meta.url)('/opt/dsh/container/trueforge-workspace.cjs');\n"
              if name.endswith('.mjs') else
              "const {workspaceSource} = require('/opt/dsh/container/trueforge-workspace.cjs');\n")
    text = raw.decode('utf-8')
    insertion = INSERT.replace('import_ToolSet.ToolSet', 'ToolSet') if name.endswith('.mjs') else INSERT
    if text.startswith(MARKER + prefix):
        original = text[len(MARKER + prefix):]
        if original.count(insertion) != 1:
            raise ValueError('Modified workspace adapter')
        original = original.replace(insertion, '')
        trueforge_patch(original.encode(), name)
        return raw
    reviewed = trueforge_patch(raw, name).decode('utf-8')
    if reviewed.count(TARGET) != 1:
        raise ValueError('Unreviewed local tool integration boundary')
    return (MARKER + prefix + reviewed.replace(TARGET, insertion + TARGET)).encode()


def source_data(guide_data):
    data = {name: patch_resolver(guide_data[name].encode(), name).decode()
            for name in ['TurnResourceResolver.js', 'TurnResourceResolver.mjs']}
    for name in ['workspace-file-tools.py', 'trueforge-workspace.cjs', 'kilo-managed.py']:
        data[name] = (ROOT / 'container' / name).read_text(encoding='utf-8')
    policy = json.loads(guide_data['kilo.json'])
    # Preserve the deployed guide/model/transport; only approve local edits.
    if policy['permission'].get('external_directory') != 'deny':
        raise ValueError('External directory denial is required')
    policy['permission']['edit'] = 'allow'
    data['kilo.json'] = json.dumps(policy, indent=2) + '\n'
    return data


def configmap(data, namespace):
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return {'apiVersion':'v1', 'kind':'ConfigMap', 'immutable':True,
            'metadata':{'namespace':namespace, 'name':'dsh-workspace-tools-' + digest[:12]}, 'data':data}


def transform(specification, name):
    spec = copy.deepcopy(specification)
    pod = spec['template']['spec']
    worker, = [c for c in pod['containers'] if c['name'] == 'dsh']
    if pod.get('automountServiceAccountToken') is not False:
        raise ValueError('Only private workers are eligible')
    if any(v['name'] == 'workspace-tools' for v in pod['volumes']):
        raise ValueError('Workspace overlay already present')
    hook = worker.get('lifecycle', {}).get('postStart')
    expected = {'exec':{'command':['python3','/opt/dsh/scripts/configure_platform_guide.py',
                                  '--state','/state','--workspace','/workspace']}}
    if hook and hook != expected:
        raise ValueError('Unreviewed startup hook')
    if hook:
        # The pinned start-dsh.sh already installs the guide after seed copy.
        # Running the same writer concurrently in postStart races first startup.
        worker['lifecycle'].pop('postStart')
    files = {n:CORE + '/' + n for n in ['TurnResourceResolver.js', 'TurnResourceResolver.mjs']}
    files.update({n:'/opt/dsh/container/' + n for n in
                  ['workspace-file-tools.py', 'trueforge-workspace.cjs']})
    files['kilo-managed.py'] = '/usr/local/bin/kilo-managed'
    files['kilo.json'] = '/etc/kilo/kilo.json'
    mounts = worker['volumeMounts']
    # Replace only exact reviewed instruction/policy mounts; preserve all storage.
    for mount in mounts:
        if mount['mountPath'] in files.values() and mount['name'] != 'platform-guide':
            raise ValueError('Unexpected existing client policy mount')
    worker['volumeMounts'] = [m for m in mounts if m['mountPath'] not in files.values()]
    worker['volumeMounts'].extend({'name':'workspace-tools','mountPath':target,
                                  'subPath':key,'readOnly':True} for key,target in files.items())
    pod['volumes'].append({'name':'workspace-tools','configMap':{'name':name,'defaultMode':0o444,
        'items':[{'key':key,'path':key,'mode':0o555 if key == 'kilo-managed.py' else 0o444}
                 for key in files]}})
    return spec
