"""Bootstrap a sealed-by-default OpenBao service. Operator material uses Windows DPAPI.

Never print initialization output or store it in the repository/Kubernetes. Existing vaults
are not reinitialized. This script requires the cryptography package and kubectl access.
"""
import argparse,base64,ctypes,datetime,hashlib,ipaddress,json,os,subprocess,time,urllib.request
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

class Blob(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]
def protect(data,decrypt=False):
    buf=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    if decrypt:ok=ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
    else:ok=ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source),'DSH credential vault operator custody',None,None,None,1,ctypes.byref(target))
    if not ok:raise RuntimeError('Windows operator protection failed')
    try:return ctypes.string_at(target.data,target.length)
    finally:ctypes.windll.kernel32.LocalFree(target.data)
def run(args,source=None):
    p=subprocess.run(args,input=source.encode('utf-8') if source is not None else None,capture_output=True,timeout=180)
    if p.returncode:raise RuntimeError('Operator command failed: '+p.stderr.decode('utf-8',errors='replace')[:300])
    return p.stdout.decode('utf-8')

def configure(namespace,operator):
    def k(*args,source=None):return run(['kubectl','-n',namespace,*args],source)
    def vault(path,body):
        output=k('exec','-i','deployment/dsh-credential-vault','--','sh','-c','read -r BAO_TOKEN; export BAO_TOKEN; exec bao write -format=json "$1" -','sh',path,source=operator['root_token']+'\n'+json.dumps(body))
        return json.loads(output) if output.lstrip().startswith('{') else {}
    for mode in ['off','on']:
        mounts=json.loads(k('exec','-i','deployment/dsh-credential-vault','--','sh','-c','read -r BAO_TOKEN; export BAO_TOKEN; exec bao secrets list -format=json',source=operator['root_token']+'\n'))
        if 'dsh-'+mode+'/' not in mounts:vault('sys/mounts/dsh-'+mode,{'type':'kv','options':{'version':'2'}})
        vault('dsh-'+mode+'/config',{'max_versions':1,'cas_required':True})
        policy='path "dsh-'+mode+'/data/*" { capabilities = ["create", "read", "update"] }\npath "auth/token/renew-self" { capabilities = ["update"] }'
        vault('sys/policies/acl/dsh-'+mode,{'policy':policy})
        token=vault('auth/token/create-orphan',{'policies':['dsh-'+mode],'period':'24h','no_default_policy':True,'display_name':'dsh-credential-'+mode})['auth']['client_token']
        k('apply','--server-side','--field-manager=dsh-credential-rollout','-f','-',source=json.dumps({'apiVersion':'v1','kind':'Secret','metadata':{'name':'dsh-credential-'+mode+'-vault-token'},'type':'Opaque','stringData':{'token':token}}))
def certificate(ca_key,ca_cert,names):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=datetime.datetime.now(datetime.timezone.utc)
    san=[x509.IPAddress(ipaddress.ip_address(n)) if n[0].isdigit() else x509.DNSName(n) for n in names]
    cert=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,names[0])])).issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=365)).add_extension(x509.SubjectAlternativeName(san),False).add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),False).sign(ca_key,hashes.SHA256()))
    return {'tls.key':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),'tls.crt':cert.public_bytes(serialization.Encoding.PEM).decode(),'ca.pem':ca_cert.public_bytes(serialization.Encoding.PEM).decode()}
def main():
    if os.name!='nt':raise RuntimeError('Windows DPAPI operator custody is required before provisioning')
    ap=argparse.ArgumentParser();ap.add_argument('--namespace',default='llm');ap.add_argument('--custody',required=True);ap.add_argument('--runtime-image');ap.add_argument('--resume',action='store_true');a=ap.parse_args()
    custody=Path(a.custody).resolve();repo=Path(__file__).resolve().parents[1]
    if a.resume:
        if not custody.is_file() or custody.is_relative_to(repo):raise RuntimeError('Existing protected operator custody required')
        configure(a.namespace,json.loads(protect(custody.read_bytes(),decrypt=True)))
        print(json.dumps({'vaultConfigured':True,'operatorCustody':str(custody)}));return
    if custody.is_relative_to(repo) or custody.exists():raise RuntimeError('Use a NEW operator custody path outside the repository')
    ns=a.namespace;k=lambda *args,source=None:run(['kubectl','-n',ns,*args],source)
    def apply(obj):return k('apply','--server-side','--field-manager=dsh-credential-rollout','-f','-',source=json.dumps(obj))
    for name,port in [('dsh-credential-vault',8200),('dsh-credential-off',8443),('dsh-credential-on',8443),('dsh-credential-tools',3443)]:
        selector={'app':name} if name!='dsh-credential-tools' else {'app':'dsh-environment-gateway'}
        apply({'apiVersion':'v1','kind':'Service','metadata':{'name':name},'spec':{'selector':selector,'ports':[{'port':port,'targetPort':port}]}})
    addresses={name:json.loads(k('get','service',name,'-o','json'))['spec']['clusterIP'] for name in ['dsh-credential-vault','dsh-credential-off','dsh-credential-on','dsh-credential-tools']}
    ca_key=rsa.generate_private_key(public_exponent=65537,key_size=3072);now=datetime.datetime.now(datetime.timezone.utc)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'DSH credential services private CA')])
    ca=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=1095)).add_extension(x509.BasicConstraints(ca=True,path_length=0),True).sign(ca_key,hashes.SHA256()))
    for name,ip in addresses.items():
        values=certificate(ca_key,ca,[name+'.'+ns+'.svc.cluster.local',name+'.'+ns+'.svc',name,ip,'127.0.0.1'])
        apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':name+'-tls'},'type':'Opaque','stringData':values})
    gateway_key=base64.urlsafe_b64encode(os.urandom(48)).decode()
    apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'dsh-credential-gateway-key'},'type':'Opaque','stringData':{'key':gateway_key}})
    hcl='storage "raft" { path = "/bao/data"\nnode_id = "dsh-vault-1" }\nlistener "tcp" { address = "0.0.0.0:8200"\ntls_cert_file = "/tls/tls.crt"\ntls_key_file = "/tls/tls.key" }\napi_addr = "https://'+addresses['dsh-credential-vault']+':8200"\ncluster_addr = "https://127.0.0.1:8201"\nui = false\n'
    apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'dsh-credential-vault-config'},'data':{'config.hcl':hcl}})
    apply({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'dsh-credential-vault-data'},'spec':{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}}})
    token=json.load(urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:openbao/openbao:pull',timeout=20))['token']
    request=urllib.request.Request('https://registry-1.docker.io/v2/openbao/openbao/manifests/2.7.1',headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json'})
    with urllib.request.urlopen(request,timeout=30) as response:digest=response.headers['Docker-Content-Digest']
    image='docker.io/openbao/openbao@'+digest
    apply({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'dsh-credential-vault'},'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app':'dsh-credential-vault'}},'template':{'metadata':{'labels':{'app':'dsh-credential-vault'}},'spec':{'automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'vault','image':image,'command':['bao','server','-config=/bao/config/config.hcl'],'env':[{'name':'BAO_ADDR','value':'https://127.0.0.1:8200'},{'name':'BAO_CACERT','value':'/tls/ca.pem'}],'ports':[{'containerPort':8200}],'resources':{'requests':{'cpu':'100m','memory':'256Mi'},'limits':{'cpu':'1','memory':'512Mi'}},'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},'volumeMounts':[{'name':'data','mountPath':'/bao/data'},{'name':'config','mountPath':'/bao/config','readOnly':True},{'name':'tls','mountPath':'/tls','readOnly':True},{'name':'tmp','mountPath':'/tmp'}]}],'volumes':[{'name':'data','persistentVolumeClaim':{'claimName':'dsh-credential-vault-data'}},{'name':'config','configMap':{'name':'dsh-credential-vault-config'}},{'name':'tls','secret':{'secretName':'dsh-credential-vault-tls','defaultMode':288}},{'name':'tmp','emptyDir':{'sizeLimit':'16Mi'}}]}}}})
    apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-credential-vault-isolation'},'spec':{'podSelector':{'matchLabels':{'app':'dsh-credential-vault'}},'policyTypes':['Ingress','Egress'],'egress':[],'ingress':[{'from':[{'podSelector':{'matchLabels':{'dsh-credential-broker':'true'}}}],'ports':[{'port':8200,'protocol':'TCP'}]}]}})
    k('rollout','status','deployment/dsh-credential-vault','--timeout=150s')
    initialized=json.loads(k('exec','deployment/dsh-credential-vault','--','bao','operator','init','-key-shares=1','-key-threshold=1','-format=json'))
    operator={**initialized,'addresses':addresses,'caPrivateKey':ca_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode(),'caCertificate':ca.public_bytes(serialization.Encoding.PEM).decode(),'vaultImage':image,'createdAt':now.isoformat()}
    custody.parent.mkdir(parents=True,exist_ok=True);custody.write_bytes(protect(json.dumps(operator).encode()))
    run(['icacls',str(custody),'/inheritance:r','/grant:r',os.environ['USERNAME']+':F'])
    k('exec','-i','deployment/dsh-credential-vault','--','bao','write','-format=json','sys/unseal','-',source=json.dumps({'key':initialized['unseal_keys_b64'][0]}))
    configure(ns,operator)
    print(json.dumps({'vaultInitialized':True,'operatorCustody':str(custody),'vaultImage':image,'addresses':addresses,'keyShares':1,'threshold':1,'automaticUnseal':False}))

if __name__=='__main__':main()
