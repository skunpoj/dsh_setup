"""Read-only Ingress inventory; update one dedicated ConfigMap, never an Ingress.

Runs separately from user workers and the authentication gateway. Its RBAC
cannot read Secrets, accounts, pods or files, or modify routes/workloads.
"""
import json, os, ssl, time, urllib.request
from datetime import datetime, timezone

TOKEN='/var/run/secrets/kubernetes.io/serviceaccount/token'
CA='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'

def summarize(items, domain, namespace, service, ingress_name):
    reserved=set();wildcard_ready=False;conflict=False
    for obj in items:
        own=obj['metadata']['namespace']==namespace and obj['metadata']['name']==ingress_name
        # NGINX aliases can occupy a host even without a spec.rules entry.
        aliases=obj['metadata'].get('annotations',{}).get('nginx.ingress.kubernetes.io/server-alias','')
        for alias in aliases.replace(',', ' ').split():
            alias=alias.lower()
            if alias=='*.'+domain:conflict=True
            elif alias.endswith('.'+domain):
                name=alias[:-len(domain)-1]
                if '.' not in name:
                    if '*' in name or '~' in name:conflict=True
                    else:reserved.add(name)
        for rule in obj.get('spec',{}).get('rules',[]):
            host=rule.get('host','').lower()
            if host=='*.'+domain:
                paths=rule.get('http',{}).get('paths',[])
                expected=own and paths and all(p.get('backend',{}).get('service',{}).get('name')==service and p['backend']['service'].get('port',{}).get('number')==3080 for p in paths)
                if expected:wildcard_ready=True
                else:conflict=True
            elif host.endswith('.'+domain):
                name=host[:-len(domain)-1]
                if '.' not in name:reserved.add(name)
    return {'domain':domain,'observedAt':datetime.now(timezone.utc).isoformat(),'reservedNames':sorted(reserved),'wildcardReady':bool(wildcard_ready and not conflict),'wildcardConflict':conflict}

def main():
    namespace=os.environ['POD_NAMESPACE'];domain=os.environ['DSH_APP_DOMAIN'];service=os.environ['DSH_GATEWAY_SERVICE'];name=os.environ['DSH_APP_INVENTORY_CONFIGMAP']
    origin='https://'+os.environ['KUBERNETES_SERVICE_HOST']+':'+os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS','443')
    ctx=ssl.create_default_context(cafile=CA)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
    def api(method,path,body=None):
        token=open(TOKEN,encoding='utf-8').read().strip()
        q=urllib.request.Request(origin+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with opener.open(q,timeout=10) as r:return json.load(r)
    while True:
        try:
            items=[];cursor=''
            while True:
                from urllib.parse import urlencode
                response=api('GET','/apis/networking.k8s.io/v1/ingresses?'+urlencode({'limit':500,**({'continue':cursor} if cursor else {})}));items.extend(response['items']);cursor=response['metadata'].get('continue','')
                if not cursor:break
                if len(items)>10000:raise RuntimeError('Inventory exceeds bound')
            snapshot=summarize(items,domain,namespace,service,'dsh-user-app-wildcard')
            route='/api/v1/namespaces/'+namespace+'/configmaps/'+name
            current=api('GET',route);current['data']={'inventory.json':json.dumps(snapshot)};api('PUT',route,current)
            print(json.dumps({'inventoryUpdated':True,'reservedNames':len(snapshot['reservedNames']),'wildcardReady':snapshot['wildcardReady']}),flush=True)
        except Exception as e:
            # Retain last valid snapshot; gateway refuses new names when stale.
            print(json.dumps({'inventoryUpdated':False,'errorType':type(e).__name__}),flush=True)
        time.sleep(15)

if __name__=='__main__':main()
