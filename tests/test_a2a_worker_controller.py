"""Controller contracts with a synthetic API, never live execution credit."""
import copy
import json
from types import SimpleNamespace
from threading import RLock
from unittest import TestCase
from unittest.mock import Mock
from scripts.a2a_worker_controller import WorkerController
from scripts.agent_runtime_commands import command_for


class WorkerControllerTests(TestCase):
    def setUp(self):
        self.task=SimpleNamespace(id='a'*32,correlation_id='c'*32,state='running',
            authenticated_subject='owner',request=dict(runtime='claude',project='project',writes=False,
            prompt='synthetic-private-prompt'),persistence_lock=RLock(),a2a_cli_worker=None,save=Mock())
        self.task.a2a_cli_context=dict(subject='owner',stageId=self.task.id,correlationId=self.task.correlation_id,
                                      project='project',runtime='claude')
        self.api=SimpleNamespace(namespace='dsh-a2a-qual',namespace_uid='11111111-1111-4111-8111-111111111111',
            read_pod=Mock(return_value=None),create_pod_once=Mock(side_effect=self.create))
        self.image='registry.invalid/runtime@sha256:'+'b'*64
        self.project=dict(claim='private',subpath='owner/project',writes=False,
                          brokerPath='/broker/private/project',credentialSecret='synthetic')
        self.allow_models=0;self.expires=200;self.foreign_admission=False
        self.controller=WorkerController(api=self.api,subject='owner',image=self.image,source_commit='f'*40,
            node_name='fixture-node',project_admission=lambda *_:dict(self.project),
            execution_admission=self.admission,clock=lambda:100)
        self.command=command_for('claude',self.task.request['prompt'],False,self.project['brokerPath'],self.task.id)

    def admission(self,subject,task_id,correlation,project,runtime,writes,prompt_sha):
        return dict(subject=subject,namespace=self.api.namespace,namespaceUID=self.api.namespace_uid,
            image=self.image,sourceCommit='f'*40,nodeName='fixture-node',mode='private-test',
            taskId='d'*32 if self.foreign_admission else task_id,correlationId=correlation,
            project=project,runtime=runtime,writes=writes,
            promptSha256=prompt_sha,
            expiresAt=self.expires,modelStartsAllowed=self.allow_models)

    def create(self,manifest):
        self.assertEqual(self.task.a2a_cli_worker['phase'],'create-reserved')
        self.assertGreaterEqual(self.task.save.call_count,1)
        self.manifest=copy.deepcopy(manifest)
        self.pod=copy.deepcopy(manifest)
        self.pod['metadata'].update(uid='22222222-2222-4222-8222-222222222222',resourceVersion='2')
        self.pod['status']=dict(phase='Running',containerStatuses=[dict(name=name,ready=True,
            restartCount=0,state={'running':{'startedAt':'synthetic'}},imageID=self.image)
            for name in ('worker','model-guard')])
        return self.pod

    def prepare(self):
        return self.controller.prepare_cli(self.task,self.command,self.project['brokerPath'])

    def test_create_is_saved_before_one_api_post_and_never_contains_prompt(self):
        record=self.prepare()
        self.assertEqual(record['phase'],'bound')
        self.assertEqual(record['podUID'],self.pod['metadata']['uid'])
        self.assertNotIn(self.task.request['prompt'],json.dumps(self.manifest))
        self.api.create_pod_once.assert_called_once()
    def test_recovered_prompt_hash_allows_cleanup_admission_but_never_model_dispatch(self):
        import hashlib
        expected=hashlib.sha256(self.task.request['prompt'].encode()).hexdigest()
        self.prepare();self.assertEqual(self.task.a2a_cli_worker['promptSha256'],expected)
        del self.task.request['prompt']
        self.assertEqual(self.controller._execution(self.task)['promptSha256'],expected)
        with self.assertRaisesRegex(ValueError,'RAW_PROMPT_REQUIRED'):
            self.controller._execution(self.task,model=True)
        self.api.create_pod_once.assert_called_once()
    def test_changed_prompt_cannot_rebind_an_existing_worker_lease(self):
        self.prepare();self.task.request['prompt']='different synthetic task input'
        with self.assertRaisesRegex(ValueError,'PROMPT_BINDING_CHANGED'):
            self.controller._execution(self.task)
    def test_prompt_change_after_admission_cannot_reserve_or_create_worker(self):
        original=self.controller.execution_admission
        def change_after_admission(*args):
            value=original(*args)
            if self.api.read_pod.called:self.task.request['prompt']='changed after lease validation'
            return value
        self.controller.execution_admission=change_after_admission
        with self.assertRaisesRegex(ValueError,'EXACT_WORKER_PROMPT_HASH_REQUIRED'):self.prepare()
        self.assertIsNone(self.task.a2a_cli_worker);self.api.create_pod_once.assert_not_called()

    def test_uncertain_create_cannot_be_repeated(self):
        self.api.create_pod_once.side_effect=TimeoutError('synthetic uncertain response')
        with self.assertRaises(TimeoutError):self.prepare()
        self.assertEqual(self.task.a2a_cli_worker['phase'],'create-reserved')
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):self.prepare()
        self.api.create_pod_once.assert_called_once()

    def test_dispatch_requires_task_specific_model_admission_then_rebases_only_private_project(self):
        self.prepare();self.api.read_pod.return_value=self.pod
        with self.assertRaisesRegex(ValueError,'ADMISSION_REQUIRED'):
            self.controller.reserve_cli_dispatch(self.task)
        self.assertEqual(self.task.a2a_cli_worker['phase'],'bound')
        self.allow_models=1
        request=self.controller.reserve_cli_dispatch(self.task)
        self.assertEqual(request['context']['scopeUid'],self.pod['metadata']['uid'])
        self.assertEqual(request['cwd'],'/workspace');self.assertEqual(request['command'][7],'/workspace')
        self.assertEqual(request['command'][8:11],['--external-guard-port','4001','--'])
        self.assertEqual(self.manifest['spec']['containers'][0]['volumeMounts'][0]['subPath'],'owner/project')
        with self.assertRaisesRegex(ValueError,'ALREADY_RESERVED'):
            self.controller.reserve_cli_dispatch(self.task)

    def test_expired_execution_can_only_observe_not_start_or_claim_exit(self):
        self.prepare();self.expires=50;self.api.read_pod.return_value=self.pod
        observed=self.controller.observe(self.task)
        self.assertFalse(observed['processExitVerified'])
        with self.assertRaisesRegex(ValueError,'ADMISSION_REQUIRED'):
            self.controller.reserve_cli_dispatch(self.task)
        self.api.read_pod.return_value=None
        absent=self.controller.observe(self.task)
        self.assertTrue(absent['resourceAbsent']);self.assertFalse(absent['processExitVerified'])

    def test_foreign_admission_or_project_escalation_fails_before_api_create(self):
        self.foreign_admission=True
        with self.assertRaises(ValueError):self.prepare()
        self.api.create_pod_once.assert_not_called()
        self.foreign_admission=False;self.task.request['writes']=True
        with self.assertRaisesRegex(ValueError,'WRITE_ADMISSION'):self.prepare()
        self.api.create_pod_once.assert_not_called()

    def test_changed_api_pod_spec_is_not_bound_as_our_worker(self):
        def changed(manifest):
            pod=self.create(manifest);pod['spec']['hostPID']=True;return pod
        self.api.create_pod_once.side_effect=changed
        with self.assertRaisesRegex(ValueError,'TEMPLATE_CHANGED'):self.prepare()
        self.assertEqual(self.task.a2a_cli_worker['phase'],'create-reserved')
        self.assertIsNone(self.task.a2a_cli_worker['podUID'])

    def test_terminal_recovery_uses_actual_pod_without_reattach_or_inventing_output(self):
        from scripts.a2a_worker_receipt import terminal_projection
        self.prepare();self.api.read_pod.return_value=self.pod;self.allow_models=1
        stream=Mock()
        def factory(**kwargs):
            stream.start.side_effect=kwargs['before_attach'];return stream
        self.controller.open_cli_stream(self.task,stream_factory=factory)
        receipt=dict(self.task.a2a_cli_context,scopeUid=self.pod['metadata']['uid'],stopped=True,
            processExitVerified=True,descendantAbsenceVerified=True,pidNamespaceInode=123,
            exitCode=0,output='synthetic result')
        self.pod['status']['containerStatuses'][0]['state']={'terminated':dict(exitCode=0,
            finishedAt='synthetic',message=json.dumps(terminal_projection(receipt)))}
        self.expires=50
        result=self.controller.observe_terminal(self.task)
        self.assertTrue(result['descendantAbsenceVerified'])
        self.assertFalse(result['outputAvailable']);self.assertFalse(result['guardStopped'])
        self.assertEqual(self.task.a2a_cli_worker['phase'],'dispatch-reserved')
        self.assertTrue(self.controller.observe_terminal(self.task,stream_receipt=receipt)['outputAvailable'])
        stream.start.assert_called_once();stream.send_line.assert_called_once()
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            self.task.directory=Path(directory)
            retained=self.controller.retain_terminal(self.task,stream_receipt=receipt)
            metadata=json.loads((Path(directory)/'a2a-worker-terminal.json').read_bytes())
            self.assertNotIn('output',metadata)
            self.assertEqual(metadata['scopeUid'],self.pod['metadata']['uid'])
            self.assertEqual(retained['phase'],'dispatch-reserved')
            recovered=self.controller.recover_terminal(self.task)
            self.assertTrue(recovered['processExitVerified'])
            self.assertFalse(recovered['outputAvailable'])
            stream.start.assert_called_once();stream.send_line.assert_called_once()
            import base64,hashlib
            self.expires=200;self.allow_models=0
            del self.task.request['prompt']  # Real Task.recover deliberately retains no raw prompt.
            guard=Mock()
            def guard_factory(**kwargs):
                self.assertEqual(kwargs['container'],'model-guard')
                guard.start.side_effect=kwargs['before_attach']
                return guard
            def response(**_):
                request=json.loads(guard.send_line.call_args.args[0])
                raw=(json.dumps(dict(event='task-fenced',task_id=self.task.id,
                    task_correlation_id=self.task.correlation_id,operation_id=request['operationId'],
                    utc='synthetic'))+'\n').encode()
                return json.dumps(dict(kind='DSH_GUARD_LOCAL_DRAIN_V1',
                    **{key:request[key] for key in ('taskId','correlationId','podUID','operationId')},
                    localInflightDrained=True,providerExecutionStoppedVerified=False,
                    ledgerSha256=hashlib.sha256(raw).hexdigest(),ledgerBase64=base64.b64encode(raw).decode()))
            guard.receive_line.side_effect=response
            drained=self.controller.drain_guard(self.task,stream_factory=guard_factory)
            self.assertTrue(drained['localInflightDrained'])
            self.assertFalse(drained['providerExecutionStoppedVerified'])
            self.assertTrue((Path(directory)/'a2a-guard-ledger.jsonl').exists())
            self.assertEqual(self.task.a2a_cli_worker['phase'],'dispatch-reserved')
            with self.assertRaisesRegex(ValueError,'NO_REATTACH'):
                self.controller.drain_guard(self.task,stream_factory=guard_factory)
            guard.send_line.assert_called_once();guard.close.assert_called_once()
            with self.assertRaisesRegex(ValueError,'PROCESS_EXIT_UNVERIFIED'):
                self.controller.observe_drained_guard(self.task)
            status=self.pod['status']['containerStatuses'][1]
            status['state']={'terminated':dict(exitCode=137,finishedAt='synthetic')}
            with self.assertRaisesRegex(ValueError,'PROCESS_EXIT_UNVERIFIED'):
                self.controller.observe_drained_guard(self.task)
            status['state']['terminated']['exitCode']=0
            checked=self.controller.observe_drained_guard(self.task)
            self.assertTrue(checked['localGuardExitVerified']);self.assertFalse(checked['workerRetired'])
            self.assertEqual(checked['reservedUpstreamStarts'],0)
            ledger_path=Path(directory)/'a2a-guard-ledger.jsonl'
            ledger_path.write_bytes(ledger_path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError,'BYTES_CHANGED'):
                self.controller.observe_drained_guard(self.task)
        self.api.read_pod.return_value=None
        with self.assertRaisesRegex(ValueError,'NOT_TERMINAL_EVIDENCE'):
            self.controller.observe_terminal(self.task)

    def test_cancel_uses_existing_stream_once_and_requires_matching_physical_stop_receipt(self):
        from scripts.a2a_worker_receipt import terminal_projection
        self.prepare();self.api.read_pod.return_value=self.pod;self.allow_models=1
        stream=Mock()
        def factory(**kwargs):
            stream.start.side_effect=kwargs['before_attach'];return stream
        self.controller.open_cli_stream(self.task,stream_factory=factory)
        self.task.state='cancelling';operation='d'*32
        self.task.a2a_cli_cancel=dict(operationId=operation,status='reserved');self.allow_models=0
        result=self.controller.send_cancel_once(self.task,operation_id=operation)
        self.assertFalse(result['processExitVerified'])
        sent=json.loads(stream.send_line.call_args.args[0])
        self.assertEqual(sent,dict(kind='cancel',context={**self.task.a2a_cli_context,
            'scopeUid':self.pod['metadata']['uid']},operationId=operation))
        self.assertEqual(stream.send_line.call_count,2)
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):
            self.controller.send_cancel_once(self.task,operation_id=operation)
        self.assertEqual(stream.send_line.call_count,2);stream.start.assert_called_once()
        receipt=dict(self.task.a2a_cli_context,scopeUid=self.pod['metadata']['uid'],stopped=True,
            processExitVerified=True,descendantAbsenceVerified=True,pidNamespaceInode=123,
            exitCode=None,output='',cancelled=True,operationId=operation)
        self.pod['status']['containerStatuses'][0]['state']={'terminated':dict(exitCode=0,
            finishedAt='synthetic',message=json.dumps(terminal_projection(receipt)))}
        self.assertTrue(self.controller.observe_cancel(self.task,operation_id=operation)['descendantAbsenceVerified'])
        with self.assertRaises(ValueError):self.controller.observe_cancel(self.task,operation_id='e'*32)

    def test_failed_stop_reservation_persistence_never_sends_cancel_frame(self):
        self.prepare();self.api.read_pod.return_value=self.pod;self.allow_models=1;stream=Mock()
        def factory(**kwargs):
            stream.start.side_effect=kwargs['before_attach'];return stream
        self.controller.open_cli_stream(self.task,stream_factory=factory)
        self.task.state='cancelling';self.task.a2a_cli_cancel=dict(operationId='d'*32,status='reserved')
        self.allow_models=0;self.task.save.side_effect=OSError('synthetic stop reservation failure')
        with self.assertRaises(OSError):self.controller.send_cancel_once(self.task,operation_id='d'*32)
        stream.send_line.assert_called_once()
        self.assertEqual(self.task.state,'interrupted')
        self.assertEqual(self.task.a2a_cli_worker['phase'],'persistence-uncertain')

    def test_cancel_waits_for_same_initial_frame_without_holding_task_lock(self):
        from threading import Event,Thread
        self.prepare();self.api.read_pod.return_value=self.pod;self.allow_models=1
        entered=Event();release=Event();reserved=Event();sent=[];errors=[];stream=Mock()
        def write(raw):
            self.assertFalse(self.task.persistence_lock._is_owned())
            value=json.loads(raw);sent.append(value)
            if len(sent)==1:
                entered.set()
                if not release.wait(5):raise TimeoutError('synthetic test frame not released')
        def factory(**kwargs):
            stream.start.side_effect=kwargs['before_attach'];stream.send_line.side_effect=write
            return stream
        def call(function):
            try:function()
            except BaseException as exc:errors.append(exc)
        initial=Thread(target=lambda:call(lambda:self.controller.open_cli_stream(self.task,stream_factory=factory)))
        initial.start()
        try:
            self.assertTrue(entered.wait(5))
            self.task.state='cancelling';self.task.a2a_cli_cancel=dict(operationId='d'*32,status='reserved')
            self.allow_models=0
            self.task.save.side_effect=lambda:reserved.set() if self.task.a2a_cli_worker.get('stopFrameOperationId') else None
            stop=Thread(target=lambda:call(lambda:self.controller.send_cancel_once(self.task,operation_id='d'*32)))
            stop.start()
            try:
                self.assertTrue(reserved.wait(5));self.assertEqual(len(sent),1)
                release.set();stop.join(timeout=5)
                self.assertFalse(stop.is_alive())
            finally:release.set();stop.join(timeout=5)
        finally:release.set();initial.join(timeout=5)
        self.assertFalse(initial.is_alive());self.assertEqual(errors,[])
        self.assertEqual(len(sent),2);self.assertEqual(sent[1]['kind'],'cancel')
        stream.start.assert_called_once()

    def test_uncertain_initial_delivery_closes_stream_without_sending_or_retrying_stop(self):
        self.prepare();self.api.read_pod.return_value=self.pod;self.allow_models=1
        stream=Mock()
        def factory(**kwargs):
            stream.start.side_effect=kwargs['before_attach'];return stream
        self.controller.open_cli_stream(self.task,stream_factory=factory)
        self.controller.dispatch_completion[self.task.id]['delivered']=False
        self.task.state='cancelling';operation='d'*32
        self.task.a2a_cli_cancel=dict(operationId=operation,status='reserved');self.allow_models=0
        with self.assertRaisesRegex(ValueError,'STOP_NOT_VERIFIED'):
            self.controller.send_cancel_once(self.task,operation_id=operation)
        stream.close.assert_called_once();stream.send_line.assert_called_once()
        with self.assertRaisesRegex(ValueError,'NO_RESEND'):
            self.controller.send_cancel_once(self.task,operation_id=operation)
        stream.send_line.assert_called_once()

    def test_stream_is_reserved_before_one_private_frame_and_same_handle_is_retained(self):
        self.prepare();self.api.read_pod.return_value=self.pod;self.allow_models=1
        stream=Mock()
        def factory(**kwargs):
            stream.start.side_effect=kwargs['before_attach']
            stream.send_line.side_effect=lambda *_:self.assertFalse(self.task.persistence_lock._is_owned())
            return stream
        result=self.controller.open_cli_stream(self.task,stream_factory=factory)
        self.assertIs(result,stream);self.assertIs(self.controller.streams[self.task.id],stream)
        self.assertIn('attachOperationId',self.task.a2a_cli_worker)
        stream.send_line.assert_called_once()
        request=json.loads(stream.send_line.call_args.args[0])
        self.assertEqual(request['context']['scopeUid'],self.pod['metadata']['uid'])
        with self.assertRaises(ValueError):self.controller.open_cli_stream(self.task,stream_factory=factory)
        stream.send_line.assert_called_once()
