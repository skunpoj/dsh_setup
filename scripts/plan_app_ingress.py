"""Check an app hostname against all visible Ingress rules; render, never apply.

Registry availability is separate from DNS, certificate and Ingress ownership.
Requires read access across namespaces, or a current operator-exported inventory.
"""
import argparse, hashlib, json, re, socket, subprocess
from pathlib import Path
import yaml

def plan(user, name, domain, namespace, service, secret, inventory):
    label=r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    if not re.fullmatch(r'[a-z0-9_.-]{3,30}',user):raise ValueError('Invalid account name')
    name=name or user.replace('_','-').replace('.','-')+'-jupyter'
    if not re.fullmatch(label,name) or len(name)<3:raise ValueError('Invalid application name')
    if not re.fullmatch(label+r'(?:\.'+label+r')+',domain) or len(domain)>190:raise ValueError('Invalid approved domain')
    for value in [namespace,service,secret]:
        if not re.fullmatch(label,value):raise ValueError('Invalid Kubernetes name')
    host=name+'.'+domain;conflicts=[]
    for item in inventory['items']:
        for rule in item.get('spec',{}).get('rules',[]):
            existing=rule.get('host','').lower()
            matches=existing==host or (existing.startswith('*.') and host.endswith(existing[1:]) and host.count('.')==existing.count('.'))
            if matches:conflicts.append({'namespace':item['metadata']['namespace'],'name':item['metadata']['name'],'host':existing})
    resource='dsh-app-'+hashlib.sha256(host.encode()).hexdigest()[:16]
    doc={'apiVersion':'networking.k8s.io/v1','kind':'Ingress','metadata':{'name':resource,'namespace':namespace,'labels':{'dsh.bot.or.th/app-url':name},'annotations':{'nginx.ingress.kubernetes.io/proxy-buffering':'off','nginx.ingress.kubernetes.io/proxy-read-timeout':'3600','nginx.ingress.kubernetes.io/proxy-send-timeout':'3600','nginx.ingress.kubernetes.io/proxy-body-size':'64m'}},'spec':{'ingressClassName':'nginx','tls':[{'hosts':[host],'secretName':secret}],'rules':[{'host':host,'http':{'paths':[{'path':'/','pathType':'Prefix','backend':{'service':{'name':service,'port':{'number':3080}}}}]}}]}}
    if any(x['metadata']['namespace']==namespace and x['metadata']['name']==resource for x in inventory['items']):
        if not conflicts:conflicts.append({'namespace':namespace,'name':resource,'host':'resource-name-already-present'})
    return {'hostname':host,'ingressName':resource,'availableInObservedIngressInventory':not conflicts,'conflicts':conflicts},doc

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user',required=True);p.add_argument('--name');p.add_argument('--domain',required=True)
    p.add_argument('--namespace',default='llm');p.add_argument('--service',default='dsh-environment-gateway');p.add_argument('--tls-secret',required=True)
    p.add_argument('--inventory',type=Path);p.add_argument('--kubectl',default='kubectl');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    inventory=json.loads(a.inventory.read_text(encoding='utf-8-sig')) if a.inventory else json.loads(subprocess.check_output([a.kubectl,'get','ingress','-A','-o','json','--request-timeout=30s'],text=True,encoding='utf-8',timeout=40))
    result,document=plan(a.user,a.name,a.domain,a.namespace,a.service,a.tls_secret,inventory)
    try:result['dnsAddresses']=sorted({v[4][0] for v in socket.getaddrinfo(result['hostname'],443)})
    except socket.gaierror:result['dnsAddresses']=[]
    result['note']='DNS resolution is not name ownership or certificate acceptance. No resource was applied.'
    if a.output.exists():raise ValueError('Refusing to overwrite candidate')
    if result['availableInObservedIngressInventory']:
        a.output.write_text(yaml.safe_dump(document,sort_keys=False),encoding='utf-8')
    print(json.dumps(result,indent=2))
    if not result['availableInObservedIngressInventory']:raise SystemExit(2)

if __name__=='__main__':main()
