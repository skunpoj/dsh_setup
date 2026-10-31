"""Render a configurable wildcard app route and least-privilege inventory reader."""
import argparse,hashlib,ipaddress,json,re
from pathlib import Path
import yaml

def render(s):
    base={'namespace','domain','gatewayService','tlsSecret','runtimeImage','apiCIDRs','tlsMode'}
    if not base.issubset(s) or set(s)-base-{'tlsMode','controllerDefaultTls'}:raise ValueError('Use only documented settings')
    mode=s['tlsMode']
    if mode not in {'dedicated','controller-default'}:raise ValueError('Unknown TLS mode')
    if mode=='controller-default':
        ref=s.get('controllerDefaultTls',{})
        if set(ref)!={'namespace','secretName','certificateSha256'} or not re.fullmatch(r'[a-f0-9]{64}',ref.get('certificateSha256','')):raise ValueError('Pin the qualified controller default certificate')
        for key in ['namespace','secretName']:
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',ref[key]):raise ValueError('Invalid controller certificate reference')
    elif 'controllerDefaultTls' in s:raise ValueError('Default certificate evidence requires controller-default mode')
    for key in ['namespace','gatewayService','tlsSecret']:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',s[key]):raise ValueError('Invalid resource name')
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}',s['domain']):raise ValueError('Invalid domain')
    if not re.fullmatch(r'[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}',s['runtimeImage']):raise ValueError('Use an immutable image digest')
    if not s['apiCIDRs']:raise ValueError('Explicit Kubernetes API host CIDRs required')
    peers=[]
    for value in s['apiCIDRs']:
        n=ipaddress.ip_network(value,strict=True)
        if n.prefixlen!=n.max_prefixlen or n.is_global or n.is_loopback:raise ValueError('Use explicit private Kubernetes API /32 or /128 hosts')
        peers.append({'ipBlock':{'cidr':str(n)}})
    ns=s['namespace'];name='dsh-app-host-inventory';sa='dsh-app-host-inventory';rbac='rbac.authorization.k8s.io/v1';role=ns+'-dsh-app-host-inventory'
    source=(Path(__file__).parent/'app_host_inventory.py').read_text(encoding='utf-8');cm=name+'-'+hashlib.sha256(source.encode()).hexdigest()[:12]
    def obj(kind,n,**body):return {'apiVersion':rbac if kind in ['Role','RoleBinding','ClusterRole','ClusterRoleBinding'] else 'apps/v1' if kind=='Deployment' else 'networking.k8s.io/v1' if kind in ['NetworkPolicy','Ingress'] else 'v1','kind':kind,'metadata':{'name':n,**({}if kind.startswith('Cluster')else {'namespace':ns})},**body}
    ref=lambda kind,n:{'apiGroup':'rbac.authorization.k8s.io','kind':kind,'name':n}
    subject=[{'kind':'ServiceAccount','name':sa,'namespace':ns}]
    docs=[obj('ServiceAccount',sa),obj('ClusterRole',role,rules=[{'apiGroups':['networking.k8s.io'],'resources':['ingresses'],'verbs':['get','list']}]),obj('ClusterRoleBinding',role,subjects=subject,roleRef=ref('ClusterRole',role)),obj('Role',name,rules=[{'apiGroups':[''],'resources':['configmaps'],'resourceNames':[name],'verbs':['get','update']}]),obj('RoleBinding',name,subjects=subject,roleRef=ref('Role',name)),obj('ConfigMap',cm,immutable=True,data={'inventory.py':source}),obj('ConfigMap',name,data={'inventory.json':json.dumps({'domain':s['domain'],'observedAt':None,'reservedNames':[],'wildcardReady':False})}),obj('Deployment',name,spec={'replicas':1,'selector':{'matchLabels':{'app':name}},'template':{'metadata':{'labels':{'app':name}},'spec':{'serviceAccountName':sa,'containers':[{'name':'inventory','image':s['runtimeImage'],'command':['python3','/source/inventory.py'],'env':[{'name':'POD_NAMESPACE','value':ns},{'name':'DSH_APP_DOMAIN','value':s['domain']},{'name':'DSH_GATEWAY_SERVICE','value':s['gatewayService']},{'name':'DSH_APP_INVENTORY_CONFIGMAP','value':name}],'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},'resources':{'requests':{'cpu':'25m','memory':'32Mi'},'limits':{'cpu':'200m','memory':'128Mi'}},'volumeMounts':[{'name':'source','mountPath':'/source','readOnly':True}]}],'volumes':[{'name':'source','configMap':{'name':cm}}]}}}),obj('NetworkPolicy',name,spec={'podSelector':{'matchLabels':{'app':name}},'policyTypes':['Ingress','Egress'],'ingress':[],'egress':[{'to':peers,'ports':[{'protocol':'TCP','port':443},{'protocol':'TCP','port':6443}]}]}),obj('Ingress','dsh-user-app-wildcard',spec={'ingressClassName':'nginx',**({'tls':[{'hosts':['*.'+s['domain']],'secretName':s['tlsSecret']}]} if mode=='dedicated' else {}),'rules':[{'host':'*.'+s['domain'],'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':s['gatewayService'],'port':{'number':3080}}}}]}}]})]
    if mode=='controller-default':
        docs[-1]['metadata']['annotations']={'nginx.ingress.kubernetes.io/force-ssl-redirect':'true'}
    return docs

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--settings',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--controller-default-certificate',type=Path);p.add_argument('--controller-arguments',type=Path);a=p.parse_args()
    if a.output.exists():raise ValueError('Refusing to overwrite candidate')
    settings=json.loads(a.settings.read_text(encoding='utf-8'))
    if settings.get('tlsMode')=='controller-default':
        if not a.controller_default_certificate or not a.controller_arguments:raise ValueError('Qualify the running controller default certificate before rendering')
        from controller_default_tls_preflight import validate
        validate(settings,json.loads(a.controller_arguments.read_text(encoding='utf-8')),a.controller_default_certificate.read_bytes())
    docs=render(settings)
    docs[-1]['metadata']['annotations']={**docs[-1]['metadata'].get('annotations',{}),'nginx.ingress.kubernetes.io/proxy-buffering':'off','nginx.ingress.kubernetes.io/proxy-read-timeout':'3600','nginx.ingress.kubernetes.io/proxy-send-timeout':'3600','nginx.ingress.kubernetes.io/proxy-body-size':'64m'}
    a.output.write_text(yaml.safe_dump_all(docs,sort_keys=False),encoding='utf-8');print(json.dumps({'objects':len(docs),'wildcardRouteLast':True}))
