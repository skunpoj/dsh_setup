"""Short-lived browser validation against the actual canary HTTPS ingress."""
import argparse,base64,hashlib,json,subprocess
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization

def main():
 p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);a=p.parse_args()
 def k(*args,obj=None):
  r=subprocess.run(['kubectl','-n','llm',*args],input=json.dumps(obj).encode() if obj else None,capture_output=True,timeout=90)
  if r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace')[:250])
  return r.stdout.decode('utf-8')
 def apply(obj):k('apply','--server-side','--field-manager=dsh-credential-rollout','-f','-',obj=obj)
 cfg=json.loads(Path(a.fixture).read_text());host=cfg['host'];ingress=json.loads(k('get','ingress','dsh-ingress','-o','json'));tls=ingress['spec']['tls'][0]['secretName']
 cert=base64.b64decode(json.loads(k('get','secret',tls,'-o','json'))['data']['tls.crt']);public=x509.load_pem_x509_certificate(cert).public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
 pods=json.loads(subprocess.check_output(['kubectl','-n','kube-system','get','pods','-o','json']))['items'];address=next(p['status']['podIP']for p in pods if p['metadata']['name'].startswith('rke2-ingress-nginx-controller-'))
 cfg={'host':host,'passwords':cfg['passwords'],'ingressIP':address,'ingressSPKI':base64.b64encode(hashlib.sha256(public).digest()).decode()}
 apply({'apiVersion':'v1','kind':'Service','metadata':{'name':'dsh-credential-canary'},'spec':{'selector':{'app':'dsh-credential-canary'},'ports':[{'port':3080,'targetPort':3080}]}})
 apply({'apiVersion':'networking.k8s.io/v1','kind':'Ingress','metadata':{'name':'dsh-credential-canary'},'spec':{'ingressClassName':ingress['spec'].get('ingressClassName','nginx'),'tls':[{'hosts':[host],'secretName':tls}],'rules':[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':'dsh-credential-canary','port':{'number':3080}}}}]}}]}})
 apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'dsh-credential-ui-fixture'},'stringData':{'config.json':json.dumps(cfg)}})
 code=(Path(__file__).resolve().parents[1]/'tests/credential_ui_live.py').read_text(encoding='utf-8')
 apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'dsh-credential-ui-source'},'data':{'test.py':code}})
 image='mcr.microsoft.com/playwright/python@sha256:330d401ae23c905896a0c26c66c36fc971b621519e7b11b435a8328d7bf6e031'
 apply({'apiVersion':'v1','kind':'Pod','metadata':{'name':'dsh-credential-ui-test','labels':{'app':'dsh-credential-ui-test'}},'spec':{'restartPolicy':'Never','activeDeadlineSeconds':300,'automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001},'containers':[{'name':'browser','image':image,'command':['sh','-c','python -m pip install --disable-pip-version-check --no-cache-dir --target /tmp/python playwright==1.64.1 >/tmp/pip.log 2>&1 && PYTHONPATH=/tmp/python python /qa/test.py; result=$?; echo BROWSER_EXIT=$result; sleep 180; exit $result'],'env':[{'name':'CRED_UI_FIXTURE','value':'/fixture/config.json'},{'name':'HOME','value':'/tmp'}],'resources':{'requests':{'cpu':'100m','memory':'512Mi'},'limits':{'cpu':'2','memory':'1536Mi'}},'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},'volumeMounts':[{'name':'qa','mountPath':'/qa','readOnly':True},{'name':'fixture','mountPath':'/fixture','readOnly':True},{'name':'tmp','mountPath':'/tmp'},{'name':'shm','mountPath':'/dev/shm'}]}],'volumes':[{'name':'qa','configMap':{'name':'dsh-credential-ui-source'}},{'name':'fixture','secret':{'secretName':'dsh-credential-ui-fixture'}},{'name':'tmp','emptyDir':{'sizeLimit':'1Gi'}},{'name':'shm','emptyDir':{'medium':'Memory','sizeLimit':'256Mi'}}]}})
 apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-credential-ui-test'},'spec':{'podSelector':{'matchLabels':{'app':'dsh-credential-ui-test'}},'policyTypes':['Ingress','Egress'],'ingress':[],'egress':[{'to':[{'ipBlock':{'cidr':address+'/32'}}],'ports':[{'port':443,'protocol':'TCP'}]},{'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}],'ports':[{'port':53,'protocol':'UDP'},{'port':53,'protocol':'TCP'}]},{'to':[{'ipBlock':{'cidr':'0.0.0.0/0','except':['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/3']}}],'ports':[{'port':443,'protocol':'TCP'}]}]}})
 print(json.dumps({'agentOwnedBrowserStarted':True,'image':image,'disposableAccountsOnly':True}))

if __name__=='__main__':main()
