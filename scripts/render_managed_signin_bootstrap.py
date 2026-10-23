"""Add a reviewed managed-signin helper to future runtime templates only."""
import copy,json,re,sys

BOOTSTRAP='''set -euo pipefail
mkdir -p /state
if [ ! -f /state/profiles/web/cordis.patch.yml ]; then
  cp -R --no-preserve=ownership,mode,timestamps /opt/dsh/seed/dsh-home/. /state/
fi
node /managed-signin/configure_managed_signin.cjs /state
exec "$@"
'''

def configure(document,configmap):
 if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}',configmap):raise ValueError('Invalid ConfigMap name')
 result=copy.deepcopy(document)
 if set(result['templates'])!={'secure','internet'}:raise ValueError('Expected both private environments')
 for template in result['templates'].values():
  pod=template['spec']['template']['spec'];workers=[c for c in pod['containers']if c['name']=='dsh']
  if len(workers)!=1:raise ValueError('Expected one DSH worker')
  worker=workers[0]
  if not worker.get('command'):raise ValueError('Explicit startup command required')
  existing=[v for v in pod['volumes']if v['name']=='managed-signin']
  if existing:raise ValueError('Bootstrap already configured; inspect before replacing')
  pod['volumes'].append({'name':'managed-signin','configMap':{'name':configmap}})
  worker['volumeMounts'].append({'name':'managed-signin','mountPath':'/managed-signin','readOnly':True})
  original=worker['command']+worker.pop('args',[])
  worker['command']=['bash','-c',BOOTSTRAP,'--',*original]
 return result

if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('Usage: render_managed_signin_bootstrap.py HELPER_CONFIGMAP < templates.json')
 print(json.dumps(configure(json.load(sys.stdin),sys.argv[1]),indent=2))
