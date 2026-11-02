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
        cls.server=cls.module.ThreadingHTTPServer(('127.0.0.1',0),cls.module.Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start(); cls.url='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls): cls.server.shutdown(); cls.temp.cleanup()
    def call(self,path,method='GET',body=None,authorized=True,subject=None):
        headers={'Authorization':'Bearer '+'x'*32} if authorized else {}
        if subject is not None:headers['X-DSH-Subject']=subject
        data=None if body is None else json.dumps(body).encode()
        if data: headers['Content-Type']='application/json'
        try:
            with request.urlopen(request.Request(self.url+path,method=method,data=data,headers=headers),timeout=3) as r:return r.status,json.load(r)
        except error.HTTPError as e:return e.code,json.load(e)
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
