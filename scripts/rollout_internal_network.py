"""Datalake-aware restricted egress: exact DNS names, KDCs and Livy endpoint.

Kerberos network reachability is not an AD login or a grant of RDT permissions.
The gateway/model server are not restarted. Workload data is never rolled back.
"""
import argparse
import concurrent.futures
import hashlib
import ipaddress
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from harden_execution_network import policies as base_policies
from run_isolation_canary import legacy_fingerprint

ROOT=Path(__file__).resolve().parents[1]


def kube(*args,data=None):
    p=subprocess.run(['kubectl','--request-timeout=30s','-n','llm',*args],input=data,text=True,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.strip())
    return p.stdout


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--endpoints',type=Path,required=True)
    ap.add_argument('--image',required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    endpoints=json.loads(args.endpoints.read_text(encoding='utf-8-sig'))
    hosts={r['host']:r['addresses'] for r in endpoints}
    expected={'bot-dc-p1.bot.or.th','bot-dc-p2.bot.or.th','bot-dc-p3.bot.or.th','bot-dc-p4.bot.or.th','workspace.bot.or.th','botdlk-gw3-p1.bot.or.th'}
    if set(hosts)!=expected or not all(hosts.values()):raise ValueError('Complete verified internal service inventory required')
    for values in hosts.values():
        for address in values:ipaddress.ip_address(address)
    code='import socket,json\nhosts='+repr(hosts)+'\nprint(json.dumps({h:sorted({v[4][0] for v in socket.getaddrinfo(h,None,socket.AF_INET)}) for h in hosts}))'
    observed=json.loads(kube('exec','-i','deploy/dsh-internet','--','python3','-',data=code))
    if any(set(observed[h])!=set(hosts[h]) for h in hosts):raise RuntimeError('Pod and operator DNS inventory differ; review without changing policies')
    dns_services=json.loads(subprocess.check_output(['kubectl','-n','kube-system','get','service','-l','k8s-app=kube-dns','-o','json'],text=True))['items']
    if len(dns_services)!=1:raise RuntimeError('Expected one explicitly labelled cluster DNS service')
    core=dns_services[0]['spec']['clusterIP']
    model=json.loads(kube('get','service','litellm','-o','json'))['spec']['clusterIP']
    postgres=json.loads(kube('get','service','litellm-postgres','-o','json'))['spec']['clusterIP']
    deployments=json.loads(kube('get','deploy','-o','json'))['items']
    offline=[d for d in deployments if d['spec']['replicas']==1 and d['spec']['template']['metadata'].get('labels',{}).get('dsh.bot.or.th/egress-mode')=='offline']
    online=[d for d in deployments if d['spec']['replicas']==1 and d['spec']['template']['metadata'].get('labels',{}).get('dsh.bot.or.th/egress-mode')=='online']
    old=[json.loads(kube('get','networkpolicy',n,'-o','json')) for n in ['dsh-offline-egress','dsh-online-egress']]
    (args.output/'rollback.json').write_text(json.dumps({'deployments':offline,'policies':old},indent=2),encoding='utf-8')
    allowed=sorted(expected|{'litellm.llm.svc.cluster.local','litellm.llm.svc','litellm.llm','litellm',
        '_kerberos._tcp.bot.or.th','_kerberos._udp.bot.or.th'})
    source=(ROOT/'scripts/internal_dns_allowlist.py').read_text(encoding='utf-8')
    krb='[libdefaults]\n default_realm = BOT.OR.TH\n dns_lookup_realm = false\n dns_lookup_kdc = true\n rdns = false\n dns_canonicalize_hostname = false\n[domain_realm]\n .bot.or.th = BOT.OR.TH\n bot.or.th = BOT.OR.TH\n'
    data={'resolver.py':source,'allowed.json':json.dumps(allowed),'krb5.conf':krb}
    name='dsh-internal-dns-'+hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()[:12]
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'internalServiceInventory':hosts,'legacyBefore':legacy_fingerprint(),
        'policyScope':'Harness and local execution pods only; remote Livy/Spark workers not attested',
        'realRdtPermissionGranted':False,'dnsResolverSourceSHA256':hashlib.sha256(source.encode()).hexdigest(),'configMap':name}
    changed=False
    def apply(obj):kube('apply','-f','-',data=json.dumps(obj))
    try:
        control='import socket,json;s=socket.create_connection(('+repr(postgres)+',5432),timeout=3);s.close();print(json.dumps({"unrelatedInternalServiceReachableBefore":True}))'
        record['onlineNegativeControl']=json.loads(kube('exec','-i','deploy/dsh-internet','--','python3','-',data=control))
        apply({'apiVersion':'v1','kind':'ConfigMap','immutable':True,'metadata':{'name':name,'namespace':'llm'},'data':data})
        apply({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'dsh-internal-dns','namespace':'llm'},'spec':{
          'replicas':1,'selector':{'matchLabels':{'app':'dsh-internal-dns'}},'template':{'metadata':{'labels':{'app':'dsh-internal-dns'}},'spec':{
          'automountServiceAccountToken':False,'securityContext':{'runAsUser':10001,'runAsGroup':10001,'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},
          'containers':[{'name':'resolver','image':args.image,'command':['python3','/config/resolver.py'],
            'env':[{'name':'DNS_UPSTREAM','value':core}], 'ports':[{'containerPort':5353,'protocol':'UDP'},{'containerPort':5353,'protocol':'TCP'},{'containerPort':8080}],
            'securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},
            'resources':{'requests':{'cpu':'50m','memory':'32Mi'},'limits':{'cpu':'250m','memory':'128Mi'}},
            'readinessProbe':{'httpGet':{'path':'/health','port':8080}},'livenessProbe':{'httpGet':{'path':'/health','port':8080},'initialDelaySeconds':10},
            'volumeMounts':[{'name':'config','mountPath':'/config','readOnly':True}]}],
          'volumes':[{'name':'config','configMap':{'name':name}}]}}}})
        apply({'apiVersion':'v1','kind':'Service','metadata':{'name':'dsh-internal-dns','namespace':'llm'},'spec':{'selector':{'app':'dsh-internal-dns'},'ports':[
          {'name':'udp','port':53,'targetPort':5353,'protocol':'UDP'},{'name':'tcp','port':53,'targetPort':5353,'protocol':'TCP'}]}})
        apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-internal-dns-boundary','namespace':'llm'},'spec':{
          'podSelector':{'matchLabels':{'app':'dsh-internal-dns'}},'policyTypes':['Ingress','Egress'],
          'ingress':[{'from':[{'podSelector':{'matchLabels':{'dsh.bot.or.th/egress-mode':'offline'}}}],
             'ports':[{'protocol':'UDP','port':5353},{'protocol':'TCP','port':5353}]}],
          'egress':[{'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}],
             'ports':[{'protocol':'UDP','port':53},{'protocol':'TCP','port':53}]}]}})
        kube('rollout','status','deploy/dsh-internal-dns','--timeout=180s')
        resolver=json.loads(kube('get','service','dsh-internal-dns','-o','json'))['spec']['clusterIP']
        offline_policy,online_policy=base_policies()
        offline_policy['spec']['egress'].append({'to':[{'podSelector':{'matchLabels':{'app':'dsh-internal-dns'}}}],
                'ports':[{'protocol':'UDP','port':5353},{'protocol':'TCP','port':5353}]})
        kdcs=sorted({a for h,values in hosts.items() if h!='botdlk-gw3-p1.bot.or.th' for a in values})
        livy=hosts['botdlk-gw3-p1.bot.or.th']
        offline_policy['spec']['egress'].extend([
          {'to':[{'ipBlock':{'cidr':a+'/32'}} for a in kdcs],'ports':[{'protocol':'TCP','port':88},{'protocol':'UDP','port':88}]},
          {'to':[{'ipBlock':{'cidr':a+'/32'}} for a in livy],'ports':[{'protocol':'TCP','port':28998}]}])
        # Also exclude the corporate public-address KDC from Internet staging.
        online_policy['spec']['egress'][-1]['to'][0]['ipBlock']['except'] += [a+'/32' for a in kdcs if not ipaddress.ip_address(a).is_private and not a.startswith('100.64.')]
        # Add the resolver while old DNS still works, then move workers one at a time.
        interim=json.loads(json.dumps(old[0]));interim['spec']['egress']+=offline_policy['spec']['egress'][1:]
        apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'dsh-offline-egress','namespace':'llm'},'spec':interim['spec']})
        changed=True
        for d in offline:
            spec=json.loads(json.dumps(d['spec']['template']['spec']))
            spec['dnsPolicy']='None';spec['dnsConfig']={'nameservers':[resolver],'options':[{'name':'ndots','value':'1'}]}
            spec['volumes']=[v for v in spec['volumes'] if v['name']!='kerberos-config'];spec['volumes'].append({'name':'kerberos-config','configMap':{'name':name}})
            c=spec['containers'][0];c['volumeMounts']=[m for m in c['volumeMounts'] if m['name']!='kerberos-config'];c['volumeMounts'].append({'name':'kerberos-config','mountPath':'/kerberos-config','readOnly':True})
            c['env']=[e for e in c['env'] if e['name']!='KRB5_CONFIG'];c['env'].append({'name':'KRB5_CONFIG','value':'/kerberos-config/krb5.conf'})
            kube('patch','deploy',d['metadata']['name'],'--type=merge','-p',json.dumps({'spec':{'template':{'spec':spec}}}))
            kube('rollout','status','deploy/'+d['metadata']['name'],'--timeout=180s')
        apply(offline_policy);apply(online_policy)
        (args.output/'applied-policies.json').write_text(json.dumps([offline_policy,online_policy],indent=2),encoding='utf-8')
        probe=(ROOT/'scripts/verify_internal_network.py').read_text(encoding='utf-8')
        def test(d):
            return {'runtime':d['metadata']['name'],**json.loads(kube('exec','-i','deploy/'+d['metadata']['name'],'--','python3','-c',probe,
                data=json.dumps({'coreDNS':core,'postgres':postgres,'kdc':kdcs[0],'livy':livy[0],'resolver':resolver})))}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:record['workers']=list(pool.map(test,offline+online))
        record['legacyAfter']=legacy_fingerprint();assert record['legacyBefore']==record['legacyAfter'];record['status']='passed'
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        if changed:
            for p in old:kube('patch','networkpolicy',p['metadata']['name'],'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':p['spec']}]))
            for d in offline:
                kube('patch','deploy',d['metadata']['name'],'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':d['spec']}]))
                kube('rollout','status','deploy/'+d['metadata']['name'],'--timeout=180s')
            record['originalSpecificationsRestored']=True
        raise
    finally:
        (args.output/'internal-network-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record),flush=True)


if __name__=='__main__':main()
