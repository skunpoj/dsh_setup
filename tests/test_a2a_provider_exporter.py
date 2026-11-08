"""Exporter/store/mTLS-client source tests; synthetic identity and SQL only."""
import copy
import hashlib
from io import BytesIO
import json
import ssl
from threading import RLock
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_provider_exporter import ProviderMetadataExporter,RegistryQueryAuthorizer,TLSProviderMetadataQuery,handler_for,ROUTE
from scripts.a2a_spend_store import LiteLLM193MetadataStore,SCHEMA,SQL,DB_FIELDS
from scripts.a2a_model_reconciliation import FIELDS
from scripts.a2a_provider_query_journal import TaskControllerQueryConsumer


class ProviderExporterTests(TestCase):
    def setUp(self):
        from test_a2a_provider_capture import ProviderCaptureTests
        self.fixture=ProviderCaptureTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.guard();self.task=self.fixture.task
        self.task.a2a_factory_allowance={'generation':'g1'}
        self.cert=b'synthetic-test-certificate-not-a-real-identity'
        self.lease=dict(subject='owner',namespace=self.task.a2a_cli_worker['namespace'],
            namespaceUID=self.task.a2a_cli_worker['namespaceUID'],generation='g1',
            controllerCertificateSha256=hashlib.sha256(self.cert).hexdigest(),expiresAt=200)
        self.identity=dict(kind='DSH_READONLY_SPEND_ROUTE_V1',identity='synthetic-readonly',receiptSha256='d'*64,expiresAt=200)
        self.db=Mock(return_value=[dict(self.fixture.row)])
        self.store=LiteLLM193MetadataStore(select_rows=self.db,schema_observer=lambda:dict(SCHEMA),
            identity_observer=lambda:copy.deepcopy(self.identity),identity_contract=self.identity,clock=lambda:100)
        self.authorizer=RegistryQueryAuthorizer(task_lookup=lambda task_id:self.task if task_id==self.task.id else None,generation='g1')
        self.registry=SimpleNamespace(tasks={self.task.id:self.task},lock=RLock())
        self.consumer=TaskControllerQueryConsumer(registry=self.registry,
            task_lookup=lambda task_id:self.registry.tasks.get(task_id),authorizer=self.authorizer)
        self.exporter=ProviderMetadataExporter(admission_reader=lambda:copy.deepcopy(self.lease),
            authorize_query=self.authorizer,consume_query=self.consumer,metadata_store=self.store,source_observer=lambda:copy.deepcopy(self.fixture.source),
            source_binding=self.fixture.source,clock=lambda:100)
        self.connection=Mock()
        def post(method,path,body,headers):
            self.assertEqual((method,path),('POST',ROUTE))
            response=self.exporter.export(json.loads(body),peer_certificate_der=self.cert)
            self.connection.getresponse.return_value.status=200
            self.connection.getresponse.return_value.getheader.return_value='application/json'
            self.connection.getresponse.return_value.read.return_value=json.dumps(response).encode()
        self.connection.request.side_effect=post
        self.connect=Mock(return_value=self.connection)
        self.tls=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.tls.minimum_version=ssl.TLSVersion.TLSv1_2
        self.client=TLSProviderMetadataQuery(origin='https://dsh-agent-task-controller.dsh-a2a-qual.svc.cluster.local:9443',
            namespace='dsh-a2a-qual',tls_context=self.tls,connection_factory=self.connect)

    def query(self):
        self.task.a2a_cli_worker.update(providerCaptureOperationId='e'*32,providerCaptureStatus='reserved')
        guard=(self.task.directory/'a2a-guard-ledger.jsonl').read_bytes()
        return self.fixture.capture._query_context(self.task,self.task.a2a_cli_worker,guard,'e'*32)

    def test_full_synthetic_capture_preserves_distinct_request_and_metadata_operation_ids(self):
        self.fixture.capture.query=self.client
        result=self.fixture.capture(self.task,self.fixture.binding)
        self.db.assert_called_once_with(SQL,([self.fixture.row['litellm_call_id']],))
        self.assertEqual(result['providerRecordIds'],[self.fixture.row['request_id']])
        self.assertNotEqual(self.fixture.row['request_id'],self.fixture.row['litellm_call_id'])
        self.assertNotIn('providerResponseIds',result)
        self.assertFalse(result['providerExecutionStoppedVerified']);self.assertFalse(result['workerRetired'])
        self.connect.assert_called_once();self.connection.close.assert_called_once()
        self.assertIn('"metadata"::jsonb->>\'litellm_call_id\' AS litellm_call_id',SQL)
        self.assertNotIn('SELECT *',SQL);self.assertNotIn('"api_key"',SQL);self.assertNotIn('"response"',SQL)

    def test_retained_sdk_receipt_shape_joins_metadata_uuid_without_rewriting_request_id(self):
        # Nonsensitive IDs from retained SDK V4 receipt; DB remains a mock.
        operation='3a00882e-1848-b886-1863-f7b7f5a7585a'
        row=dict(request_id='chatcmpl-ed44bcea8388439eb5a79ce820ea0144',litellm_call_id=operation,
            model='custom_openai/deepseek-v4.1-flash',status='success',prompt_tokens=5703,completion_tokens=13)
        self.db.return_value=[row]
        result=self.store.select_task_metadata(columns=tuple(sorted(FIELDS)),task_id=self.task.id,
            task_correlation_id=self.task.correlation_id,operation_ids=(operation,))
        self.assertEqual(result,[row]);self.assertNotEqual(result[0]['request_id'],operation)
        self.db.assert_called_once_with(SQL,([operation],))

    def test_foreign_or_missing_metadata_operation_is_not_replaced_by_request_id(self):
        operation=self.fixture.row['litellm_call_id']
        for changed in ({**self.fixture.row,'litellm_call_id':'11111111-1111-4111-8111-111111111111'},
                        {k:v for k,v in self.fixture.row.items() if k!='litellm_call_id'}):
            self.db.return_value=[changed]
            with self.assertRaisesRegex(ValueError,'FOREIGN_OR_UNFILTERED'):
                self.store.select_task_metadata(columns=tuple(sorted(FIELDS)),task_id=self.task.id,
                    task_correlation_id=self.task.correlation_id,operation_ids=(operation,))

    def test_wrong_peer_empty_selector_foreign_pod_and_stale_generation_never_query_store(self):
        query=self.query()
        with self.assertRaises(ValueError):self.exporter.export(query,peer_certificate_der=b'foreign')
        with self.assertRaises(ValueError):self.exporter.export({**query,'operationIds':[]},peer_certificate_der=self.cert)
        with self.assertRaises(ValueError):self.exporter.export({**query,'podUID':'11111111-1111-4111-8111-111111111111'},peer_certificate_der=self.cert)
        self.lease['generation']='old'
        with self.assertRaises(ValueError):self.exporter.export(query,peer_certificate_der=self.cert)
        self.db.assert_not_called()

    def test_query_replay_and_task_status_change_refuse_without_second_select(self):
        query=self.query();self.exporter.export(query,peer_certificate_der=self.cert)
        with self.assertRaises(ValueError):self.exporter.export(query,peer_certificate_der=self.cert)
        self.db.assert_called_once()
        self.task.a2a_cli_worker['providerCaptureStatus']='uncertain'
        with self.assertRaises(ValueError):self.authorizer(query,generation='g1')

    def test_database_identity_schema_and_sensitive_projection_fail_closed(self):
        query=self.query();self.identity['identity']='changed'
        with self.assertRaises(ValueError):self.exporter.export(query,peer_certificate_der=self.cert)
        self.db.assert_not_called()
        with self.assertRaises(ValueError):
            self.store.select_task_metadata(columns=('api_key',),task_id=query['taskId'],
                task_correlation_id=query['correlationId'],operation_ids=tuple(query['operationIds']))

    def test_changed_schema_and_noncanonical_request_id_never_reach_database(self):
        query=self.query();self.store.schema=lambda:{**SCHEMA,'version':'unreviewed'}
        with self.assertRaises(ValueError):self.exporter.export(query,peer_certificate_der=self.cert)
        self.db.assert_not_called()
        self.store.schema=lambda:dict(SCHEMA)
        with self.assertRaises(ValueError):
            self.store.select_task_metadata(columns=tuple(sorted(FIELDS)),task_id=query['taskId'],
                task_correlation_id=query['correlationId'],operation_ids=("uuid' OR true",))
        self.db.assert_not_called()

    def test_restarted_interrupted_task_cannot_requery_even_with_empty_exporter_cache(self):
        query=self.query();self.task.state='interrupted'
        self.assertFalse(hasattr(self.exporter,'consumed'))
        with self.assertRaisesRegex(ValueError,'STALE_OR_REPLAYED'):
            self.exporter.export(query,peer_certificate_der=self.cert)
        self.db.assert_not_called()

    def test_raw_database_row_with_extra_sensitive_field_is_not_projected(self):
        query=self.query();self.db.return_value[0]['api_key']='synthetic-rejected'
        with self.assertRaisesRegex(ValueError,'UNFILTERED_SPEND_ROW'):
            self.exporter.export(query,peer_certificate_der=self.cert)

    def test_client_never_redirects_or_retries_and_requires_exact_verified_internal_tls_origin(self):
        self.connection.request.side_effect=None
        self.connection.getresponse.return_value.status=302
        self.connection.getresponse.return_value.read.return_value=b'{}'
        self.connection.getresponse.return_value.getheader.return_value='application/json'
        with self.assertRaisesRegex(RuntimeError,'NO_RETRY'):self.client(self.query())
        self.connect.assert_called_once();self.connection.request.assert_called_once();self.connection.close.assert_called_once()
        with self.assertRaises(ValueError):
            TLSProviderMetadataQuery(origin='https://external.invalid',namespace='dsh-a2a-qual',tls_context=self.tls,connection_factory=self.connect)

    def test_http_handler_refuses_plain_or_missing_client_auth_before_export(self):
        handler=handler_for(self.exporter).__new__(handler_for(self.exporter))
        query=self.query();body=json.dumps(query).encode()
        handler.path=ROUTE;handler.headers={'Content-Type':'application/json','Content-Length':str(len(body))}
        handler.rfile=BytesIO(body);handler.reply=Mock()
        handler.connection=Mock(context=SimpleNamespace(verify_mode=ssl.CERT_NONE))
        handler.do_POST();self.assertEqual(handler.reply.call_args.args[0],403);self.db.assert_not_called()
        handler.connection=Mock(context=SimpleNamespace(verify_mode=ssl.CERT_REQUIRED))
        handler.connection.getpeercert.return_value=self.cert;handler.rfile=BytesIO(body)
        handler.do_POST();self.assertEqual(handler.reply.call_args.args[0],200)
        self.db.assert_called_once()

    def test_runtime_assembly_is_inert_installs_once_and_uses_same_registry_capture(self):
        from threading import RLock
        from scripts.a2a_sdk_controller import SDKWorkerController
        from scripts.a2a_factory_contract import ProtectedA2AFactory,PROVIDER,BUDGET,DEPENDENCIES
        from scripts.a2a_provider_runtime import ProviderCaptureRuntime
        cli=self.fixture.f.controller
        sdk=SDKWorkerController(api=cli.api,subject=cli.subject,image=cli.image,source_commit=cli.source_commit,
            node_name=cli.node_name,project_admission=cli.project_admission,execution_admission=cli.execution_admission,
            generation='g1',package_admission_sha256='e'*64,clock=lambda:100)
        self.task.request['backend']='private'
        registry=SimpleNamespace(tasks={self.task.id:self.task},lock=RLock())
        placement=dict(namespace=cli.api.namespace,namespaceUID=cli.api.namespace_uid,
            podUID='22222222-2222-4222-8222-222222222222',workloadUID='33333333-3333-4333-8333-333333333333',
            environment='test',workloadRole='qualification')
        admission=dict(subject='owner',generation='g1',namespace=cli.api.namespace,namespaceUID=cli.api.namespace_uid,
            nodeName=cli.node_name,image=cli.image,sourceCommit=cli.source_commit,packageAdmissionSha256=sdk.package_hash,
            provider=copy.deepcopy(PROVIDER),resourceBudget=copy.deepcopy(BUDGET),expiresAt=200,modelStartsAllowed=0,rollbackOwner='owner')
        deps={name:Mock() for name in DEPENDENCIES}
        deps.update(workspacePolicy=cli.project_admission,executionAdmission=cli.execution_admission)
        factory=ProtectedA2AFactory(registry=registry,sdk_controller=sdk,cli_controller=cli,
            task_lookup=lambda task_id:registry.tasks.get(task_id),placement_observer=lambda:copy.deepcopy(placement),
            placement_binding=placement,admission_reader=lambda:copy.deepcopy(admission),dependencies=deps,clock=lambda:100)
        self.fixture.source['sourceCommit']=cli.source_commit
        runtime=ProviderCaptureRuntime(factory=factory,origin='https://dsh-agent-task-controller.dsh-a2a-qual.svc.cluster.local:9443',
            client_tls=self.tls,exporter_admission=lambda:copy.deepcopy(self.lease),metadata_store=self.store,
            source_observer=lambda:copy.deepcopy(self.fixture.source),source_binding=self.fixture.source,
            connection_factory=self.connect,clock=lambda:100)
        self.connect.assert_not_called();self.db.assert_not_called()
        runtime.install();self.assertIs(runtime.factory.registry,registry)
        with self.assertRaisesRegex(ValueError,'NO_REPLACEMENT'):runtime.install()
        self.exporter=runtime.exporter
        result=factory.bind(self.task)['capture_provider']()
        self.assertTrue(result['providerMetadataIdentityMatched']);self.assertFalse(result['workerRetired'])
        self.assertFalse(hasattr(runtime,'qualified'));self.db.assert_called_once()
        # Rebuilt runtime shares the existing Task directory, not any in-memory
        # response cache. Finalization recovers bytes without another SELECT.
        successor=ProviderCaptureRuntime(factory=factory,origin='https://dsh-agent-task-controller.dsh-a2a-qual.svc.cluster.local:9443',
            client_tls=self.tls,exporter_admission=lambda:copy.deepcopy(self.lease),metadata_store=self.store,
            source_observer=lambda:copy.deepcopy(self.fixture.source),source_binding=self.fixture.source,
            connection_factory=self.connect,clock=lambda:100)
        self.assertEqual(successor.capture(self.task,self.fixture.binding),result)
        self.db.assert_called_once();self.connect.assert_called_once()
        with self.assertRaisesRegex(ValueError,'CANONICAL'):
            successor.install_retirement(admission_reader=Mock())
        with self.assertRaisesRegex(ValueError,'EXPLICIT_PROTECTED'):
            runtime.retire(self.task,self.fixture.binding)
        w=self.task.a2a_cli_worker
        cleanup=dict(scope=dict(binding=copy.deepcopy(self.fixture.binding),namespace=w['namespace'],namespaceUID=w['namespaceUID'],
            podName=w['podName'],podUID=w['podUID'],source=copy.deepcopy(self.fixture.source),captureSha256=w['providerCaptureSha256']),
            expiresAt=200,cleanupOnly=True)
        cleanup_reader=Mock(side_effect=lambda task,binding:copy.deepcopy(cleanup))
        runtime.install_retirement(admission_reader=cleanup_reader)
        self.assertEqual(set(runtime.retirements),{'sdk','claude','deepagents'})
        with self.assertRaisesRegex(ValueError,'NO_REPLACEMENT'):
            runtime.install_retirement(admission_reader=cleanup_reader)
        def retire_worker(**kwargs):
            cli.api.read_pod.return_value=None
            return dict(deleteAccepted=True,podUID=w['podUID'])
        cli.api.delete_pod_once=Mock(side_effect=retire_worker)
        retired=factory.bind(self.task)['retire']()
        self.assertTrue(retired['resourceAbsent']);self.assertFalse(retired['rollbackVerified'])
        self.assertEqual(factory.bind(self.task)['retire'](),retired)
        cli.api.delete_pod_once.assert_called_once();self.db.assert_called_once()
        cli.api.read_pod.return_value=self.fixture.f.pod  # Restore disposable fixture for capture negative control.
        from scripts.a2a_provider_capture import NAME
        (self.task.directory/NAME).unlink()  # Disposable fixture fault only.
        with self.assertRaises(FileNotFoundError):successor.capture(self.task,self.fixture.binding)
        self.db.assert_called_once();self.connect.assert_called_once()
