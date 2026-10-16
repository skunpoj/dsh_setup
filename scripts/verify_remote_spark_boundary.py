"""Synthetic Livy driver/executor egress test using Windows SSPI Negotiate.

Creates only its own small session, reads no RDT, tests no data writes, and
always requests deletion of that session. Does not retrieve any credential.
One principal's entitlements are not assumed to represent other users.
"""
import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

BASE='http://botdlk-gw3-p1.bot.or.th:28998'


def api(method,path,payload=None):
    args=['curl.exe','--negotiate','-u',':','--noproxy','*','--max-time','25','--silent','--show-error',
          '--request',method,'--write-out','\n%{http_code}',BASE+path]
    text=None
    if payload is not None:
        args += ['--header','Content-Type: application/json','--data-binary','@-'];text=json.dumps(payload)
    p=subprocess.run(args,input=text,text=True,capture_output=True,check=True)
    body,_,status=p.stdout.rpartition('\n')
    if not status.startswith('2'):raise RuntimeError('Livy '+method+' '+path+' returned HTTP '+status)
    return json.loads(body) if body.strip() else {}


def identity_hash(value):
    return hashlib.sha256(str(value).lower().encode()).hexdigest() if value else None


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    record={'timeUTC':datetime.now(timezone.utc).isoformat(),'authentication':'Existing Windows SSPI Negotiate',
            'realRdtReadOrWritten':False,'sessionCreatedByThisTest':None}
    session=None
    try:
        existing=api('GET','/sessions')
        if existing.get('sessions'):raise RuntimeError('Remote sessions are active; defer bounded acceptance to avoid interference')
        created=api('POST','/sessions',{'kind':'pyspark','name':'dsh-boundary-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'),
          'driverMemory':'2g','executorMemory':'2g','driverCores':1,'executorCores':1,'numExecutors':1,
          'conf':{'spark.dynamicAllocation.enabled':'false','spark.executor.instances':'1',
                  'spark.yarn.stagingDir':'/tmp/dsh-boundary-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}})
        session=created['id'];record['sessionCreatedByThisTest']=session
        print(json.dumps({'createdSyntheticSession':session}),flush=True)
        deadline=time.monotonic()+240
        while True:
            state=api('GET',f'/sessions/{session}')
            if state['state']=='idle':break
            if state['state'] in ['dead','error','killed','shutting_down'] or time.monotonic()>deadline:
                record['sessionState']=state['state'];raise RuntimeError('Synthetic Spark session did not become idle')
            time.sleep(5)
        owner=state.get('owner');record['sessionOwnerHash']=identity_hash(owner)
        code=r'''import json,socket
def dsh_boundary_probe(_):
 import socket
 result=[]
 for host,port in [('1.1.1.1',443),('8.8.8.8',53),('github.com',443)]:
  try:
   with socket.create_connection((host,port),timeout=3):pass
   result.append({'target':host,'port':port,'blocked':False})
  except OSError:
   result.append({'target':host,'port':port,'blocked':True})
 return result
driver=dsh_boundary_probe(0)
executor=sc.parallelize([0],1).map(dsh_boundary_probe).collect()[0]
print('DSH_BOUNDARY_JSON='+json.dumps({'driver':driver,'executor':executor,'sparkUser':sc.sparkUser()}))
'''
        submitted=api('POST',f'/sessions/{session}/statements',{'code':code})
        statement=submitted['id'];deadline=time.monotonic()+90
        while True:
            response=api('GET',f'/sessions/{session}/statements/{statement}')
            if response['state']=='available':break
            if time.monotonic()>deadline:raise RuntimeError('Synthetic statement timeout')
            time.sleep(3)
        output=response.get('output',{})
        if output.get('status')!='ok':raise RuntimeError('Synthetic boundary statement failed; no RDT query was submitted')
        text=output.get('data',{}).get('text/plain','')
        line=next(line for line in text.splitlines() if line.startswith('DSH_BOUNDARY_JSON='))
        result=json.loads(line.split('=',1)[1]);spark_user=result.pop('sparkUser',None)
        record['sparkUserHash']=identity_hash(spark_user)
        record['ownerMatchesSparkUser']=bool(owner and spark_user and owner.lower()==spark_user.lower())
        record['network']=result
        record['allRepresentativeExternalConnectionsBlocked']=all(v['blocked'] for rows in result.values() for v in rows)
        record['status']='passed' if record['allRepresentativeExternalConnectionsBlocked'] else 'failed-egress-boundary'
    except Exception as e:
        record['status']='not-established';record['error']=str(e)
        if session is not None:
            try:
                logs=api('GET',f'/sessions/{session}/log?from=0&size=200').get('log',[])
                record['sanitizedFailureLines']=[line[:400] for line in logs
                    if any(x in line.lower() for x in ['error','exception','caused by','permission denied'])
                    and not any(x in line.lower() for x in ['password','token','keytab','credential','secret'])][-12:]
            except Exception:pass
    finally:
        if session is not None:
            try:
                api('DELETE',f'/sessions/{session}');record['ownSessionStopRequested']=True
                after=api('GET','/sessions');record['ownSessionAbsentFromActiveList']=all(s['id']!=session for s in after.get('sessions',[]))
            except Exception as e:record['cleanupError']=str(e)
        (args.output/'remote-spark-boundary.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__':main()
