"""Inspect only named public-sandbox metadata with existing Windows SSPI.

No password/ticket export, no data query, no source write and no permission
change. Uses one bounded synthetic session only when no other session is active.
An empty catalog result means not visible here, not proof of nonexistence.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from verify_remote_spark_boundary import api, identity_hash

TARGET = 'sandbox_da_agent_public_data'
SYSTEM = 'da-agent-system-user'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    record = {'observedAt':datetime.now(timezone.utc).isoformat(), 'targetSandbox':TARGET,
              'authentication':'Existing Windows SSPI Negotiate', 'sourceDataReadOrWritten':False,
              'permissionsChanged':False, 'metadataOnly':True}
    session = None
    try:
        if api('GET','/sessions').get('sessions'):
            raise RuntimeError('Other Livy sessions are active; metadata test deferred without interference')
        created = api('POST','/sessions', {'kind':'pyspark','name':'dsh-public-sandbox-metadata-'+datetime.now(timezone.utc).strftime('%H%M%S'),
            'driverMemory':'2g','executorMemory':'2g','driverCores':1,'executorCores':1,'numExecutors':1,
            'conf':{'spark.dynamicAllocation.enabled':'false','spark.executor.instances':'1',
                    'spark.yarn.stagingDir':'/tmp/dsh-public-metadata-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}})
        session=created['id'];record['syntheticSession']=session
        print(json.dumps({'syntheticMetadataSession':session}),flush=True)
        deadline=time.monotonic()+240
        while True:
            state=api('GET',f'/sessions/{session}')
            if state['state']=='idle':break
            if state['state'] in {'dead','error','killed','shutting_down'} or time.monotonic()>deadline:
                raise RuntimeError('Metadata session did not become ready: '+state['state'])
            time.sleep(5)
        owner=state.get('owner','')
        record['ownerHash']=identity_hash(owner)
        record['authenticatedAsSystemAccount']=owner.lower().split('@')[0].split('\\')[-1]==SYSTEM
        code=r'''import json
from urllib.parse import urlsplit
target='sandbox_da_agent_public_data'
result={'sparkUser':sc.sparkUser(),'catalogImplementation':spark.conf.get('spark.sql.catalogImplementation')}
matches=[str(row[0]) for row in spark.sql("SHOW DATABASES LIKE 'sandbox_da_agent_public_data'").collect()]
result['targetVisibleInThisCatalog']=target in matches
hconf=sc._jsc.hadoopConfiguration()
result['defaultFileSystem']=str(sc._jvm.org.apache.hadoop.fs.FileSystem.getDefaultUri(hconf))
it=hconf.iterator();rm=[]
while it.hasNext():
 entry=it.next();key=str(entry.getKey())
 if key.startswith('yarn.resourcemanager.webapp.address') or key.startswith('yarn.resourcemanager.webapp.https.address'):
  address=str(entry.getValue())
  if not address.startswith(('0.0.0.0:','localhost:')):rm.append({'setting':key,'address':address})
result['resourceManagerWebAddresses']=rm
if result['targetVisibleInThisCatalog']:
 db=spark.catalog.getDatabase(target)
 result['sandboxLocation']=db.locationUri
 result['tableCount']=len(spark.catalog.listTables(target))
 result['hdfsAccessChecks']={}
 path=sc._jvm.org.apache.hadoop.fs.Path(db.locationUri);fs=path.getFileSystem(hconf)
 for name in ['READ','WRITE']:
  try:
   fs.access(path,getattr(sc._jvm.org.apache.hadoop.fs.permission.FsAction,name))
   result['hdfsAccessChecks'][name]='allowed-by-access-check'
  except Exception as e:result['hdfsAccessChecks'][name]={'result':'not-established','exceptionType':type(e).__name__}
 try:
  grants=spark.sql('SHOW GRANT USER `da-agent-system-user` ON DATABASE `sandbox_da_agent_public_data`').collect()
  result['systemUserGrantMetadata']={'querySucceeded':True,'rowCount':len(grants),'doesNotEstablishExclusiveScope':True}
 except Exception as e:result['systemUserGrantMetadata']={'querySucceeded':False,'exceptionType':type(e).__name__}
print('DSH_SANDBOX_METADATA='+json.dumps(result))
'''
        submitted=api('POST',f'/sessions/{session}/statements',{'code':code})
        statement=submitted['id'];deadline=time.monotonic()+100
        while True:
            response=api('GET',f'/sessions/{session}/statements/{statement}')
            if response['state']=='available':break
            if time.monotonic()>deadline:raise RuntimeError('Metadata statement timed out')
            time.sleep(3)
        output=response.get('output',{})
        if output.get('status')!='ok':
            record['statementExceptionType']=output.get('ename')
            raise RuntimeError('Catalog metadata query did not complete; no dataset query was submitted')
        text=output.get('data',{}).get('text/plain','')
        payload=json.loads(next(line.split('=',1)[1] for line in text.splitlines() if line.startswith('DSH_SANDBOX_METADATA=')))
        spark_user=payload.pop('sparkUser','')
        record['sparkUserHash']=identity_hash(spark_user)
        record['ownerMatchesSparkUser']=bool(owner and spark_user and owner.lower()==spark_user.lower())
        record['metadata']=payload
        record['status']='metadata-checked-not-system-account-acceptance'
    except Exception as e:
        record['status']='not-established';record['error']=str(e)
    finally:
        if session is not None:
            try:
                api('DELETE',f'/sessions/{session}')
                record['ownSessionStoppedAndAbsent']=all(s['id']!=session for s in api('GET','/sessions').get('sessions',[]))
            except Exception as e:record['cleanupError']=str(e)
        (args.output/'public-sandbox-metadata.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps(record),flush=True)


if __name__=='__main__':
    main()
