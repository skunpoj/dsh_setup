"""Verify the scoped pilot using an existing private Kerberos cache.

No password argument, credential export, real data query, source write or
permission change. Creates/deletes only its own bounded synthetic Livy session.
The caller supplies an isolated runtime, then destroys its ticket/cache.
"""
import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

TARGET='sandbox_da_agent_public_data'
PRINCIPAL='da-agent-system-user'
BASE='http://botdlk-gw3-p1.bot.or.th:28998'


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--pod',required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('Refuse to overwrite evidence')
    record={'startedAtUTC':datetime.now(timezone.utc).isoformat(),'principal':PRINCIPAL,'sandbox':TARGET,
       'sourceDataReadOrWritten':False,'permissionsChanged':False,'credentialValuesExported':False,
       'scope':'Dedicated temporary No Internet pod and ticket cache; metadata and synthetic driver/executor network probes'}
    session=None
    def kube(command,source=None):
        p=subprocess.run(['kubectl','--request-timeout=25s','-n','llm','exec','-i',args.pod,'--',*command],input=source,
            capture_output=True,text=True,encoding='utf8',timeout=40)
        if p.returncode:raise RuntimeError('Private runtime operation failed: '+p.stderr[:180])
        return p.stdout
    def api(method,path,payload=None):
        command=['curl','--disable','--negotiate','-u',':','--noproxy','*','--max-time','25','--silent','--show-error',
          '--request',method,'--write-out','\n%{http_code}',BASE+path]
        if payload is not None:command+=['--header','Content-Type: application/json','--data-binary','@-']
        raw=kube(command,json.dumps(payload) if payload is not None else None)
        body,_,status=raw.rpartition('\n')
        if not status.startswith('2'):raise RuntimeError('Livy '+method+' '+path+' HTTP '+status)
        return json.loads(body) if body.strip() else {}
    def save():args.output.write_text(json.dumps(record,indent=2),encoding='utf8')
    try:
        tickets=kube(['klist','-c','FILE:/tmp/dsh-system-ccache'])
        record['kerberosPrincipalVerified']='Default principal: '+PRINCIPAL+'@BOT.OR.TH' in tickets
        if not record['kerberosPrincipalVerified']:raise RuntimeError('Kerberos cache principal differs from requested system account')
        current=api('GET','/sessions');record['authenticatedLivyGetSucceeded']=True
        record['existingSessionCount']=len(current.get('sessions',[]))
        if record['existingSessionCount']:raise RuntimeError('Other Livy sessions are active; defer synthetic execution')
        created=api('POST','/sessions',{'kind':'pyspark','name':'dsh-system-pilot-'+datetime.now(timezone.utc).strftime('%H%M%S'),
           'driverMemory':'2g','executorMemory':'2g','driverCores':1,'executorCores':1,'numExecutors':1,
           'conf':{'spark.dynamicAllocation.enabled':'false','spark.executor.instances':'1',
                   'spark.yarn.stagingDir':'/tmp/dsh-system-pilot-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}})
        session=created['id'];record['syntheticSessionId']=session;save();print(json.dumps({'createdSyntheticSystemSession':session}),flush=True)
        deadline=time.monotonic()+240
        while True:
            state=api('GET',f'/sessions/{session}')
            if state['state']=='idle':break
            if state['state'] in {'dead','error','killed','shutting_down'} or time.monotonic()>deadline:
                record['sessionState']=state['state'];raise RuntimeError('System-account session did not become ready: '+state['state'])
            time.sleep(5)
        owner=state.get('owner','');record['livyOwnerIsSystemAccount']=owner.lower().split('@')[0].split('\\')[-1]==PRINCIPAL
        if not record['livyOwnerIsSystemAccount']:raise RuntimeError('Livy owner identity mismatch')
        code=r'''import json,socket
target='sandbox_da_agent_public_data'
result={'sparkUser':sc.sparkUser(),'catalogImplementation':spark.conf.get('spark.sql.catalogImplementation')}
result['defaultFileSystem']=str(sc._jvm.org.apache.hadoop.fs.FileSystem.getDefaultUri(sc._jsc.hadoopConfiguration()))
matches=[str(row[0]) for row in spark.sql("SHOW DATABASES LIKE 'sandbox_da_agent_public_data'").collect()]
result['targetVisibleInThisCatalog']=target in matches
if result['targetVisibleInThisCatalog']:
 db=spark.catalog.getDatabase(target);result['sandboxLocation']=db.locationUri;result['tableCount']=len(spark.catalog.listTables(target))
 path=sc._jvm.org.apache.hadoop.fs.Path(db.locationUri);fs=path.getFileSystem(sc._jsc.hadoopConfiguration());checks={}
 for action in ['READ','WRITE']:
  try:fs.access(path,getattr(sc._jvm.org.apache.hadoop.fs.permission.FsAction,action));checks[action]='allowed-by-access-check'
  except Exception as e:checks[action]={'result':'not-established','exceptionType':type(e).__name__}
 result['hdfsAccessChecks']=checks
def network_probe(_):
 import socket
 rows=[]
 for host,port in [('github.com',443),('1.1.1.1',443),('8.8.8.8',53)]:
  try:
   s=socket.create_connection((host,port),timeout=3);s.close();rows.append({'host':host,'port':port,'tcpConnected':True})
  except Exception as e:rows.append({'host':host,'port':port,'tcpConnected':False,'errorType':type(e).__name__})
 return rows
result['driverNetwork']=network_probe(None)
result['executorNetwork']=sc.parallelize([1],1).map(network_probe).collect()
print('DSH_SYSTEM_PILOT='+json.dumps(result))
'''
        statement=api('POST',f'/sessions/{session}/statements',{'code':code})['id'];deadline=time.monotonic()+120
        while True:
            response=api('GET',f'/sessions/{session}/statements/{statement}')
            if response['state']=='available':break
            if time.monotonic()>deadline:raise RuntimeError('System metadata statement deadline exceeded')
            time.sleep(3)
        output=response.get('output',{})
        if output.get('status')!='ok':
            record['statementErrorType']=output.get('ename');raise RuntimeError('System-account metadata statement failed')
        text=output.get('data',{}).get('text/plain','')
        line=next((line for line in text.splitlines() if line.startswith('DSH_SYSTEM_PILOT=')),None)
        if not line:raise RuntimeError('System metadata sentinel missing')
        result=json.loads(line.split('=',1)[1]);record['metadata']=result
        record['sparkIdentityIsSystemAccount']=result['sparkUser'].lower().split('@')[0].split('\\')[-1]==PRINCIPAL
        record['exclusiveSandboxPermissionsEstablished']=False
        record['outOfScopeNegativeFixture']='Not supplied; no genuine internal dataset was queried'
        record['status']='metadata-test-completed' if record['sparkIdentityIsSystemAccount'] else 'identity-mismatch'
    except Exception as e:
        record['status']='stopped';record['reason']=str(e)
    finally:
        if session is not None:
            try:
                api('DELETE',f'/sessions/{session}');record['syntheticSessionDeleteAccepted']=True
                deadline=time.monotonic()+35
                while time.monotonic()<deadline:
                    if session not in [s['id'] for s in api('GET','/sessions').get('sessions',[])]:
                        record['syntheticSessionAbsentAfterDelete']=True;break
                    time.sleep(2)
            except Exception as e:record['sessionCleanupErrorType']=type(e).__name__
        record['finishedAtUTC']=datetime.now(timezone.utc).isoformat();save()
    print(json.dumps(record),flush=True)


if __name__=='__main__':main()
