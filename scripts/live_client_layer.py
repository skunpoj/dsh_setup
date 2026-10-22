"""Prepare a small, versioned launch layer without changing running processes.

The two pinned TrueForge modules are replaced only in a newly launched Node
process. Existing image files, client databases and sessions remain untouched.
"""
import hashlib
import json
from workspace_tools_overlay import CORE

BASE = '/state/.dsh-managed-clients'
BEGIN = '# DSH MANAGED CLIENT LAUNCHERS BEGIN'
END = '# DSH MANAGED CLIENT LAUNCHERS END'
BLOCK = f'''\n{BEGIN}
if [ -r {BASE}/current/activate.sh ]; then
    . {BASE}/current/activate.sh
fi
{END}
'''

HOOK = r'''// Only the two hash-qualified local modules are replaced, in this process.
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {fileURLToPath}=require('node:url');
const {registerHooks}=require('node:module');
const root=__dirname,manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json')));
const hits=[];
function hash(bytes){return crypto.createHash('sha256').update(bytes).digest('hex');}
if(process.versions.node!=='22.23.3')throw Error('Unqualified Node runtime for this compatibility layer');
if(typeof registerHooks!=='function')throw Error('Managed clients require qualified Node registerHooks support');
registerHooks({load(url,context,nextLoad){
  if(!url.startsWith('file:'))return nextLoad(url,context);
  const filename=fileURLToPath(url),rule=manifest.modules[filename];
  if(!rule)return nextLoad(url,context);
  if(!rule.accepted.includes(hash(fs.readFileSync(filename))))throw Error('Unqualified TrueForge module; no live substitution');
  const source=fs.readFileSync(path.join(root,rule.replacement));
  if(hash(source)!==manifest.files[rule.replacement])throw Error('Managed client source integrity failure');
  hits.push(filename);
  return {format:filename.endsWith('.mjs')?'module':'commonjs',source:source.toString(),shortCircuit:true};
}});
module.exports={hits};
'''


def digest(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def bundle(qualified, old_guide, trueforge_launcher):
    """Every input is already qualified source, not a remote package download."""
    assert qualified['kilo.json'] and old_guide['kilo.json']
    old_policy = json.loads(old_guide['kilo.json'])
    policy = json.loads(qualified['kilo.json'])
    expected = json.loads(json.dumps(old_policy))
    expected['permission']['edit'] = 'allow'
    assert expected == policy and policy['permission']['external_directory'] == 'deny'
    # Kilo adds this schema on first use if absent, rewriting the pinned asset.
    # Include it canonically so normal session operations leave bytes unchanged.
    qualified = dict(qualified)
    policy['$schema'] = 'https://app.kilo.ai/config.json'
    qualified['kilo.json'] = json.dumps(policy, indent=2) + '\n'
    identity = digest(json.dumps({'qualified': qualified, 'launcher': trueforge_launcher,
                                  'hook': HOOK, 'version': 3}, sort_keys=True))[:16]
    release = BASE + '/releases/' + identity
    files = {}
    files['workspace-file-tools.py'] = qualified['workspace-file-tools.py']
    adapter = qualified['trueforge-workspace.cjs']
    needle = "['/opt/dsh/container/workspace-file-tools.py']"
    assert adapter.count(needle) == 1
    files['trueforge-workspace.cjs'] = adapter.replace(needle, "[require('node:path').join(__dirname,'workspace-file-tools.py')]")
    modules = {}
    for name in ['TurnResourceResolver.js', 'TurnResourceResolver.mjs']:
        raw = qualified[name]
        target = '/opt/dsh/container/trueforge-workspace.cjs'
        assert raw.count(target) == 1
        files[name] = raw.replace(target, release + '/trueforge-workspace.cjs')
        modules[CORE + '/' + name] = {'accepted': [digest(old_guide[name]), digest(qualified[name])],
                                    'replacement': name}
    files['register.cjs'] = HOOK
    files['kilo.json'] = qualified['kilo.json']
    kilo = qualified['kilo-managed.py']
    needle = "POLICY = Path('/etc/kilo/kilo.json')"
    assert kilo.count(needle) == 1
    files['bin/kilo'] = kilo.replace(needle, "POLICY = Path(__file__).resolve().parent.parent / 'kilo.json'")
    needle = 'exec node /usr/local/lib/node_modules/@truefoundry/trueforge/dist/cli.js'
    assert trueforge_launcher.count(needle) == 1
    files['bin/trueforge'] = trueforge_launcher.replace(needle, 'exec /usr/local/bin/node --require ' + release + '/register.cjs /usr/local/lib/node_modules/@truefoundry/trueforge/dist/cli.js')
    files['activate.sh'] = f'''# New invocations only; never signal or replace an existing client.
kilo() {{ {release}/bin/kilo "$@"; }}
kilocode() {{ {release}/bin/kilo "$@"; }}
trueforge() {{ {release}/bin/trueforge "$@"; }}
'''
    hashes = {n: digest(v) for n, v in files.items()}
    manifest = {'version': 1, 'release': identity, 'path': release, 'files': hashes,
                'modules': modules, 'base_policy_sha256': digest(old_guide['kilo.json']),
                'scope': 'New client launches only; no process, database or deployment replacement'}
    files['manifest.json'] = json.dumps(manifest, indent=2) + '\n'
    return {'identity': identity, 'path': release, 'files': files, 'manifest': manifest,
            'bashrc_block': BLOCK, 'bytes': sum(len(v.encode()) for v in files.values())}
