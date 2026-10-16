"""Install operator-owned policy and fail closed if the pinned TrueForge changes."""
import hashlib
from pathlib import Path
import shutil

ROOT = Path('/opt/dsh')
MAIN = Path('/usr/local/lib/node_modules/@truefoundry/trueforge/dist/main.js')
EXPECTED = '3759e982f8f96821dbd70359c20f744135885a70701d1e98c3fb7b19387a8366'

def patch(source):
    if hashlib.sha256(source).hexdigest() != EXPECTED:
        raise ValueError('Unreviewed TrueForge package; refusing policy patch')
    text = source.decode()
    changes = {
      'const modelProviderStore = new SqliteModelProviderStore2(db);':
        'const modelProviderStore = managedStore();',
      'const app = new OpenAPIHono20({ defaultHook: zodValidationHook });':
        '''const app = new OpenAPIHono20({ defaultHook: zodValidationHook });
  app.use('*', async (c, next) => {
    if (!['GET','HEAD','OPTIONS'].includes(c.req.method) &&
        /^\\/api\\/v1\\/settings\\/model-providers(?:\\/|$)/.test(c.req.path))
      return c.json({error:{message:'Model configuration is operator managed'}},403);
    await next();
  });'''
    }
    for before, after in changes.items():
        if text.count(before) != 1:
            raise ValueError('TrueForge policy target is not unique')
        text = text.replace(before, after)
    return "import {managedStore} from '/opt/dsh/container/managed_trueforge_store.mjs';\n" + text

if __name__ == '__main__':
    MAIN.write_text(patch(MAIN.read_bytes()), encoding='utf8')
    target = Path('/etc/claude-code/managed-settings.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/'container/claude-managed-settings.json', target)
    target.chmod(0o644)
    for name in ['harness-api-key.sh', 'trueforge-managed.sh']:
        (ROOT/'container'/name).chmod(0o755)
    link = Path('/usr/local/bin/trueforge')
    if link.is_symlink(): link.unlink()
    elif link.exists(): raise ValueError('Unexpected TrueForge executable')
    link.symlink_to(ROOT/'container/trueforge-managed.sh')
