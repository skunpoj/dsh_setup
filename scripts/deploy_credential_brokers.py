"""Deploy isolated broker services from reviewed source and operator-owned profile files."""
import argparse,base64,hashlib,json,os,re,subprocess
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

PUBLIC_EXCEPT=['0.0.0.0/8','10.0.0.0/8','100.64.0.0/10','127.0.0.0/8','169.254.0.0/16','172.16.0.0/12','192.168.0.0/16','224.0.0.0/3']

def validate_owner_lists(profiles):
    """'allowedOwners' must be a list of account ids u-<32 hex> (at most 200); an empty list means nobody may use the profile."""
    for name, profile in sorted(profiles.items()):
        owners = profile.get('allowedOwners')
        if owners is None:
            continue
        if not (isinstance(owners, list) and len(owners) <= 200 and all(isinstance(o, str) and re.fullmatch(r'u-[a-f0-9]{32}', o) for o in owners)):
            raise ValueError('Profile %s: allowedOwners must be a list of account ids u-<32 hex>' % name)


def eda_egress(profiles):
    """One rule per 'eda-session' profile: plain http to the named in-cluster pods only. A ClusterIP in an ipBlock is not reliable (the CNI sees the pod address
    after translation), so the destination is a namespace plus ONE pod label, like the workspace policy for the EDA."""
    rules=[]
    for name,profile in sorted(profiles.items()):
        if profile.get('auth')!='eda-session':continue
        selector=profile.get('egressPods') or {}
        namespace,labels,port=selector.get('namespace'),selector.get('labels'),profile.get('port')
        if not(isinstance(namespace,str) and re.fullmatch(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?',namespace) and isinstance(labels,dict) and len(labels)==1
               and all(isinstance(k,str) and isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9._/-]{1,63}',k) and re.fullmatch(r'[A-Za-z0-9._-]{1,63}',v) for k,v in labels.items())
               and type(port) is int and 1<=port<=65535):
            raise ValueError('Profile %s needs egressPods {namespace, one label} and a port' % name)
        rules.append({'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':namespace}},'podSelector':{'matchLabels':labels}}],'ports':[{'port':port,'protocol':'TCP'}]})
    return rules

def broker_egress(mode,profiles):
    validate_owner_lists(profiles)
    egress=[{'to':[{'podSelector':{'matchLabels':{'app':'dsh-credential-vault'}}}],'ports':[{'port':8200,'protocol':'TCP'}]},{'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}],'ports':[{'port':53,'protocol':'UDP'},{'port':53,'protocol':'TCP'}]}]
    if mode=='on':
        egress.append({'to':[{'ipBlock':{'cidr':'0.0.0.0/0','except':PUBLIC_EXCEPT}}],'ports':[{'port':443,'protocol':'TCP'}]})
    else:
        addresses=sorted({ip for profile in profiles.values() if profile.get('auth')!='eda-session' for ip in profile.get('allowedAddresses',[])})
        if addresses:egress.append({'to':[{'ipBlock':{'cidr':ip+'/32'}} for ip in addresses],'ports':[{'port':443,'protocol':'TCP'}]})
        egress.extend(eda_egress(profiles))
    return egress

def main():
    p=argparse.ArgumentParser();p.add_argument('--namespace',default='llm');p.add_argument('--image',required=True);p.add_argument('--profiles-off',required=True);p.add_argument('--profiles-on',required=True);p.add_argument('--enterprise-ca-configmap');a=p.parse_args()
    if '@sha256:' not in a.image:raise ValueError('Pinned runtime image required')
    def k(*args,body=None):
        r=subprocess.run(['kubectl','-n',a.namespace,*args],input=json.dumps(body).encode() if body else None,capture_output=True,timeout=90)
        if r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace')[:300])
        return r.stdout.decode('utf-8')
    def apply(obj):
        # These two deployments were created by this bootstrap using client-side apply.
        # Transfer only these owned broker deployments to the same rollout's SSA manager.
        own=obj.get('kind')=='Deployment' and obj['metadata']['name'] in ['dsh-credential-off','dsh-credential-on']
        return k('apply','--server-side','--field-manager=dsh-credential-rollout',*(['--force-conflicts'] if own else []),'-f','-',body=obj)
    ips={n:json.loads(k('get','service',n,'-o','json'))['spec']['clusterIP'] for n in ['dsh-credential-vault','dsh-credential-off','dsh-credential-on','dsh-credential-tools']}
    # No keys cross into a user execution workload. Each broker receives only its own key.
    existing=json.loads(k('get','secret','dsh-credential-gateway-key','-o','json'))
    if not all(m in existing.get('data',{}) for m in ['off','on']):
        keys={m:base64.urlsafe_b64encode(os.urandom(48)).decode() for m in ['off','on']}
        apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':'dsh-credential-gateway-key'},'type':'Opaque','stringData':keys})
    code=(Path(__file__).parent/'credential_broker.js').read_text(encoding='utf-8');digest=hashlib.sha256(code.encode()).hexdigest();source='dsh-credential-source-'+digest[:12]
    apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':source},'immutable':True,'data':{'credential_broker.js':code}})
    for mode in ['off','on']:
        name='dsh-credential-'+mode
        found=subprocess.run(['kubectl','-n',a.namespace,'get','secret',name+'-envelope-key','-o','name'],capture_output=True,timeout=30)
        if found.returncode:
            private=rsa.generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
            apply({'apiVersion':'v1','kind':'Secret','metadata':{'name':name+'-envelope-key'},'type':'Opaque','stringData':{'key.pem':private}})
        profiles=json.loads(Path(getattr(a,'profiles_'+mode)).read_text(encoding='utf-8'))
        config={'environment':mode,'port':8443,'encryptionKeyFile':'/envelope/key.pem','vault':{'url':'https://'+ips['dsh-credential-vault']+':8200','mount':'dsh-'+mode,'tokenFile':'/vault-token/token','caFile':'/tls/ca.pem'},'gatewayKeyFile':'/gateway-key/key','auditFile':'/audit/usage.jsonl','tls':{'keyFile':'/tls/tls.key','certFile':'/tls/tls.crt'},'profiles':profiles}
        configtext=json.dumps(config);configname=name+'-config-'+hashlib.sha256(configtext.encode()).hexdigest()[:12]
        apply({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':configname},'immutable':True,'data':{'broker.json':configtext}})
        apply({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':name+'-audit'},'spec':{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}}})
        volumes=[{'name':'envelope','secret':{'secretName':name+'-envelope-key','defaultMode':288}},{'name':'source','configMap':{'name':source}},{'name':'config','configMap':{'name':configname}},{'name':'tls','secret':{'secretName':name+'-tls','defaultMode':288}},{'name':'vault-token','secret':{'secretName':name+'-vault-token','defaultMode':288}},{'name':'gateway-key','secret':{'secretName':'dsh-credential-gateway-key','items':[{'key':mode,'path':'key'}],'defaultMode':288}},{'name':'audit','persistentVolumeClaim':{'claimName':name+'-audit'}}]
        mounts=[{'name':n,'mountPath':path,'readOnly':True} for n,path in [('envelope','/envelope'),('source','/broker'),('config','/config'),('tls','/tls'),('vault-token','/vault-token'),('gateway-key','/gateway-key')]]+[{'name':'audit','mountPath':'/audit'}]
        if a.enterprise_ca_configmap:
            volumes.append({'name':'enterprise-ca','configMap':{'name':a.enterprise_ca_configmap,'items':[{'key':'root.pem','path':'root.pem'}]}});mounts.append({'name':'enterprise-ca','mountPath':'/enterprise-ca','readOnly':True})
        apply({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name},'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app':name}},'template':{'metadata':{'labels':{'app':name,'dsh-credential-broker':'true'},'annotations':{'dsh.credential/source-sha256':digest}},'spec':{'automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'broker','image':a.image,'command':['node','/broker/credential_broker.js'],'env':[{'name':'DSH_CREDENTIAL_BROKER_CONFIG','value':'/config/broker.json'}],'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},'resources':{'requests':{'cpu':'50m','memory':'64Mi'},'limits':{'cpu':'500m','memory':'192Mi'}},'ports':[{'containerPort':8443}],'readinessProbe':{'httpGet':{'path':'/health','port':8443,'scheme':'HTTPS'},'initialDelaySeconds':2,'periodSeconds':5},'volumeMounts':mounts}],'volumes':volumes}}}})
        egress=broker_egress(mode,profiles)
        apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':name+'-isolation'},'spec':{'podSelector':{'matchLabels':{'app':name}},'policyTypes':['Ingress','Egress'],'ingress':[{'from':[{'podSelector':{'matchLabels':{'app':'dsh-environment-gateway'}}},{'podSelector':{'matchLabels':{'app':'dsh-credential-canary'}}}],'ports':[{'port':8443,'protocol':'TCP'}]}],'egress':egress}})
        k('rollout','status','deployment/'+name,'--timeout=90s')
    print(json.dumps({'brokersDeployed':True,'sourceSHA256':digest,'addresses':ips,'newPersistentStorageGiB':3,'newCloudInstances':0}))

if __name__=='__main__':main()
