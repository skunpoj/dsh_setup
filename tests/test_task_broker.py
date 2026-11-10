import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
from unittest import mock
import unittest
from urllib import request, error


class BrokerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); root=Path(cls.temp.name)
        cls.workspace=root/'workspace'; cls.workspace.mkdir(); (cls.workspace/'project').mkdir()
        cls.token=root/'token'; cls.token.write_text('x'*32)
        os.environ.update(DSH_TASK_STATE_ROOT=str(root/'state'),DSH_TASK_WORKSPACE_ROOT=str(cls.workspace),DSH_TASK_TOKEN_FILE=str(cls.token))
        source=Path(__file__).parents[1]/'container'/'dsh-task-broker.py'
        spec=importlib.util.spec_from_file_location('task_broker',source); cls.module=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.module)
        # These tests cover the broker WITHOUT the workspace-local SDK flag; pin it off so the in-image run (where the flag is baked) is deterministic.
        if hasattr(cls.module,'LOCAL_SDK_FLAG'): cls.module.LOCAL_SDK_FLAG=root/'no-local-sdk-flag.json'
        cls.server=cls.module.ThreadingHTTPServer(('127.0.0.1',0),cls.module.Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start(); cls.url='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.server.server_close(); cls.temp.cleanup()
    def call(self,path,method='GET',body=None,authorized=True,subject=None):
        headers={'Authorization':'Bearer '+'x'*32} if authorized else {}
        if subject is not None:headers['X-DSH-Subject']=subject
        data=None if body is None else json.dumps(body).encode()
        if data: headers['Content-Type']='application/json'
        try:
            with request.urlopen(request.Request(self.url+path,method=method,data=data,headers=headers),timeout=3) as r:return r.status,json.load(r)
        except error.HTTPError as e:return e.code,json.load(e)
    def test_a2a_reservation_is_durable_and_recovery_never_replays_it(self):
        task=self.module.Task('7'*32,dict(runtime='sdk',project='project',writes=False))
        task.reserve_a2a_stage('sdk','8'*32,'9'*32)
        saved=json.loads((task.directory/'task.json').read_text())
        self.assertEqual(saved['a2aStages'][0]['status'],'reserved')
        with mock.patch('subprocess.Popen') as process:
            restored=self.module.Task.recover(saved,task.directory)
            self.assertEqual(restored.state,'interrupted')
            self.assertEqual(restored.a2a_stages[0]['status'],'fenced')
            with self.assertRaisesRegex(ValueError,'TASK_FENCED'):
                restored.reserve_a2a_stage('claude','a'*32,'b'*32)
            process.assert_not_called()
        self.assertEqual(json.loads((task.directory/'task.json').read_text())['state'],'interrupted')

    def test_factory_allowance_survives_actual_task_journal_and_restart_fence(self):
        import hashlib
        from types import SimpleNamespace
        from scripts.a2a_factory_budget import reserve_launch
        with tempfile.TemporaryDirectory() as directory,mock.patch.object(self.module,'ROOT',Path(directory)):
            task=self.module.Task('fab1'*8,dict(runtime='claude',project='project',writes=False,prompt='synthetic budget'),
                                  authenticated_subject='owner')
            task.state='running';task.save()
            registry=SimpleNamespace(tasks={task.id:task},lock=threading.RLock())
            binding=dict(subject='owner',generation='g1',taskId=task.id,correlationId=task.correlation_id,
                runtime='claude',project='project',writes=False,
                promptSha256=hashlib.sha256(task.request['prompt'].encode()).hexdigest())
            record=reserve_launch(task,registry=registry,admission={'modelStartsAllowed':1,'subject':'owner','generation':'g1'},binding=binding)
            saved=json.loads((task.directory/'task.json').read_text())
            self.assertEqual(saved['a2aFactoryAllowance'],record)
            with mock.patch('subprocess.Popen') as process:
                restored=self.module.Task.recover(saved,task.directory)
                self.assertEqual(restored.state,'interrupted')
                self.assertEqual(restored.a2a_factory_allowance,record)
                self.assertNotIn('prompt',restored.request)
                process.assert_not_called()
            self.assertEqual(json.loads((task.directory/'task.json').read_text())['state'],'interrupted')

    def test_factory_write_ahead_fences_grant_after_real_disk_save_failures(self):
        import hashlib
        from types import SimpleNamespace
        from scripts.a2a_factory_budget import reserve_launch,WAL_NAME
        for owner in ('task','parent'):
            for boundary in ('before-temp-write','before-replace','after-replace-before-directory-fsync'):
                with self.subTest(owner=owner,boundary=boundary),tempfile.TemporaryDirectory() as directory:
                    with mock.patch.object(self.module,'ROOT',Path(directory)):
                        task=self.module.Task('da7a'*8,dict(runtime='claude',project='project',writes=False,prompt='synthetic crash'),
                                              authenticated_subject='owner')
                        task.state='running';task.save()
                        parent=None
                        if owner=='parent':
                            parent=self.module.Task('da7b'*8,dict(runtime='claude',project='project',writes=False),authenticated_subject='owner')
                            parent.reserve_a2a_stage('claude',task.id,task.correlation_id)
                            parent.active_a2a_child=task
                        roots={parent.id:parent} if parent else {task.id:task}
                        registry=SimpleNamespace(tasks=roots,lock=threading.RLock())
                        binding=dict(subject='owner',generation='g1',taskId=task.id,correlationId=task.correlation_id,
                            runtime='claude',project='project',writes=False,
                            promptSha256=hashlib.sha256(task.request['prompt'].encode()).hexdigest())
                        admission=dict(modelStartsAllowed=3,subject='owner',generation='g1')
                        target=(parent or task).directory/'task.json'
                        original_json=self.module.atomic_json;original_replace=self.module.replace_task_journal
                        def replace(temp,path):
                            if path==target:
                                if boundary.startswith('after-replace'):original_replace(temp,path)
                                raise OSError('synthetic exact replacement boundary failure')
                            return original_replace(temp,path)
                        def atomic(path,value):
                            if path==target and boundary=='before-temp-write':
                                raise OSError('synthetic failure before temp write')
                            return original_json(path,value)
                        with mock.patch.object(self.module,'replace_task_journal',side_effect=replace),mock.patch.object(self.module,'atomic_json',side_effect=atomic):
                            with self.assertRaises(OSError):
                                reserve_launch(task,registry=registry,admission=admission,binding=binding)
                        self.assertTrue((task.directory/WAL_NAME).is_file())
                        # Reconstruct only from persisted files, not the failed
                        # operation's mutated in-memory Task/Registry objects.
                        restarted=self.module.Registry()
                        self.assertTrue(restarted.factory_budget_faults)
                        restored=restarted.get(task.id)
                        self.assertIsNotNone(restored)
                        self.assertTrue(restored.factory_budget_fault)
                        self.assertEqual(restored.state,'interrupted')
                        other=self.module.Task('da7c'*8,dict(runtime='claude',project='project',writes=False,prompt='synthetic crash'),
                                               authenticated_subject='owner')
                        other.state='running';other.save();restarted.tasks[other.id]=other
                        new_binding={**binding,'taskId':other.id,'correlationId':other.correlation_id}
                        with self.assertRaisesRegex(ValueError,'GRANT_DURABILITY_UNRESOLVED'):
                            reserve_launch(other,registry=restarted,admission=admission,binding=new_binding)

    def test_missing_or_malformed_factory_write_ahead_is_not_silently_skipped(self):
        import hashlib
        from types import SimpleNamespace
        from scripts.a2a_factory_budget import reserve_launch,WAL_NAME
        for corruption in ('missing','empty','truncated','missing-task-json'):
            with self.subTest(corruption=corruption),tempfile.TemporaryDirectory() as directory:
                with mock.patch.object(self.module,'ROOT',Path(directory)):
                    task=self.module.Task('fabc'*8,dict(runtime='claude',project='project',writes=False,prompt='synthetic corrupt'),authenticated_subject='owner')
                    task.state='running';task.save()
                    registry=SimpleNamespace(tasks={task.id:task},lock=threading.RLock())
                    binding=dict(subject='owner',generation='g1',taskId=task.id,correlationId=task.correlation_id,
                        runtime='claude',project='project',writes=False,promptSha256=hashlib.sha256(task.request['prompt'].encode()).hexdigest())
                    reserve_launch(task,registry=registry,admission=dict(modelStartsAllowed=3,subject='owner',generation='g1'),binding=binding)
                    marker=task.directory/WAL_NAME
                    if corruption=='missing':marker.unlink()
                    elif corruption=='missing-task-json':(task.directory/'task.json').unlink()
                    else:marker.write_bytes(b'' if corruption=='empty' else b'{')
                    restarted=self.module.Registry()
                    self.assertTrue(restarted.factory_budget_faults)
                    with mock.patch('subprocess.Popen') as process:
                        with self.assertRaises(RuntimeError):
                            restarted.create(dict(runtime='claude',project='project',writes=False),authenticated_subject='owner')
                        process.assert_not_called()

    def test_provider_capture_recovers_saved_bytes_after_task_commit_failure_without_requery(self):
        import copy
        import shutil
        from test_a2a_provider_capture import ProviderCaptureTests
        from scripts.a2a_provider_capture import NAME
        fixture=ProviderCaptureTests();fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.guard()
        with tempfile.TemporaryDirectory() as directory,mock.patch.object(self.module,'ROOT',Path(directory)):
            original=fixture.task
            task=self.module.Task(original.id,copy.deepcopy(original.request),authenticated_subject='owner')
            task.correlation_id=original.correlation_id
            task.a2a_cli_context=copy.deepcopy(original.a2a_cli_context)
            task.a2a_cli_worker=copy.deepcopy(original.a2a_cli_worker)
            for name in ('a2a-worker-terminal.json','a2a-guard-ledger.jsonl'):
                shutil.copyfile(original.directory/name,task.directory/name)
            task.state='running';task.save()
            atomic=self.module.atomic_json
            def fail_final_capture_commit(path,value):
                worker=value.get('a2aCliWorker') or {}
                if path==task.directory/'task.json' and worker.get('providerCaptureStatus') in {'retained','uncertain'}:
                    raise OSError('synthetic failure before retained Task metadata write')
                return atomic(path,value)
            with mock.patch.object(self.module,'atomic_json',side_effect=fail_final_capture_commit):
                with self.assertRaises(OSError):fixture.capture(task,fixture.binding)
            self.assertTrue((task.directory/NAME).is_file())
            saved=json.loads((task.directory/'task.json').read_text())
            self.assertIsNotNone(saved['a2aCliWorker']['providerCaptureOperationId'])
            self.assertNotIn('providerCaptureSha256',saved['a2aCliWorker'])
            restarted=self.module.Registry();restored=restarted.get(task.id)
            self.assertIsNot(restored,task);self.assertNotIn('prompt',restored.request)
            result=fixture.capture.recover(restored,fixture.binding)
            self.assertFalse(result['providerExecutionStoppedVerified'])
            self.assertFalse(result['workerRetired'])
            self.assertEqual(fixture.query.call_count,1)
            self.assertEqual(json.loads((restored.directory/'task.json').read_text())['a2aCliWorker']['providerCaptureSha256'],result['captureSha256'])

    def test_exporter_consumption_survives_restart_with_task_still_eligible(self):
        import copy
        import hashlib
        import shutil
        from test_a2a_provider_exporter import ProviderExporterTests
        from scripts.a2a_provider_exporter import ProviderMetadataExporter,RegistryQueryAuthorizer
        from scripts.a2a_provider_query_journal import TaskControllerQueryConsumer,NAME
        from scripts.a2a_factory_budget import reserve_launch
        class Crash(BaseException):pass
        stages=('before-durable-reservation','after-reservation-before-query',
                'after-query-before-capture','after-capture-before-response')
        for stage in stages:
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                fixture=ProviderExporterTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
                with mock.patch.object(self.module,'ROOT',Path(directory)):
                    registry=self.module.Registry();original=fixture.task
                    task=self.module.Task(original.id,copy.deepcopy(original.request),authenticated_subject='owner')
                    task.correlation_id=original.correlation_id;task.state='running'
                    task.a2a_cli_context=copy.deepcopy(original.a2a_cli_context)
                    task.a2a_cli_worker=copy.deepcopy(original.a2a_cli_worker)
                    for name in ('a2a-worker-terminal.json','a2a-guard-ledger.jsonl'):
                        shutil.copyfile(original.directory/name,task.directory/name)
                    task.save();registry.tasks[task.id]=task
                    binding=dict(subject='owner',generation='g1',taskId=task.id,correlationId=task.correlation_id,
                        runtime='claude',project='project',writes=False,
                        promptSha256=hashlib.sha256(task.request['prompt'].encode()).hexdigest())
                    reserve_launch(task,registry=registry,admission=dict(modelStartsAllowed=3,subject='owner',generation='g1'),binding=binding)
                    fixture.task=task
                    def build(current_registry):
                        authorizer=RegistryQueryAuthorizer(task_lookup=current_registry.get,generation='g1')
                        consumer=TaskControllerQueryConsumer(registry=current_registry,task_lookup=current_registry.get,authorizer=authorizer)
                        exporter=ProviderMetadataExporter(admission_reader=lambda:copy.deepcopy(fixture.lease),
                            authorize_query=authorizer,consume_query=consumer,metadata_store=fixture.store,
                            source_observer=lambda:copy.deepcopy(fixture.fixture.source),source_binding=fixture.fixture.source,clock=lambda:100)
                        return exporter,authorizer
                    fixture.exporter,_=build(registry)
                    if stage=='after-capture-before-response':
                        fixture.fixture.capture.query=fixture.client
                        with self.assertRaises(Crash):
                            fixture.fixture.capture(task,fixture.fixture.binding)
                            raise Crash('after durable capture before caller response')
                        query=json.loads((task.directory/'a2a-provider-capture.json').read_bytes())['query']
                    else:
                        query=fixture.query();task.save()
                        if stage=='before-durable-reservation':
                            with mock.patch('scripts.a2a_provider_query_journal.sync_directory',side_effect=OSError('before durable directory sync')):
                                with self.assertRaises(OSError):fixture.exporter.export(query,peer_certificate_der=fixture.cert)
                        elif stage=='after-reservation-before-query':
                            atomic=self.module.atomic_json
                            def fail_consumption_commit(path,value):
                                if (value.get('a2aCliWorker') or {}).get('providerExportQueryStatus')=='consumed':
                                    raise OSError('after durable intent before Task commit/query')
                                return atomic(path,value)
                            with mock.patch.object(self.module,'atomic_json',side_effect=fail_consumption_commit):
                                with self.assertRaises(OSError):fixture.exporter.export(query,peer_certificate_der=fixture.cert)
                        else:
                            select=fixture.store.select_task_metadata
                            def crash_after_select(**kwargs):
                                select(**kwargs)
                                raise Crash('after DB result before response/capture')
                            with mock.patch.object(fixture.store,'select_task_metadata',side_effect=crash_after_select):
                                with self.assertRaises(Crash):fixture.exporter.export(query,peer_certificate_der=fixture.cert)
                    expected=1 if stage.startswith('after-query') or stage=='after-capture-before-response' else 0
                    self.assertEqual(fixture.db.call_count,expected)
                    self.assertTrue((task.directory/NAME).is_file())
                    # Drop the failed operation's objects and rebuild from disk.
                    restarted=self.module.Registry();restored=restarted.get(task.id)
                    self.assertIsNot(restored,task)
                    # Negative control: do not rely on Registry's incidental
                    # interrupted fence or captured-status rejection to pass.
                    restored.state='running';restored.a2a_cli_worker['providerCaptureStatus']='reserved'
                    fresh,authorizer=build(restarted)
                    authorizer(query,generation='g1')  # Otherwise fully eligible.
                    with self.assertRaisesRegex(ValueError,'CONSUMED_OR_UNCERTAIN_NO_REQUERY'):
                        fresh.export(query,peer_certificate_der=fixture.cert)
                    self.assertEqual(fixture.db.call_count,expected)

    def test_a2a_native_child_completion_binds_project_and_verified_exit(self):
        parent=self.module.Task('3'*32,dict(runtime='claude',project='project',writes=False))
        child=self.module.Task('4'*32,dict(runtime='sdk',project='project',writes=False))
        parent.reserve_a2a_stage('sdk',child.id,child.correlation_id)
        with self.assertRaisesRegex(ValueError,'NOT_RETIRED'):
            parent.complete_native_a2a_stage(child,'checked')
        context=dict(taskId=child.id,sessionId=child.id,subject='owner',generation='g1',operationId='5'*32)
        child.native_sdk=dict(phase='stopped',taskId=child.id,project='project',
            correlationId=child.correlation_id,sessionId=child.id,subject='owner',generation='g1',
            stopOperationId='5'*32,stopReceipt=dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True))
        child.state='completed';child.finished.set()
        parent.complete_native_a2a_stage(child,'checked')
        saved=json.loads((parent.directory/'task.json').read_text())
        self.assertEqual(saved['a2aStages'][0]['status'],'completed')
        self.assertNotIn('checked',json.dumps(saved))
        with self.assertRaisesRegex(ValueError,'STALE_OR_FENCED'):
            parent.complete_native_a2a_stage(child,'duplicate')

    def test_a2a_cancel_targets_exact_child_but_refuses_unverified_stop(self):
        parent=self.module.Task('2'*32,dict(runtime='claude',project='project',writes=False))
        child=self.module.Task('1'*32,dict(runtime='sdk',project='project',writes=False))
        parent.reserve_a2a_stage('sdk',child.id,child.correlation_id)
        parent.attach_a2a_child(child)
        with mock.patch.object(child,'cancel',return_value=True) as cancel:
            self.assertFalse(parent.cancel())
        cancel.assert_called_once_with()
        self.assertEqual(parent.state,'interrupted')
        self.assertEqual(parent.a2a_stages[-1]['status'],'fenced')

    def test_a2a_approval_delegates_only_to_bound_current_native_stage(self):
        parent=self.module.Task('c1'*16,dict(runtime='claude',project='project',writes=False))
        child=self.module.Task('d1'*16,dict(runtime='sdk',project='project',writes=False))
        parent.reserve_a2a_stage('sdk',child.id,child.correlation_id)
        parent.attach_a2a_child(child)
        child.official_sdk_bridge=mock.Mock()
        decision=dict(subject='owner',generation='g1',approval_id='ticket',outcome='allow')
        parent.decide_a2a(**decision)
        child.official_sdk_bridge.decide.assert_called_once_with(**decision)
        parent.state='cancelled'
        with self.assertRaisesRegex(ValueError,'STAGE_UNAVAILABLE'):
            parent.decide_a2a(**decision)
        self.assertEqual(child.official_sdk_bridge.decide.call_count,1)

    def test_a2a_parent_events_return_only_current_owner_ticket(self):
        parent=self.module.Task('e1'*16,dict(runtime='claude',project='project',writes=False))
        child=self.module.Task('f1'*16,dict(runtime='sdk',project='project',writes=False))
        parent.reserve_a2a_stage('sdk',child.id,child.correlation_id)
        parent.attach_a2a_child(child)
        child.state='awaiting_approval'
        child.native_sdk=dict(subject='owner',phase='awaiting-approval',generation='g2',
            pending=dict(approvalId='ticket2',toolName='read',callId='call2'))
        self.module.REGISTRY.tasks[parent.id]=parent
        try:
            path='/v1/tasks/'+parent.id+'/events'
            self.assertEqual(self.call(path,subject='foreign')[0],403)
            status,response=self.call(path,subject='owner')
            self.assertEqual(status,200)
            self.assertEqual(response['nativeApproval']['stageId'],child.id)
            self.assertEqual(response['nativeApproval']['generation'],'g2')
            self.assertEqual(response['state'],'awaiting_approval')
            parent.state='cancelled'
            self.assertIsNone(self.call(path,subject='owner')[1]['nativeApproval'])
        finally:
            self.module.REGISTRY.tasks.pop(parent.id,None)

    def test_a2a_orchestrator_dispatches_two_retired_stages_once(self):
        parent=self.module.Task('a2'*16,dict(runtime='deepagents',handoffRuntime='claude',
            project='project',writes=False,prompt='synthetic draft'),authenticated_subject='owner')
        children=[]
        def execute(child):
            children.append(child)
            self.assertEqual(child.authenticated_subject,'owner')
            self.assertEqual(json.loads((child.directory/'task.json').read_text())['authenticatedSubject'],'owner')
            if len(children)==2:
                self.assertIn('verified draft',child.request['prompt'])
            child.state='completed';child.finished.set()
            child.a2a_terminal_receipt=dict(stageId=child.id,correlationId=child.correlation_id,scopeUid="synthetic-owned-worker",
                stopped=True,processExitVerified=True,descendantAbsenceVerified=True)
            return 'verified draft' if len(children)==1 else 'verified final'
        parent.run_a2a_chain(execute)
        self.assertEqual(parent.state,'completed')
        self.assertEqual(len(children),2)
        self.assertNotEqual(children[0].correlation_id,children[1].correlation_id)
        with self.assertRaisesRegex(ValueError,'CHAIN_REQUEST_REFUSED'):
            parent.run_a2a_chain(execute)
        self.assertEqual(len(children),2)

    def test_physical_worker_reservation_recovers_fenced_in_same_task_journal(self):
        from scripts import a2a_worker_journal as journal
        task=self.module.Task('c6'*16,dict(runtime='claude',project='project',writes=False,
            prompt='do-not-persist-prompt'),authenticated_subject='owner')
        task.state='running'
        task.a2a_cli_context=dict(subject='owner',stageId=task.id,correlationId=task.correlation_id,
                                 project='project',runtime='claude')
        record=journal.reserve(task,namespace='private-test',
            namespace_uid='11111111-1111-4111-8111-111111111111',template_sha256='a'*64,
            image='invalid.example/runtime@sha256:'+'b'*64)
        journal.bind_created(task,operation_id=record['createOperationId'],
                             pod_uid='22222222-2222-4222-8222-222222222222')
        journal.reserve_dispatch(task,pod_uid='22222222-2222-4222-8222-222222222222')
        saved=json.loads((task.directory/'task.json').read_text())
        self.assertNotIn('do-not-persist-prompt',json.dumps(saved))
        recovered=self.module.Task.recover(saved,task.directory)
        self.assertEqual(recovered.state,'interrupted')
        self.assertEqual(recovered.a2a_cli_worker['phase'],'dispatch-reserved')
        self.assertEqual(recovered.a2a_cli_worker['podUID'],'22222222-2222-4222-8222-222222222222')
        with self.assertRaises(ValueError):
            journal.reserve_dispatch(recovered,pod_uid='22222222-2222-4222-8222-222222222222')
        registry=self.module.Registry()
        with mock.patch.object(self.module.threading,'Thread') as thread:
            with self.assertRaisesRegex(RuntimeError,'TASK_ALREADY_ACTIVE'):
                registry.create(dict(runtime='claude',backend='private',project='project',
                    writes=False,prompt='must-not-start'))
            thread.assert_not_called()

    def test_a2a_orchestrator_missing_stop_proof_never_starts_second(self):
        parent=self.module.Task('b2'*16,dict(runtime='deepagents',handoffRuntime='claude',
            project='project',writes=False,prompt='synthetic draft'))
        calls=[]
        def execute(child):
            calls.append(child.id);child.state='completed';child.finished.set()
            return 'unverified output'
        parent.run_a2a_chain(execute)
        self.assertEqual(parent.state,'interrupted')
        self.assertEqual(len(calls),1)
        self.assertEqual(parent.a2a_stages[0]['status'],'fenced')

    def test_http_native_handoff_requires_configured_executor_and_owner(self):
        class Executor:
            qualified=True;subject='owner'
            def __init__(self):self.calls=[]
            def __call__(self,child):
                self.calls.append(child.request['runtime'])
                child.state='completed';child.finished.set()
                if child.request['runtime']=='sdk':
                    context=dict(taskId=child.id,sessionId=child.id,subject='owner',generation='g1',operationId='5'*32)
                    child.native_sdk=dict(phase='stopped',taskId=child.id,project='project',
                        correlationId=child.correlation_id,sessionId=child.id,subject='owner',generation='g1',
                        stopOperationId='5'*32,stopReceipt=dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True))
                else:
                    child.a2a_terminal_receipt=dict(stageId=child.id,correlationId=child.correlation_id,scopeUid="synthetic-owned-worker",
                        stopped=True,processExitVerified=True,descendantAbsenceVerified=True)
                return 'synthetic checked output'
        executor=Executor()
        body=dict(runtime='claude',handoffRuntime='sdk',backend='private',project='project',
            prompt='synthetic',writes=False,approved=True)
        with mock.patch.object(self.server,'a2a_executor',executor,create=True):
            self.assertEqual(self.call('/v1/tasks','POST',body,subject='foreign')[0],400)
            self.assertEqual(executor.calls,[])
            status,response=self.call('/v1/tasks','POST',body,subject='owner')
            self.assertEqual(status,202)
            task=self.module.REGISTRY.get(response['taskId'])
            self.assertTrue(task.finished.wait(5))
            self.assertEqual(task.state,'completed',task.events.read_text())
            self.assertEqual(executor.calls,['claude','sdk'])

    def test_interrupted_a2a_without_child_exit_blocks_new_task(self):
        parent=self.module.Task('c2'*16,dict(runtime='claude',project='project',writes=False))
        parent.reserve_a2a_stage('sdk','d2'*16,'e2'*16)
        parent.state='interrupted'
        parent.a2a_stages=self.module.a2a_stage_journal.fence(parent.a2a_stages)
        self.module.REGISTRY.tasks[parent.id]=parent
        try:
            with self.assertRaisesRegex(RuntimeError,'TASK_ALREADY_ACTIVE'):
                self.module.REGISTRY.create(dict(runtime='claude',project='project',writes=False,prompt='new'))
        finally:self.module.REGISTRY.tasks.pop(parent.id,None)

    def test_events_are_paged_from_the_cursor_without_losing_any(self):
        task=self.module.Task('e0'*16,dict(runtime='claude',project='project',writes=False),authenticated_subject='owner')
        task.state='completed'
        for number in range(250):task.emit('output',dict(text='line%d\n'%number,runtime='claude'))
        self.module.REGISTRY.tasks[task.id]=task
        try:
            status,first=self.call('/v1/tasks/'+task.id+'/events?after=0',subject='owner')
            self.assertEqual(status,200)
            sequences=[row['sequence'] for row in first['events']]
            self.assertEqual((sequences[0],sequences[-1],len(sequences)),(1,200,200))
            self.assertEqual(first['next'],200)
            status,second=self.call('/v1/tasks/'+task.id+'/events?after='+str(first['next']),subject='owner')
            self.assertEqual([row['sequence'] for row in second['events']],list(range(201,252)))
            self.assertEqual(second['next'],251)
            status,third=self.call('/v1/tasks/'+task.id+'/events?after=251',subject='owner')
            self.assertEqual((third['events'],third['next']),([],251))
        finally:self.module.REGISTRY.tasks.pop(task.id,None)

    def test_recovered_parent_keeps_owner_boundary_without_live_child(self):
        task=self.module.Task('f2'*16,dict(runtime='claude',project='project',writes=False),authenticated_subject='owner')
        task.state='interrupted';task.save()
        restored=self.module.Task.recover(json.loads((task.directory/'task.json').read_text()),task.directory)
        self.module.REGISTRY.tasks[task.id]=restored
        try:
            self.assertIsNone(restored.active_a2a_child)
            self.assertEqual(self.call('/v1/tasks/'+task.id+'/events',subject='foreign')[0],403)
            self.assertEqual(self.call('/v1/tasks/'+task.id+'/events',subject='owner')[0],200)
            self.assertEqual(self.call('/v1/tasks/'+task.id,'DELETE',subject='foreign')[0],403)
            self.assertEqual(self.call('/v1/tasks/'+task.id+'/approve','POST',{'approved':True},subject='foreign')[0],403)
        finally:self.module.REGISTRY.tasks.pop(task.id,None)

    def test_a2a_child_cannot_escalate_writes_or_cross_project(self):
        parent=self.module.Task('a1'*16,dict(runtime='claude',project='project',writes=False))
        child=self.module.Task('b1'*16,dict(runtime='sdk',project='project',writes=True))
        parent.reserve_a2a_stage('sdk',child.id,child.correlation_id)
        with self.assertRaisesRegex(ValueError,'BINDING_REFUSED'):
            parent.attach_a2a_child(child)
        child.request['writes']=False;child.request['project']='foreign'
        with self.assertRaisesRegex(ValueError,'BINDING_REFUSED'):
            parent.attach_a2a_child(child)

    def test_a2a_persistence_failure_fences_dispatch_and_reservation(self):
        task=self.module.Task('6'*32,dict(runtime='sdk',project='project',writes=False))
        with mock.patch.object(task,'save',side_effect=OSError('synthetic journal failure')):
            with self.assertRaises(OSError):
                task.reserve_a2a_stage('sdk','8'*32,'9'*32)
        self.assertEqual(task.state,'interrupted')
        self.assertEqual(task.a2a_stages[0]['status'],'fenced')
        with self.assertRaisesRegex(ValueError,'TASK_FENCED'):
            task.reserve_a2a_stage('sdk','a'*32,'b'*32)

    def test_atomic_json_retries_transient_windows_destination_lock(self):
        path=Path(self.temp.name)/'atomic-retry.json'
        real_replace=os.replace
        attempts=[]
        def transient(source,target):
            attempts.append((source,target))
            if len(attempts)<3:
                failure=PermissionError(5,'synthetic sharing violation',str(target))
                failure.winerror=5
                raise failure
            return real_replace(source,target)
        with mock.patch.object(self.module.sys,'platform','win32'), \
                mock.patch.object(self.module.os,'replace',side_effect=transient), \
                mock.patch.object(self.module.time,'sleep'):
            self.module.atomic_json(path,{'state':'settled'})
        self.assertEqual(len(attempts),3)
        self.assertEqual(json.loads(path.read_text()),{'state':'settled'})
        self.assertEqual(list(path.parent.glob(path.name+'.tmp-*')),[])
    def test_atomic_json_cleans_unpublished_temp_on_permanent_failure(self):
        path=Path(self.temp.name)/'atomic-denied.json'
        with mock.patch.object(self.module.os,'name','posix'), \
                mock.patch.object(self.module.os,'replace',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError): self.module.atomic_json(path,{'state':'private'})
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.glob(path.name+'.tmp-*')),[])
    def test_auth_and_capabilities_fail_closed(self):
        self.assertEqual(self.call('/v1/capabilities',authorized=False)[0],401)
        status,value=self.call('/v1/capabilities');self.assertEqual(status,200)
        self.assertEqual(next(x for x in value['backends'] if x['id']=='openshell')['enabled'],False)
        self.assertEqual(value['runtimes'],['claude','deepagents','kilo','sdk'])
    def test_project_escape_refused(self):
        with self.assertRaises(ValueError): self.module.confined_project('../outside')
    def test_openshell_http_requires_auth_and_admitted_service(self):
        path='/v1/tasks/'+'a'*32+'/openshell/bind'
        self.assertEqual(self.call(path,'POST',{'approved':True},authorized=False)[0],401)
        self.assertEqual(self.call(path,'POST',{'approved':True})[0],503)
    def test_openshell_http_calls_injected_service_with_authenticated_subject_header(self):
        path='/v1/tasks/'+'a'*32+'/openshell/resolve'
        service=mock.Mock();service.operate.return_value={'phase':'bound'}
        self.server.openshell_service=service
        try:
            self.assertEqual(self.call(path,'POST',{'approved':True}), (200,{'phase':'bound'}))
            service.operate.assert_called_once_with('', 'a'*32,'resolve',{'approved':True})
            service.operate.side_effect=TimeoutError
            self.assertEqual(self.call(path,'POST',{'approved':True}), (503,{'error':'OPENSHELL_OPERATION_UNCERTAIN'}))
        finally:del self.server.openshell_service

    @mock.patch('subprocess.Popen')
    def test_openshell_task_runs_only_through_native_service(self,popen):
        from scripts.openshell_task_binding import BrokerOpenShellService
        native=mock.Mock()
        native.allocate.side_effect=lambda c,o,e:{**c,'workerUID':'native1','operationId':o}
        native.dispatch.side_effect=lambda c,o:{**c,'operationId':o,'nativeRequired':True,'unrestrictedFallback':False}
        native.stop_exact.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'stopped':True}
        native.verify_absent.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'absent':True}
        native.events.side_effect=lambda c,o:iter([{'type':'output','text':'native checked result'},
                                                  {'type':'exit','exitCode':0,'workerUID':c['workerUID'],'operationId':o}])
        self.server.openshell_service=BrokerOpenShellService(self.module.REGISTRY,'alice','g1',native,qualified=True)
        try:
            body={'runtime':'deepagents','backend':'openshell','project':'project','prompt':'synthetic','writes':False,'approved':True}
            self.assertEqual(self.call('/v1/tasks','POST',body,subject='bob')[0],400)
            status,value=self.call('/v1/tasks','POST',body,subject='alice');self.assertEqual(status,202)
            task=self.module.REGISTRY.get(value['taskId']);self.assertTrue(task.finished.wait(3))
            self.assertEqual(task.state,'completed');popen.assert_not_called()
            self.assertEqual(native.dispatch.call_count,1)
            self.assertEqual(json.loads((task.directory/'task.json').read_text())['backend'],'openshell')
            self.assertIn('native checked result',task.events.read_text())
        finally:del self.server.openshell_service

    @mock.patch('subprocess.Popen')
    def test_native_transport_failure_cannot_fallback_locally(self,popen):
        from scripts.openshell_task_binding import BrokerOpenShellService
        native=mock.Mock();native.allocate.side_effect=TimeoutError
        self.server.openshell_service=BrokerOpenShellService(self.module.REGISTRY,'alice','g1',native,qualified=True)
        try:
            body={'runtime':'claude','backend':'openshell','project':'project','prompt':'synthetic','writes':False,'approved':True}
            status,value=self.call('/v1/tasks','POST',body,subject='alice');self.assertEqual(status,202)
            task=self.module.REGISTRY.get(value['taskId']);self.assertTrue(task.finished.wait(3))
            self.assertEqual(task.state,'interrupted');popen.assert_not_called();native.dispatch.assert_not_called()
            self.assertEqual(task.openshell['phase'],'allocation-reserved')
            with self.assertRaisesRegex(RuntimeError,'TASK_ALREADY_ACTIVE'):
                self.module.REGISTRY.create({'runtime':'sdk','backend':'private','project':'project','prompt':'x','writes':False})
        finally:
            if 'task' in locals():self.module.REGISTRY.tasks.pop(task.id,None)
            del self.server.openshell_service

    @mock.patch('subprocess.Popen')
    def test_native_handoff_http_persists_both_stages_without_prompt(self,popen):
        from scripts.openshell_task_binding import BrokerOpenShellService
        native=mock.Mock();allocations=[]
        def allocate(c,o,e):
            worker='native-'+str(len(allocations));allocations.append(worker)
            return {**c,'workerUID':worker,'operationId':o}
        native.allocate.side_effect=allocate
        native.dispatch.side_effect=lambda c,o:{**c,'operationId':o,'nativeRequired':True,'unrestrictedFallback':False}
        native.stop_exact.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'stopped':True}
        native.verify_absent.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'absent':True}
        native.events.side_effect=lambda c,o:iter([{'type':'output','text':'stage result'},
            {'type':'exit','exitCode':0,'workerUID':c['workerUID'],'operationId':o}])
        self.server.openshell_service=BrokerOpenShellService(self.module.REGISTRY,'alice','g1',native,qualified=True)
        try:
            body={'runtime':'deepagents','backend':'openshell','project':'project','prompt':'PRIVATE_PROMPT_MARKER',
                  'writes':False,'approved':True,'handoffRuntime':'claude','handoffPrompt':'PRIVATE_HANDOFF_MARKER'}
            status,value=self.call('/v1/tasks','POST',body,subject='alice');self.assertEqual(status,202)
            task=self.module.REGISTRY.get(value['taskId']);self.assertTrue(task.finished.wait(5))
            self.assertEqual(task.state,'completed');popen.assert_not_called()
            raw=(task.directory/'task.json').read_text();saved=json.loads(raw)
            self.assertNotIn('PRIVATE_PROMPT_MARKER',raw);self.assertNotIn('PRIVATE_HANDOFF_MARKER',raw)
            stages=saved['nativeStages'];self.assertEqual(len(stages),2)
            self.assertEqual([s['runtime'] for s in stages],['deepagents','claude'])
            self.assertTrue(all(s['binding']['phase']=='stopped' for s in stages))
            self.assertNotEqual(stages[0]['binding']['workerUID'],stages[1]['binding']['workerUID'])
            self.assertNotEqual(stages[0]['correlationId'],stages[1]['correlationId'])
            restored=self.module.Task.recover(saved,task.directory)
            self.assertEqual(restored.native_stages,stages)
            self.assertEqual(native.dispatch.call_count,2)
        finally:del self.server.openshell_service

    @mock.patch('subprocess.Popen')
    def test_native_exit_without_verified_cleanup_is_not_completed(self,popen):
        from scripts.openshell_task_binding import BrokerOpenShellService
        native=mock.Mock();native.allocate.side_effect=lambda c,o,e:{**c,'workerUID':'native2','operationId':o}
        native.dispatch.side_effect=lambda c,o:{**c,'operationId':o,'nativeRequired':True,'unrestrictedFallback':False}
        native.events.side_effect=lambda c,o:iter([{'type':'exit','exitCode':0,'workerUID':c['workerUID'],'operationId':o}])
        native.stop_exact.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'stopped':True}
        native.verify_absent.return_value={'absent':False}
        task=self.module.Task('2'*32,{'runtime':'sdk','backend':'openshell','project':'project','prompt':'synthetic','writes':False})
        self.module.REGISTRY.tasks[task.id]=task
        try:
            service=BrokerOpenShellService(self.module.REGISTRY,'alice','g1',native,qualified=True)
            service.run_task('alice',task)
            self.assertEqual(task.state,'interrupted');self.assertEqual(task.openshell['phase'],'stop-reserved')
            self.assertNotIn('"state": "completed"',task.events.read_text());popen.assert_not_called()
        finally:self.module.REGISTRY.tasks.pop(task.id)

    @mock.patch('subprocess.Popen')
    def test_native_cancel_during_stream_verifies_absence(self,popen):
        from scripts.openshell_task_binding import BrokerOpenShellService
        entered=threading.Event();released=threading.Event();native=mock.Mock()
        native.allocate.side_effect=lambda c,o,e:{**c,'workerUID':'native3','operationId':o}
        native.dispatch.side_effect=lambda c,o:{**c,'operationId':o,'nativeRequired':True,'unrestrictedFallback':False}
        def stream(c,o):
            entered.set()
            if not released.wait(3):raise TimeoutError()
            yield {'type':'exit','exitCode':0,'workerUID':c['workerUID'],'operationId':o}
        native.events.side_effect=stream
        def stop(c,o):
            released.set();return {'workerUID':c['workerUID'],'operationId':o,'stopped':True}
        native.stop_exact.side_effect=stop
        native.verify_absent.side_effect=lambda c,o:{'workerUID':c['workerUID'],'operationId':o,'absent':True}
        task=self.module.Task('3'*32,{'runtime':'sdk','backend':'openshell','project':'project','prompt':'synthetic','writes':False})
        self.module.REGISTRY.tasks[task.id]=task
        service=BrokerOpenShellService(self.module.REGISTRY,'alice','g1',native,qualified=True);task.execution_service=service
        thread=threading.Thread(target=service.run_task,args=('alice',task))
        try:
            thread.start();self.assertTrue(entered.wait(3));self.assertTrue(task.cancel(),task.events.read_text())
            thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(task.state,'cancelled')
            self.assertEqual(task.openshell['phase'],'stopped');popen.assert_not_called()
        finally:
            released.set();thread.join(3);self.module.REGISTRY.tasks.pop(task.id)
    def test_commands_are_fixed_and_bounded(self):
        project=self.workspace/'project'
        sdk=self.module.command_for('sdk','hello',False,project,'a'*32)
        self.assertEqual(sdk[:4],['/usr/local/bin/dsh-unattended','sdk','--task-id','a'*32])
        self.assertIn('--max-model-starts',sdk);self.assertIn('--cwd',sdk)
        self.assertEqual(sdk[-3:],['--','--prompt','hello'])
        resumed=self.module.command_for('sdk','',False,project,'a'*32,True)
        self.assertIn('--resume',resumed);self.assertEqual(resumed[-2:],['--','--resume'])
        claude=self.module.command_for('claude','hello',True,project,'a'*32)
        self.assertIn('acceptEdits',claude);self.assertIn('--output-format',claude);self.assertIn('--max-model-starts',claude)
        kilo=self.module.command_for('kilo','hello',False,project,'a'*32)
        self.assertEqual(kilo[-3:],['--pure','run','hello']);self.assertIn('--max-model-starts',kilo)
    @mock.patch('subprocess.Popen')
    def test_create_stream_and_recovery_record(self,popen):
        child=popen.return_value;child.stdout=iter(['first\n','second\n']);child.wait.return_value=0
        body={'runtime':'deepagents','backend':'private','project':'project','prompt':'read README','writes':False,'approved':True}
        status,value=self.call('/v1/tasks','POST',body);self.assertEqual(status,202)
        self.assertRegex(value['correlationId'],r'^[a-f0-9]{32}$')
        task=self.module.REGISTRY.get(value['taskId'])
        for _ in range(100):
            if task.state=='completed':break
            threading.Event().wait(.01)
        self.assertEqual(task.state,'completed')
        self.assertTrue(task.finished.wait(3))
        status,events=self.call('/v1/tasks/'+task.id+'/events?after=0');self.assertEqual(status,200)
        self.assertIn('first', ''.join(e['data'].get('text','') for e in events['events']))
        self.assertTrue((task.directory/'task.json').exists())
    def test_invalid_shape_and_openshell_refused(self):
        body={'runtime':'sdk','backend':'openshell','project':'project','prompt':'x','writes':False,'approved':True}
        self.assertEqual(self.call('/v1/tasks','POST',body)[0],400)
    @mock.patch('subprocess.Popen')
    def test_agent_to_agent_handoff_is_broker_owned_and_bounded(self,popen):
        first=mock.Mock();first.stdout=iter(['draft answer\n']);first.wait.return_value=0
        second=mock.Mock();second.stdout=iter(['checked answer\n']);second.wait.return_value=0
        popen.side_effect=[first,second]
        body={'runtime':'deepagents','backend':'private','project':'project','prompt':'draft','writes':False,'approved':True,
              'handoffRuntime':'kilo','handoffPrompt':'Check the draft.'}
        status,value=self.call('/v1/tasks','POST',body);self.assertEqual(status,202)
        task=self.module.REGISTRY.get(value['taskId'])
        for _ in range(100):
            if task.state=='completed':break
            threading.Event().wait(.01)
        self.assertEqual(task.state,'completed');self.assertEqual(popen.call_count,2)
        self.assertTrue(task.finished.wait(3))
        second_command=popen.call_args_list[1].args[0]
        self.assertIn('kilo',second_command);self.assertIn('--max-model-starts',second_command)
        self.assertIn('Previous agent result:',second_command[-1]);self.assertIn('draft answer',second_command[-1])
        saved=json.loads((task.directory/'task.json').read_text())
        self.assertEqual(saved['handoffRuntime'],'kilo');self.assertNotIn('prompt',saved)
        first_env=popen.call_args_list[0].kwargs['env'];second_env=popen.call_args_list[1].kwargs['env']
        self.assertRegex(first_env['DSH_CORRELATION_ID'],r'^[a-f0-9]{32}$')
        self.assertRegex(second_env['DSH_CORRELATION_ID'],r'^[a-f0-9]{32}$')
        self.assertNotEqual(first_env['DSH_CORRELATION_ID'],second_env['DSH_CORRELATION_ID'])
    @mock.patch('subprocess.Popen')
    def test_legacy_sdk_checkpoint_approval_preserved_for_old_records(self,popen):
        first=mock.Mock();first.stdout=iter(['approval required\n']);first.wait.return_value=75
        second=mock.Mock();second.stdout=iter(['resumed\n']);second.wait.return_value=0
        popen.side_effect=[first,second]
        body={'runtime':'sdk','backend':'private','project':'project','prompt':'write file','writes':True,'approved':True}
        task=self.module.Task('9'*32,body)
        self.module.REGISTRY.tasks[task.id]=task
        threading.Thread(target=task.run,daemon=True).start()
        self.assertTrue(task.finished.wait(5),task.events.read_text())
        self.assertEqual(task.state,'awaiting_approval')
        self.assertEqual(self.call('/v1/tasks/'+task.id+'/approve','POST',{'approved':False})[0],400)
        self.assertEqual(self.call('/v1/tasks/'+task.id+'/approve','POST',{'approved':True})[0],202)
        self.assertTrue(task.finished.wait(5),task.events.read_text())
        self.assertEqual(task.state,'completed')
        self.assertIn('--resume',popen.call_args.args[0])

    @mock.patch('subprocess.Popen')
    def test_new_sdk_http_request_cannot_fallback_to_legacy_helper(self,popen):
        body={'runtime':'sdk','backend':'private','project':'project','prompt':'synthetic','writes':False,'approved':True}
        self.assertEqual(self.call('/v1/tasks','POST',body)[0],503)
        popen.assert_not_called()
        status,value=self.call('/v1/capabilities')
        self.assertEqual(status,200)
        self.assertFalse(value['runtimeDetails']['sdk']['enabled'])
        body['backend']='openshell'
        self.assertEqual(self.call('/v1/tasks','POST',body),
                         (400,{'error':'OFFICIAL_SDK_NATIVE_WORKER_NOT_QUALIFIED'}))
        popen.assert_not_called()
    def test_one_active_task_is_enforced(self):
        request_value={'runtime':'sdk','backend':'private','project':'project','prompt':'x','writes':False,'approved':True}
        task=self.module.Task('b'*32,request_value);task.state='running';self.module.REGISTRY.tasks[task.id]=task
        with self.assertRaisesRegex(RuntimeError,'TASK_ALREADY_ACTIVE'): self.module.REGISTRY.create(request_value)
        task.state='completed';self.module.REGISTRY.tasks.pop(task.id,None)
    @mock.patch('subprocess.Popen')
    def test_cancelled_handoff_cannot_report_completion(self,popen):
        req={'runtime':'sdk','project':'project','prompt':'x','writes':False,'handoffRuntime':'kilo'}
        task=self.module.Task('f'*32,req)
        first=mock.Mock();first.stdout=iter(['draft']);first.wait.return_value=0
        second=mock.Mock();second.stdout=iter([])
        def cancelled():
            task.state='cancelled'
            return 0
        second.wait.side_effect=cancelled;popen.side_effect=[first,second]
        task.run();self.assertEqual(task.state,'cancelled')
        self.assertEqual(json.loads((task.directory/'task.json').read_text())['state'],'cancelled')
    @mock.patch('subprocess.Popen')
    def test_sdk_handoff_interrupt_never_resumes_first_agent(self,popen):
        req={'runtime':'claude','project':'project','prompt':'x','writes':False,'handoffRuntime':'sdk'}
        task=self.module.Task('1'*32,req)
        first=mock.Mock();first.stdout=iter(['draft']);first.wait.return_value=0
        second=mock.Mock();second.stdout=iter([]);second.wait.return_value=75
        popen.side_effect=[first,second];task.run()
        self.assertEqual(task.state,'interrupted');self.assertFalse(task.approve())
    def test_cancellation_terminates_exact_process_group(self):
        request_value={'runtime':'sdk','backend':'private','project':'project','prompt':'x','writes':False,'approved':True}
        task=self.module.Task('c'*32,request_value);task.state='running'
        process=mock.Mock(pid=4242);process.poll.return_value=None;process.wait.return_value=0;task.process=process
        with mock.patch.object(self.module.os,'killpg',create=True) as killpg:
            self.assertTrue(task.cancel());killpg.assert_called_once_with(4242,self.module.signal.SIGTERM)
        self.assertEqual(task.state,'cancelled')
    def test_restart_marks_orphaned_task_interrupted_without_prompt_persistence(self):
        directory=self.module.ROOT/('d'*32);directory.mkdir(parents=True,exist_ok=True)
        (directory/'task.json').write_text(json.dumps({'id':'d'*32,'state':'running','runtime':'sdk','project':'project','prompt':'secret'}))
        self.module.Registry()
        value=json.loads((directory/'task.json').read_text());self.assertEqual(value['state'],'interrupted')
        # Newly created task metadata deliberately excludes the prompt.
        task=self.module.Task('e'*32,{'runtime':'sdk','backend':'private','project':'project','prompt':'do not persist','writes':False,'approved':True})
        self.assertNotIn('prompt',json.loads((task.directory/'task.json').read_text()))


if __name__=='__main__': unittest.main()
