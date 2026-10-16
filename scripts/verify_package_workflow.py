"""Exercise reviewed download -> isolated promotion -> No Internet installation.

Only a bounded test artifact and temporary venv are used. No workspace/history
or datalake content is read. The operator reviews the download metadata before
running this command. This is functional/provenance testing, not malware proof.
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
IMAGE='dsoreg-sm1-p1.bot.or.th/da-gpu-server/dsh-runtime@sha256:c10f792b1516813fb2d5c4b4de0bfe816931dfcf71caeab8cd161cb13c5a8ca6'


def kube(*args,data=None):
    p=subprocess.run(['kubectl','--request-timeout=30s','-n','llm',*args],input=data,
                     text=True,capture_output=True,check=True)
    return p.stdout


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--download',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();download=json.loads(args.download.read_text())
    if download['artifact']!='acceptance-20261016-closure/python/six-1.17.0-py2.py3-none-any.whl' or not download['matchesPyPIMetadata']:
        raise ValueError('Expected reviewed pinned test artifact')
    args.output.mkdir(parents=True,exist_ok=False)
    helper=(ROOT/'container/promote_packages.py').read_text(encoding='utf-8')
    tests=(ROOT/'tests/test_package_promotion.py').read_text(encoding='utf-8')
    data={'helper.py':helper,'tests.py':tests,'manifest.sha256':download['sha256']+'  '+download['artifact']+'\n'}
    cm='dsh-promotion-'+hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]
    job='dsh-package-acceptance-'+datetime.now(timezone.utc).strftime('%H%M%S')
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'download':download,'promotionConfigMap':cm,
            'promotionSourceSHA256':hashlib.sha256(helper.encode()).hexdigest(),'job':job,'noRealRdtUsed':True}
    def apply(d):kube('apply','-f','-',data=json.dumps(d))
    apply({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':cm,'namespace':'llm'},'data':data})
    # This job needs storage only: no inference, DNS, KDC or public egress.
    apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-package-promotion-boundary','namespace':'llm'},
           'spec':{'podSelector':{'matchLabels':{'app':'dsh-package-promotion'}},'policyTypes':['Ingress','Egress'],'ingress':[],'egress':[]}})
    run="import subprocess;subprocess.run(['python3','-m','unittest','discover','-s','/promotion/tests','-v'],check=True);subprocess.run(['python3','/promotion/container/promote_packages.py'],check=True)"
    obj={'apiVersion':'batch/v1','kind':'Job','metadata':{'name':job,'namespace':'llm'},'spec':{'backoffLimit':0,'activeDeadlineSeconds':120,
       'template':{'metadata':{'labels':{'app':'dsh-package-promotion'}},'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,
       'securityContext':{'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},
       'containers':[{'name':'promote','image':IMAGE,'command':['python3','-c',run],
         'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
         'resources':{'requests':{'cpu':'100m','memory':'128Mi'},'limits':{'cpu':'1','memory':'256Mi'}},
         'env':[{'name':'APPROVAL_MANIFEST','value':'/promotion/manifest.sha256'},{'name':'PYTHONDONTWRITEBYTECODE','value':'1'}],
         'volumeMounts':[{'name':'config','mountPath':'/promotion','readOnly':True},
          {'name':'incoming','mountPath':'/packages/incoming','readOnly':True},{'name':'approved','mountPath':'/packages/approved'},
          {'name':'temporary','mountPath':'/tmp'}]}],
       'volumes':[{'name':'config','configMap':{'name':cm,'items':[{'key':'helper.py','path':'container/promote_packages.py'},
        {'key':'tests.py','path':'tests/test_package_promotion.py'},{'key':'manifest.sha256','path':'manifest.sha256'}]}},
        {'name':'incoming','persistentVolumeClaim':{'claimName':'dsh-package-incoming'}},
        {'name':'approved','persistentVolumeClaim':{'claimName':'dsh-package-approved'}},{'name':'temporary','emptyDir':{}}]}}}}
    try:
        apply(obj)
        kube('wait','--for=condition=complete','job/'+job,'--timeout=150s')
        logs=kube('logs','job/'+job);record['promotionLog']=logs
        assert 'Ran 5 tests' in logs and 'OK' in logs and 'promoted 1 verified dependency artifacts' in logs
        code=r'''import hashlib,json,os,subprocess,tempfile
from pathlib import Path
wheel=Path('/packages/approved/acceptance-20261016-closure/python/six-1.17.0-py2.py3-none-any.whl')
assert hashlib.sha256(wheel.read_bytes()).hexdigest()==DIGEST
with tempfile.TemporaryDirectory(prefix='dsh-offline-acceptance-') as d:
 subprocess.run(['python3','-m','venv',d],capture_output=True,check=True)
 env=dict(os.environ,PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
 p=subprocess.run([d+'/bin/pip','install','--no-index','--no-deps','--only-binary=:all:','--find-links',str(wheel.parent),'six==1.17.0'],env=env,capture_output=True,text=True,check=True)
 result=subprocess.check_output([d+'/bin/python','-c',"import six;assert six.__version__=='1.17.0';print('OFFLINE_PACKAGE_OK')"],text=True).strip()
 assert result=='OFFLINE_PACKAGE_OK'
 denied=False
 try:
  with wheel.open('ab'):pass
 except OSError:denied=True
 assert denied
 print(json.dumps({'exactImportResult':result,'installedWithNoIndex':True,'approvedWheelHashMatches':True,'approvedWriteDenied':True,'temporaryVenvRemovedOnExit':True}))
'''.replace('DIGEST',repr(download['sha256']))
        record['offlineInstallation']=json.loads(kube('exec','-i','deploy/dsh-secure','--','python3','-',data=code))
        record['status']='passed'
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        try:record['promotionLog']=kube('logs','job/'+job)
        except Exception:pass
        raise
    finally:
        (args.output/'package-workflow-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__':main()
