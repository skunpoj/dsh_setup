"""Warm replacement acceptance for the separated legacy worker/auth runtimes."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

from isolate_legacy_auth import credential_from_dpapi
from migrate_legacy_private_runtime import kube, ROOT, CHECKPOINT


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--name',choices=['dsh-user2','dsh3'],required=True)
    ap.add_argument('--credential-snapshot',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    before=json.loads(kube('get','deploy',a.name,'-o','json'))
    proxy=next(c for c in before['spec']['template']['spec']['containers'] if c['name']=='auth-proxy')
    env={e['name']:e.get('value') for e in proxy['env']};owner=env['AUTH_USER'];host=env['DSH_TRUSTED_HOST']
    password=credential_from_dpapi(a.credential_snapshot)
    marker='.restart-acceptance-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    content=hashlib.sha256(marker.encode()).hexdigest()
    fingerprint=CHECKPOINT[CHECKPOINT.index('def fingerprint(path):'):CHECKPOINT.index('frozen=[]')]
    code="import pathlib,os,hashlib,json\n"+fingerprint+"\nprint(json.dumps(fingerprint(pathlib.Path('/root/.dsh/sessions'))))"
    sessions=json.loads(kube('exec','-i','deploy/'+a.name,'-c','dsh','--','python3','-',source=code))
    create="import pathlib;name="+repr(marker)+";value="+repr(content)+";[(pathlib.Path(base)/name).write_text(value) for base in ['/root','/workspace']]"
    kube('exec','deploy/'+a.name,'-c','dsh','--','python3','-c',create)
    source=(ROOT/'scripts/auth_proxy.js').read_text(encoding='utf-8');helper=(ROOT/'scripts/password_store.js').read_text(encoding='utf-8')
    cm='dsh-legacy-auth-source-'+hashlib.sha256((source+helper).encode()).hexdigest()[:12]
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':cm,'namespace':'llm'},'data':{'auth_proxy.js':source,'password_store.js':helper}}))
    new=json.loads(json.dumps(before['spec']));pod=new['template']['spec']
    pod['volumes']=[v for v in pod['volumes'] if v['name']!='legacy-auth-source']+[{'name':'legacy-auth-source','configMap':{'name':cm}}]
    proxy=next(c for c in pod['containers'] if c['name']=='auth-proxy')
    for mount in proxy['volumeMounts']:
        if mount['mountPath']=='/scripts':mount['name']='legacy-auth-source'
    new['template']['metadata'].setdefault('annotations',{})['dsh.bot.or.th/auth-source-sha256']=hashlib.sha256(source.encode()).hexdigest()
    label='legacy-dsh2' if a.name=='dsh-user2' else 'legacy-dsh3'
    collector=(ROOT/'scripts/collect_legacy_audit.py').read_text(encoding='utf-8')
    collector_cm='dsh-legacy-audit-'+hashlib.sha256(collector.encode()).hexdigest()[:12]
    kube('apply','-f','-',source=json.dumps({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':collector_cm,'namespace':'llm'},'data':{'collector.py':collector}}))
    mkdir="require('fs').mkdirSync(process.env.DSH_AUDIT_DIR+'/legacy/"+label+"',{recursive:true,mode:0o700});"
    kube('exec','deploy/dsh-environment-gateway','--','node','-e',mkdir)
    pod['volumes']=[v for v in pod['volumes'] if v['name'] not in ['audit-export-source','central-legacy-audit']]+[{'name':'audit-export-source','configMap':{'name':collector_cm}},{'name':'central-legacy-audit','persistentVolumeClaim':{'claimName':'dsh-da-workspace-secure'}}]
    pod['containers']=[c for c in pod['containers'] if c['name']!='audit-exporter']
    pod['containers'].append({'name':'audit-exporter','image':proxy['image'],
        'command':['sh','-c','while true; do python3 -B /collector/collector.py || echo "Audit projection unavailable" >&2; sleep 30; done'],
        'env':[{'name':'DSH_AUDIT_SOURCE_LABEL','value':label}],
        'securityContext':{'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
        'resources':{'requests':{'cpu':'25m','memory':'32Mi'},'limits':{'cpu':'250m','memory':'256Mi'}},
        'volumeMounts':[{'name':'legacy-auth','mountPath':'/sources/'+label,'subPath':'audit','readOnly':True},{'name':'audit-export-source','mountPath':'/collector','readOnly':True},{'name':'central-legacy-audit','mountPath':'/output','subPath':'dsh-admin-audit/legacy/'+label}]})
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'name':a.name,'authSource':cm,'sessionsBefore':sessions}
    changed=False
    try:
        changed=True;kube('patch','deploy',a.name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':new}]))
        kube('rollout','status','deploy/'+a.name,'--timeout=180s')
        verify="import pathlib,json,os;name="+repr(marker)+";value="+repr(content)+";assert all((pathlib.Path(base)/name).read_text()==value for base in ['/root','/workspace']);print(json.dumps({'uid':os.getuid(),'twoDurableMarkersMatched':True,'workerCanReadAuthStore':pathlib.Path('/auth/users/users.json').exists(),'oldWorkspaceAuthFileExists':pathlib.Path('/workspace/users/.user_auth.json').exists(),'serviceAccountTokenMounted':pathlib.Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()}))"
        record['worker']=json.loads(kube('exec','deploy/'+a.name,'-c','dsh','--','python3','-c',verify));assert record['worker']['uid']==10001 and not any(record['worker'][k] for k in ['workerCanReadAuthStore','oldWorkspaceAuthFileExists','serviceAccountTokenMounted'])
        probe=(ROOT/'scripts/review_legacy_auth.js').read_text(encoding='utf-8').replace("const users=JSON.parse(fs.readFileSync('/workspace/users/.user_auth.json'));","const users=JSON.parse(fs.readFileSync(0,'utf8'));")
        record['login']=json.loads(kube('exec','-i','deploy/'+a.name,'-c','auth-proxy','--','node','-e',probe,source=json.dumps({owner:password,'guest':'denied','thanatcc':'denied'})))
        assert record['login']['authenticatedHistoryRpcSucceeded'] and record['login']['accountsInSharedRuntime']==1 and not record['login']['sharedGuestAccountPresent']
        terminal=(ROOT/'scripts/verify_terminal_websocket.js').read_text(encoding='utf-8');start=terminal.index('const selectedUser=');end=terminal.index('function request(')
        terminal=terminal[:start]+"const identity=JSON.parse(fs.readFileSync(0,'utf8'));\n"+terminal[end:]
        terminal=terminal.replace('dsh.aiportal.bot.or.th',host).replace("[['off','secure'],['on','internet']]","[['on','internet']]")
        record['terminal']=json.loads(kube('exec','-i','deploy/'+a.name,'-c','auth-proxy','--','node','-e',terminal,source=json.dumps({'user':owner,'password':password})))
        record['sessionsAfter']=json.loads(kube('exec','-i','deploy/'+a.name,'-c','dsh','--','python3','-',source=code));assert sessions==record['sessionsAfter']
        record['status']='passed'
        (a.output/'candidate-public.json').write_text(json.dumps({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':a.name,'namespace':'llm'},'spec':new},indent=2)+'\n',encoding='utf-8')
    except Exception as error:
        record['status']='failed';record['error']=str(error)
        if changed:
            kube('patch','deploy',a.name,'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':before['spec']}]))
            kube('rollout','status','deploy/'+a.name,'--timeout=180s');record['specificationRestored']=True
        raise
    finally:
        cleanup="import pathlib;name="+repr(marker)+";[(pathlib.Path(base)/name).unlink(missing_ok=True) for base in ['/root','/workspace']]"
        kube('exec','deploy/'+a.name,'-c','dsh','--','python3','-c',cleanup)
        password=None;(a.output/'result.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8');print(json.dumps(record),flush=True)


if __name__=='__main__':main()
