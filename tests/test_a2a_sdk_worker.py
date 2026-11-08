"""SDK worker source contracts; never starts a real child or provider."""
import base64
import copy
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import Mock,patch
from scripts.a2a_sdk_worker import prepare_request,relay_once
from scripts.a2a_worker_receipt import terminal_projection,decode_projection
import json


class SDKWorkerTests(TestCase):
    def request(self):
        context=dict(subject='owner',stageId='a'*32,correlationId='b'*32,project='private',
            runtime='sdk',scopeUid='22222222-2222-4222-8222-222222222222')
        env=dict(PATH='/usr/local/bin:/usr/bin:/bin',LANG='C.UTF-8',HOME='/broker/private/home',
            PYTHONDONTWRITEBYTECODE='1',OTEL_SDK_DISABLED='true',DO_NOT_TRACK='1',LANGSMITH_TRACING='false',
            DSH_UNATTENDED_TASK=context['stageId'],DSH_CORRELATION_ID=context['correlationId'],
            DSH_GUARDED_MODEL_BASE_URL='http://127.0.0.1:4001/v1')
        options=dict(provider='deepseek-official',model='deepseek-v4.1-flash',profile='sdk',
            cwd='/broker/project',runtime_cwd='/broker/project',dsh_home=env['HOME'],
            dsh_bin='/usr/local/bin/dsh-official-sdk-runtime',approval_requests=True,
            base_url=env['DSH_GUARDED_MODEL_BASE_URL'],api_key='local-guard-placeholder',max_tokens=256,
            initialize_timeout_seconds=15,request_timeout_seconds=120,shutdown_timeout_seconds=2,env=env)
        binding=dict(subject='owner',generation='test-generation',taskId=context['stageId'],
            sessionId=context['stageId'],project='private',correlationId=context['correlationId'],
            packageAdmissionSha256='c'*64)
        return dict(context=context,bootstrap=dict(key=base64.b64encode(b'x'*32).decode(),
            binding=binding,options=options),timeoutSeconds=120)
    def prepare(self,value):return prepare_request(value,pod_uid=self.request()['context']['scopeUid'])
    def test_private_paths_are_rebased_and_original_input_is_unchanged(self):
        request=self.request();original=copy.deepcopy(request)
        context,boot,env=self.prepare(request)
        self.assertEqual(request,original)
        self.assertEqual(boot['options']['cwd'],'/workspace')
        self.assertEqual(boot['options']['runtime_cwd'],'/workspace')
        self.assertEqual(boot['options']['dsh_home'],'/home/dsh/official-sdk')
        self.assertNotIn('/broker',json.dumps(boot))
        self.assertEqual(env['DSH_CORRELATION_ID'],context['correlationId'])
    def test_foreign_context_binding_key_or_deadline_is_refused(self):
        for field in ('subject','project','stageId','correlationId','runtime','scopeUid'):
            value=self.request();value['context'][field]='foreign'
            with self.subTest(field=field),self.assertRaises(ValueError):self.prepare(value)
        value=self.request();value['bootstrap']['key']=base64.b64encode(b'x').decode()
        with self.assertRaises(ValueError):self.prepare(value)
        for limit in (0,121,True,'120'):
            value=self.request();value['timeoutSeconds']=limit
            with self.assertRaises(ValueError):self.prepare(value)
    def test_external_provider_root_command_extra_options_and_environment_are_refused(self):
        changes=[('base_url','https://external.invalid/v1'),('dsh_bin','/bin/sh'),
            ('api_key','synthetic-nonplaceholder'),('approval_requests',False),('max_tokens',True),
            ('patches',['untrusted'])]
        for field,item in changes:
            value=self.request();value['bootstrap']['options'][field]=item
            with self.subTest(field=field),self.assertRaises(ValueError):self.prepare(value)
        value=self.request();value['bootstrap']['options']['env']['UNADMITTED']='synthetic'
        with self.assertRaises(ValueError):self.prepare(value)
    def test_post_spawn_setup_failure_stops_namespace_and_closes_all_private_pipes(self):
        with ExitStack() as stack:
            request=self.request();context,boot,env=self.prepare(request)
            stack.enter_context(patch('scripts.a2a_sdk_worker.require_private_init',return_value=123))
            path=stack.enter_context(patch('scripts.a2a_sdk_worker.Path'))
            path.return_value.read_text.return_value=context['scopeUid']
            stack.enter_context(patch('scripts.a2a_sdk_worker.os.chown',create=True))
            stack.enter_context(patch('scripts.a2a_sdk_worker.namespace_members',return_value=set()))
            stop=stack.enter_context(patch('scripts.a2a_sdk_worker.stop_namespace'))
            popen=stack.enter_context(patch('scripts.a2a_sdk_worker.subprocess.Popen'))
            stack.enter_context(patch('scripts.a2a_sdk_worker.selectors.DefaultSelector',side_effect=OSError('synthetic setup failure')))
            with self.assertRaises(OSError):relay_once(request,control=Mock(),emit=Mock())
            stop.assert_called_once()
            self.assertEqual(popen.call_args.kwargs['user'],10001)
            self.assertEqual(popen.call_args.kwargs['group'],10001)
            self.assertTrue(popen.call_args.kwargs['close_fds'])
            for stream in (popen.return_value.stdin,popen.return_value.stdout,popen.return_value.stderr):
                stream.close.assert_called_once()
    def test_relay_preserves_authenticated_sdk_frame_and_returns_separate_stop_metadata(self):
        from threading import Event
        from types import SimpleNamespace
        from scripts.official_sdk_control_peer import SDKFrameCodec,COMMAND
        request=self.request();binding=request['bootstrap']['binding'];key=b'x'*32
        payload={'kind':'response','id':'d'*32,'ok':True,'result':{'synthetic':'checked'}}
        encoded=SDKFrameCodec(key,binding).encode(payload)
        closing=Event()
        control=SimpleNamespace(closing=closing,stop=closing.set,
            readline=lambda *_:(closing.wait(5) and b'') or b'')
        with ExitStack() as stack:
            stack.enter_context(patch('scripts.a2a_sdk_worker.require_private_init',return_value=123))
            path=stack.enter_context(patch('scripts.a2a_sdk_worker.Path'))
            path.return_value.read_text.return_value=request['context']['scopeUid']
            stack.enter_context(patch('scripts.a2a_sdk_worker.os.chown',create=True))
            stack.enter_context(patch('scripts.a2a_sdk_worker.namespace_members',return_value=set()))
            stop=stack.enter_context(patch('scripts.a2a_sdk_worker.stop_namespace'))
            popen=stack.enter_context(patch('scripts.a2a_sdk_worker.subprocess.Popen'))
            popen.return_value.poll.return_value=0;popen.return_value.wait.return_value=0
            selector=stack.enter_context(patch('scripts.a2a_sdk_worker.selectors.DefaultSelector')).return_value
            selector.get_map.side_effect=[{'stdout':object()},{}]
            selector.select.return_value=[(SimpleNamespace(data='stdout',fileobj=popen.return_value.stdout),None)]
            stack.enter_context(patch('scripts.a2a_sdk_worker.os.read',return_value=(encoded+'\n').encode()))
            writer=stack.enter_context(patch('scripts.a2a_sdk_worker.write_frame_once'))
            emit=Mock();receipt=relay_once(request,control=control,emit=emit)
            self.assertEqual(popen.call_args.args[0],COMMAND)
            bootstrap=json.loads(writer.call_args.args[1])
            self.assertEqual(bootstrap['options']['cwd'],'/workspace')
            frame=emit.call_args.args[0]
            self.assertEqual(frame['context'],request['context'])
            self.assertEqual(SDKFrameCodec(key,binding).decode(frame['frame']),payload)
            self.assertTrue(receipt['descendantAbsenceVerified']);self.assertEqual(receipt['output'],'')
            self.assertGreaterEqual(stop.call_count,1)

    def test_cancel_disconnect_deadline_output_budget_and_join_failure_are_fenced(self):
        from threading import Event
        from types import SimpleNamespace
        for scenario in ('cancel','disconnect','deadline','output-budget','reader-join'):
            with self.subTest(scenario=scenario),ExitStack() as stack:
                request=self.request();context=request['context'];closing=Event()
                command=dict(kind='cancel',context=context,operationId='d'*32)
                control=SimpleNamespace(closing=closing,stop=closing.set,
                    readline=lambda *_:(json.dumps(command)+'\n').encode() if scenario=='cancel' else b'')
                stack.enter_context(patch('scripts.a2a_sdk_worker.require_private_init',return_value=123))
                path=stack.enter_context(patch('scripts.a2a_sdk_worker.Path'))
                path.return_value.read_text.return_value=context['scopeUid']
                stack.enter_context(patch('scripts.a2a_sdk_worker.os.chown',create=True))
                stack.enter_context(patch('scripts.a2a_sdk_worker.namespace_members',return_value=set()))
                stop=stack.enter_context(patch('scripts.a2a_sdk_worker.stop_namespace'))
                popen=stack.enter_context(patch('scripts.a2a_sdk_worker.subprocess.Popen'))
                popen.return_value.poll.return_value=None;popen.return_value.wait.return_value=0
                selector=stack.enter_context(patch('scripts.a2a_sdk_worker.selectors.DefaultSelector')).return_value
                selector.get_map.return_value={} if scenario=='reader-join' else {'synthetic':object()}
                selector.select.return_value=[(SimpleNamespace(data='stderr',fileobj=popen.return_value.stderr),None)]
                stack.enter_context(patch('scripts.a2a_sdk_worker.os.read',return_value=b'x'*65536))
                stack.enter_context(patch('scripts.a2a_sdk_worker.write_frame_once'))
                clock=stack.enter_context(patch('scripts.a2a_sdk_worker.time.monotonic',return_value=0))
                if scenario=='deadline':clock.side_effect=[0,121]
                thread=Mock();thread.is_alive.return_value=scenario=='reader-join'
                def make_thread(*,target):
                    if scenario in {'cancel','disconnect'}:thread.start.side_effect=target
                    return thread
                stack.enter_context(patch('scripts.a2a_sdk_worker.threading.Thread',side_effect=make_thread))
                if scenario=='cancel':
                    result=relay_once(request,control=control,emit=Mock())
                    self.assertTrue(result['cancelled']);self.assertEqual(result['operationId'],'d'*32)
                    self.assertEqual(result['output'],'')
                else:
                    errors={'disconnect':('SDK_CONTROLLER_DISCONNECTED',ValueError),
                        'deadline':('SDK_WORKER_DEADLINE',TimeoutError),
                        'output-budget':('OUTPUT_BUDGET',ValueError),
                        'reader-join':('READER_EXIT_UNVERIFIED',RuntimeError)}
                    message,kind=errors[scenario]
                    with self.assertRaisesRegex(kind,message):relay_once(request,control=control,emit=Mock())
                self.assertGreaterEqual(stop.call_count,1)
                for stream in (popen.return_value.stdin,popen.return_value.stdout,popen.return_value.stderr):
                    stream.close.assert_called_once()

    def test_stop_arriving_during_child_exit_cannot_be_reported_as_normal_completion(self):
        from threading import Event
        from types import SimpleNamespace
        for scenario in ('cancel','disconnect','cancel-on-join'):
            with self.subTest(scenario=scenario),ExitStack() as stack:
                request=self.request();context=request['context'];closing=Event()
                command=dict(kind='cancel',context=context,operationId='d'*32)
                control=SimpleNamespace(closing=closing,stop=closing.set,
                    readline=lambda *_:(json.dumps(command)+'\n').encode() if scenario!='disconnect' else b'')
                stack.enter_context(patch('scripts.a2a_sdk_worker.require_private_init',return_value=123))
                path=stack.enter_context(patch('scripts.a2a_sdk_worker.Path'))
                path.return_value.read_text.return_value=context['scopeUid']
                stack.enter_context(patch('scripts.a2a_sdk_worker.os.chown',create=True))
                stack.enter_context(patch('scripts.a2a_sdk_worker.namespace_members',return_value=set()))
                stop=stack.enter_context(patch('scripts.a2a_sdk_worker.stop_namespace'))
                popen=stack.enter_context(patch('scripts.a2a_sdk_worker.subprocess.Popen'))
                selector=stack.enter_context(patch('scripts.a2a_sdk_worker.selectors.DefaultSelector')).return_value
                selector.get_map.return_value={}
                stack.enter_context(patch('scripts.a2a_sdk_worker.write_frame_once'))
                reader={};thread=Mock();thread.is_alive.return_value=False
                def make_thread(*,target):reader['target']=target;return thread
                stack.enter_context(patch('scripts.a2a_sdk_worker.threading.Thread',side_effect=make_thread))
                def child_exit(**_):
                    if scenario!='cancel-on-join':reader['target']()
                    return 0
                popen.return_value.wait.side_effect=child_exit
                if scenario=='cancel-on-join':thread.join.side_effect=lambda **_:reader['target']()
                if scenario!='disconnect':
                    result=relay_once(request,control=control,emit=Mock())
                    self.assertTrue(result.get('cancelled'))
                    self.assertEqual(result['operationId'],command['operationId'])
                    self.assertEqual(result['exitCode'],0)
                else:
                    with self.assertRaisesRegex(ValueError,'SDK_CONTROLLER_DISCONNECTED'):
                        relay_once(request,control=control,emit=Mock())
                self.assertGreaterEqual(stop.call_count,1)

    def test_sdk_physical_receipt_does_not_invent_a_model_result(self):
        value=dict(self.request()['context'],stopped=True,processExitVerified=True,
            descendantAbsenceVerified=True,pidNamespaceInode=123,exitCode=0,output='')
        saved=terminal_projection(value)
        self.assertEqual(saved['runtime'],'sdk');self.assertNotIn('output',saved)
        self.assertEqual(decode_projection(json.dumps(saved)),saved)
