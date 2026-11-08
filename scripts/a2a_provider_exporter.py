"""Protected metadata-only exporter route; explicit mTLS and read-only store.

No default database, secret retrieval, unfiltered-log reader or Task writer.
The deployed store/schema/identity and real TLS path still need qualification.
"""
import copy
import hashlib
import http.client
import json
import re
import ssl
import time
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit
from scripts.a2a_model_reconciliation import FIELDS,MODELS
from scripts.official_sdk_package_admission import unique_json
from scripts.a2a_provider_query_journal import consumption_record,canonical

ROUTE='/internal/dsh/task-provider-metadata/v1'
QUERY_FIELDS={'kind','subject','taskId','correlationId','namespace','namespaceUID','podUID',
              'captureOperationId','guardSha256','operationIds'}


class RegistryQueryAuthorizer:
    def __init__(self,*,task_lookup,generation):
        if not callable(task_lookup) or not isinstance(generation,str) or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',generation):
            raise ValueError('PROTECTED_TASK_LOOKUP_AND_GENERATION_REQUIRED')
        self.lookup,self.generation=task_lookup,generation

    def __call__(self,query,*,generation):
        task=self.lookup(query['taskId'])
        if task is None:raise ValueError('UNKNOWN_PROVIDER_QUERY_TASK')
        self.validate_task(task,query,generation=generation)

    def validate_task(self,task,query,*,generation):
        from scripts import a2a_worker_journal as journal
        if generation!=self.generation:raise ValueError('STALE_PROVIDER_QUERY_GENERATION')
        with task.persistence_lock:
            worker=getattr(task,'a2a_cli_worker',None);allocation=getattr(task,'a2a_factory_allowance',None)
            if (task.id!=query['taskId'] or task.authenticated_subject!=query['subject'] or task.correlation_id!=query['correlationId']
                    or task.state not in {'running','finalizing','cancelling','awaiting_approval'}
                    or not isinstance(worker,dict) or not isinstance(allocation,dict)
                    or allocation.get('generation')!=self.generation
                    or worker.get('providerCaptureOperationId')!=query['captureOperationId']
                    or worker.get('providerCaptureStatus')!='reserved'
                    or any(worker.get(k)!=query[v] for k,v in
                        [('namespace','namespace'),('namespaceUID','namespaceUID'),('podUID','podUID'),('guardLedgerSha256','guardSha256')])):
                raise ValueError('FOREIGN_STALE_OR_REPLAYED_PROVIDER_QUERY')
            rows=journal.read_guard_ledger(task)
            operations=[str(uuid.UUID(row['operation_correlation_id'])) for row in rows if row['event']=='upstream-start-reserved']
            if operations!=query['operationIds']:raise ValueError('FOREIGN_PROVIDER_QUERY_OPERATIONS')
        # Deliberately read-only: only the Task controller writes the journal.


class ProviderMetadataExporter:
    def __init__(self,*,admission_reader,authorize_query,consume_query,metadata_store,source_observer,source_binding,clock=time.time):
        if (not callable(admission_reader) or not callable(authorize_query)
                or not callable(consume_query)
                or not callable(getattr(metadata_store,'select_task_metadata',None)) or not callable(source_observer)
                or not isinstance(source_binding,dict) or set(source_binding)!={'sourceCommit','imageDigest','exporterSha256'}
                or not re.fullmatch(r'[a-f0-9]{40}',str(source_binding.get('sourceCommit')))
                or not re.fullmatch(r'sha256:[a-f0-9]{64}',str(source_binding.get('imageDigest')))
                or not re.fullmatch(r'[a-f0-9]{64}',str(source_binding.get('exporterSha256')))):
            raise ValueError('EXPLICIT_PROTECTED_EXPORTER_DEPENDENCIES_REQUIRED')
        self.read,self.authorize,self.store=admission_reader,authorize_query,metadata_store
        self.consume=consume_query
        self.observe,self.source,self.clock=source_observer,copy.deepcopy(source_binding),clock

    def export(self,query,*,peer_certificate_der):
        lease=self.read()
        fields={'subject','namespace','namespaceUID','generation','controllerCertificateSha256','expiresAt'}
        if (not isinstance(lease,dict) or set(lease)!=fields or type(lease['expiresAt']) not in (int,float)
                or not 0<lease['expiresAt']-self.clock()<=300
                or any(not isinstance(lease[k],str) or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',lease[k])
                       for k in ('subject','generation'))
                or not isinstance(peer_certificate_der,bytes) or not 0<len(peer_certificate_der)<=65536
                or hashlib.sha256(peer_certificate_der).hexdigest()!=lease['controllerCertificateSha256']
                or not re.fullmatch(r'[a-f0-9]{64}',str(lease['controllerCertificateSha256']))):
            raise ValueError('FINITE_MTLS_CONTROLLER_ADMISSION_REQUIRED')
        if (not isinstance(query,dict) or set(query)!=QUERY_FIELDS
                or query['kind']!='DSH_TASK_PROVIDER_METADATA_QUERY_V1'
                or any(query[k]!=lease[k] for k in ('subject','namespace','namespaceUID'))
                or not re.fullmatch(r'dsh-a2a-[a-z0-9][a-z0-9-]{0,54}',str(query['namespace']))
                or any(not re.fullmatch(r'[a-f0-9]{32}',str(query[k])) for k in ('taskId','correlationId','captureOperationId'))
                or not re.fullmatch(r'[a-f0-9]{64}',str(query['guardSha256']))
                or not isinstance(query['operationIds'],list) or len(query['operationIds'])!=1):
            raise ValueError('EXACT_NONEMPTY_TASK_PROVIDER_QUERY_REQUIRED')
        for value in (query['namespaceUID'],query['podUID'],*query['operationIds']):
            if not isinstance(value,str) or str(uuid.UUID(value))!=value:
                raise ValueError('EXACT_PROVIDER_QUERY_RESOURCE_AND_OPERATION_UID_REQUIRED')
        if self.observe()!=self.source:raise ValueError('EXPORTER_SOURCE_IDENTITY_CHANGED')
        self.authorize(copy.deepcopy(query),generation=lease['generation'])
        # Only the injected canonical Task writer commits consumption. A fresh
        # exporter process cannot erase this durable pre-SELECT reservation.
        consumed=self.consume(copy.deepcopy(query),generation=lease['generation'],source=copy.deepcopy(self.source))
        digest=hashlib.sha256(canonical(consumption_record(query,generation=lease['generation'],source=self.source))).hexdigest()
        expected=dict(kind='DSH_PROVIDER_EXPORT_CONSUMED_V1',generation=lease['generation'],taskId=query['taskId'],
            captureOperationId=query['captureOperationId'],guardSha256=query['guardSha256'],consumptionSha256=digest)
        if consumed!=expected:raise ValueError('DURABLE_PROVIDER_QUERY_CONSUMPTION_UNVERIFIED')
        if self.read()!=lease or self.observe()!=self.source or not 0<lease['expiresAt']-self.clock()<=300:
            raise ValueError('EXPORTER_ADMISSION_OR_SOURCE_CHANGED')
        self.authorize(copy.deepcopy(query),generation=lease['generation'])
        rows=self.store.select_task_metadata(columns=tuple(sorted(FIELDS)),task_id=query['taskId'],
            task_correlation_id=query['correlationId'],operation_ids=tuple(query['operationIds']))
        # The store MUST apply these selectors in its backend query. Returning
        # raw logs and projecting them here is never an accepted implementation.
        if not isinstance(rows,list) or len(rows)!=1:raise ValueError('EXACT_TASK_PROVIDER_METADATA_REQUIRED')
        row=rows[0]
        if (not isinstance(row,dict) or set(row)!=FIELDS or row['litellm_call_id']!=query['operationIds'][0]
                or not isinstance(row['request_id'],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',row['request_id'])
                or not isinstance(row['model'],str) or row['model'] not in MODELS
                or not isinstance(row['status'],str) or row['status'] not in {'success','failure'}
                or any(type(row[k]) is not int or not 0<=row[k]<=2**31-1 for k in ('prompt_tokens','completion_tokens'))):
            raise ValueError('UNFILTERED_OR_FOREIGN_PROVIDER_METADATA_REFUSED')
        if self.read()!=lease or self.observe()!=self.source or not 0<lease['expiresAt']-self.clock()<=300:
            raise ValueError('EXPORTER_ADMISSION_OR_SOURCE_CHANGED')
        return dict(query=copy.deepcopy(query),source=copy.deepcopy(self.source),rows=copy.deepcopy(rows))


def handler_for(exporter):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def reply(self,status,value):
            raw=json.dumps(value,separators=(',',':')).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            if self.path!=ROUTE:return self.reply(404,{'error':'NOT_FOUND'})
            try:
                if (getattr(getattr(self.connection,'context',None),'verify_mode',None)!=ssl.CERT_REQUIRED
                        or self.headers.get('Transfer-Encoding') is not None
                        or self.headers.get('Content-Encoding') not in (None,'identity')
                        or self.headers.get('Content-Type')!='application/json'):
                    raise ValueError('PROTECTED_MTLS_JSON_ONLY')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384:raise ValueError('BOUNDED_PROVIDER_QUERY_REQUIRED')
                self.connection.settimeout(5)
                raw=self.rfile.read(length)
                if len(raw)!=length:raise ValueError('INCOMPLETE_PROVIDER_QUERY')
                value=unique_json(raw)
                response=exporter.export(value,peer_certificate_der=self.connection.getpeercert(binary_form=True))
                return self.reply(200,response)
            except Exception:return self.reply(403,{'error':'PROVIDER_METADATA_EXPORT_REFUSED'})
        def do_GET(self):return self.reply(405,{'error':'METHOD_NOT_ALLOWED'})
    return Handler


class TLSProviderMetadataQuery:
    """One explicit HTTPS POST to the dedicated protected controller only."""
    def __init__(self,*,origin,namespace,tls_context,connection_factory=http.client.HTTPSConnection):
        if not isinstance(origin,str):raise ValueError('EXPLICIT_PROTECTED_EXPORTER_ORIGIN_REQUIRED')
        parsed=urlsplit(origin)
        if (not re.fullmatch(r'dsh-a2a-[a-z0-9][a-z0-9-]{0,54}',str(namespace))
                or parsed.scheme!='https' or parsed.hostname!='dsh-agent-task-controller.'+namespace+'.svc.cluster.local'
                or parsed.username is not None or parsed.password is not None or parsed.path not in ('','/')
                or parsed.query or parsed.fragment or not isinstance(tls_context,ssl.SSLContext)
                or tls_context.verify_mode!=ssl.CERT_REQUIRED or tls_context.check_hostname is not True
                or tls_context.minimum_version<ssl.TLSVersion.TLSv1_2 or not callable(connection_factory)):
            raise ValueError('EXPLICIT_VERIFIED_PROTECTED_EXPORTER_TLS_ROUTE_REQUIRED')
        self.origin,self.tls,self.connect=parsed,tls_context,connection_factory

    def __call__(self,query):
        connection=None
        try:
            if self.tls.verify_mode!=ssl.CERT_REQUIRED or self.tls.check_hostname is not True:
                raise ValueError('PROTECTED_EXPORTER_TLS_REVOKED')
            if not isinstance(query,dict) or set(query)!=QUERY_FIELDS:
                raise ValueError('EXACT_PROVIDER_QUERY_REQUIRED')
            raw=json.dumps(query,separators=(',',':')).encode()
            if not 0<len(raw)<=16384:raise ValueError('BOUNDED_PROVIDER_QUERY_REQUIRED')
            connection=self.connect(self.origin.hostname,self.origin.port or 443,context=self.tls,timeout=5)
            connection.request('POST',ROUTE,body=raw,headers={'Content-Type':'application/json','Accept':'application/json'})
            response=connection.getresponse();data=response.read(32769)
            if response.status!=200 or len(data)>32768 or response.getheader('Content-Type')!='application/json':
                raise ValueError('PROVIDER_EXPORTER_RESPONSE_REFUSED')
            value=unique_json(data)
            if not isinstance(value,dict) or set(value)!={'query','source','rows'} or value['query']!=query:
                raise ValueError('FOREIGN_PROVIDER_EXPORTER_RESPONSE')
            return value  # TaskProviderCapture independently verifies source/rows and persists.
        except Exception:
            raise RuntimeError('PROTECTED_PROVIDER_QUERY_UNCERTAIN_NO_RETRY') from None
        finally:
            if connection is not None:connection.close()
