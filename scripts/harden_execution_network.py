"""Remove external DNS forwarding from offline workers; constrain online egress.

No model restart, source-data grant or shared LiteLLM policy change. On failure,
restore saved policies and deployment specifications, never workspace contents.
"""
import argparse
import concurrent.futures
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from run_isolation_canary import legacy_fingerprint


def kube(*args, data=None):
    p=subprocess.run(['kubectl','--request-timeout=30s','-n','llm',*args],input=data,text=True,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.strip())
    return p.stdout


def policies():
    internal={'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'llm'}},
              'podSelector':{'matchLabels':{'app':'litellm'}}}
    dns={'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},
         'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}
    base={'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy'}
    return [{**base,'metadata':{'name':'dsh-offline-egress','namespace':'llm'},'spec':{
        'podSelector':{'matchLabels':{'dsh.bot.or.th/egress-mode':'offline'}},'policyTypes':['Egress'],
        'egress':[{'to':[internal],'ports':[{'protocol':'TCP','port':4000}]}]}},
      {**base,'metadata':{'name':'dsh-online-egress','namespace':'llm'},'spec':{
        'podSelector':{'matchLabels':{'dsh.bot.or.th/egress-mode':'online'}},'policyTypes':['Egress'],
        'egress':[{'to':[internal],'ports':[{'protocol':'TCP','port':4000}]},
          {'to':[dns],'ports':[{'protocol':'UDP','port':53},{'protocol':'TCP','port':53}]},
          {'to':[{'ipBlock':{'cidr':'0.0.0.0/0','except':['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16',
             '127.0.0.0/8','169.254.0.0/16','100.64.0.0/10','224.0.0.0/4']}}]}]}}]


PROBE=r'''
import concurrent.futures,json,os,socket,struct,subprocess,urllib.request,urllib.error
def curl(url):
 p=subprocess.run(['curl','--noproxy','*','--max-time','3','-s','-o','/dev/null','-w','%{http_code}',url],capture_output=True,text=True)
 return {'target':url,'exitCode':p.returncode,'HTTP':p.stdout}
def dns(server,kind):
 try:
  s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM if kind=='UDP' else socket.SOCK_STREAM);s.settimeout(2)
  if kind=='UDP':
   name=b''.join(bytes([len(x)])+x.encode() for x in 'containment-test.invalid'.split('.'))+b'\0'
   query=struct.pack('!HHHHHH',1234,256,1,0,0,0)+name+struct.pack('!HH',1,1)
   s.sendto(query,(server,53));s.recvfrom(512)
  else:s.connect((server,53))
  return {'server':server,'protocol':kind,'denied':False}
 except (OSError,socket.timeout):return {'server':server,'protocol':kind,'denied':True}
 finally:s.close()
req=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',
 data=json.dumps({'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'Reply exactly NETWORK_INTERNAL_OK'}],
 'max_tokens':32,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}).encode(),
 headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
with urllib.request.urlopen(req,timeout=30) as response:answer=json.load(response)
internal=answer['choices'][0]['message']['content'].strip()=='NETWORK_INTERNAL_OK';assert internal
mode=os.environ['DSH_ENVIRONMENT']
urls=['https://github.com','https://pypi.org','https://registry.npmjs.org']
if mode=='secure':urls+=['https://1.1.1.1']
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:public=list(pool.map(curl,urls))
record={'environment':mode,'internalInferenceExact':internal,'public':public,'uid':os.getuid()}
if mode=='secure':
 assert all(r['exitCode']!=0 and r['HTTP']=='000' for r in public)
 checks=[dns(DNS_IP,'UDP'),dns(DNS_IP,'TCP'),dns('8.8.8.8','UDP')]
 assert all(r['denied'] for r in checks);record['dnsDenied']=checks
 assert all(socket.gethostbyname(h)==MODEL_IP for h in ['litellm','litellm.llm.svc.cluster.local'])
 record['internalHostAliasesResolve']=True
else:
 assert all(r['HTTP']=='200' for r in public)
 s=socket.socket();s.settimeout(2)
 try:s.connect((POSTGRES_IP,5432));raise RuntimeError('Unapproved internal service reachable')
 except (OSError,socket.timeout):record['unapprovedInternalPortDenied']=True
 finally:s.close()
print(json.dumps(record))
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--inference-only-profile', action='store_true', help='Explicitly excludes Kerberos/Livy/HDFS; never use for a datalake-enabled worker')
    args=ap.parse_args()
    if not args.inference_only_profile:
        raise RuntimeError('Required internal Kerberos/datalake endpoints must be inventoried first. This profile is inference-only and must not silently block RDT connections.')
    args.output.mkdir(parents=True,exist_ok=False)
    ds=json.loads(kube('get','deploy','-o','json'))['items']
    offline=[d for d in ds if d['spec']['template']['metadata'].get('labels',{}).get('dsh.bot.or.th/egress-mode')=='offline' and d['spec']['replicas']==1]
    online=[d for d in ds if d['spec']['template']['metadata'].get('labels',{}).get('dsh.bot.or.th/egress-mode')=='online' and d['spec']['replicas']==1]
    old=[json.loads(kube('get','networkpolicy',n,'-o','json')) for n in ['dsh-offline-egress','dsh-online-egress']]
    (args.output/'rollback.json').write_text(json.dumps({'deployments':offline,'policies':old},indent=2),encoding='utf-8')
    model=json.loads(kube('get','service','litellm','-o','json'))['spec']['clusterIP']
    dns_services=json.loads(subprocess.check_output(['kubectl','--request-timeout=30s','-n','kube-system','get','service','-l','k8s-app=kube-dns','-o','json'],text=True))['items']
    if len(dns_services)!=1:raise RuntimeError('Expected one labelled cluster DNS service')
    dns=dns_services[0]['spec']['clusterIP']
    postgres=json.loads(kube('get','service','litellm-postgres','-o','json'))['spec']['clusterIP']
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'legacyBefore':legacy_fingerprint(),'modelRestarted':False}
    try:
        control="import socket,json;s=socket.create_connection(("+repr(postgres)+",5432),timeout=3);s.close();print(json.dumps({'actualInternalServiceInitiallyReachable':True}))"
        record['onlineNegativeControl']=json.loads(kube('exec','-i','deploy/dsh-internet','--','python3','-',data=control))
        for d in offline:
            spec=d['spec']['template']['spec'];aliases=[a for a in spec.get('hostAliases',[]) if a['ip']!=model]
            aliases.append({'ip':model,'hostnames':['litellm','litellm.llm','litellm.llm.svc','litellm.llm.svc.cluster.local']})
            kube('patch','deploy',d['metadata']['name'],'--type=merge','-p',json.dumps({'spec':{'template':{'spec':{
                 'dnsPolicy':'None','dnsConfig':{'nameservers':['127.0.0.1'],'options':[{'name':'ndots','value':'1'}]},'hostAliases':aliases}}}}))
            kube('rollout','status','deploy/'+d['metadata']['name'],'--timeout=180s')
        for p in policies():kube('apply','-f','-',data=json.dumps(p))
        code=PROBE.replace('DNS_IP',repr(dns)).replace('MODEL_IP',repr(model)).replace('POSTGRES_IP',repr(postgres))
        def test(d):
            name=d['metadata']['name']
            return {'runtime':name,**json.loads(kube('exec','-i','deploy/'+name,'--','python3','-',data=code))}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:record['workers']=list(pool.map(test,offline+online))
        record['legacyAfter']=legacy_fingerprint();assert record['legacyBefore']==record['legacyAfter']
        record['status']='passed'
    except Exception as e:
        record['status']='failed';record['error']=str(e)
        for p in old:
            kube('patch','networkpolicy',p['metadata']['name'],'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':p['spec']}]))
        for d in offline:
            kube('patch','deploy',d['metadata']['name'],'--type=json','-p',json.dumps([{'op':'replace','path':'/spec','value':d['spec']}]))
            kube('rollout','status','deploy/'+d['metadata']['name'],'--timeout=180s')
        record['specificationsRestored']=True;raise
    finally:
        (args.output/'execution-network-live.json').write_text(json.dumps(record,indent=2),encoding='utf-8');print(json.dumps(record),flush=True)


if __name__=='__main__':main()
