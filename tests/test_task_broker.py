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
    def call(self,path,method='GET',body=None,authorized=True):
        headers={'Authorization':'Bearer '+'x'*32} if authorized else {}
        data=None if body is None else json.dumps(body).encode()
        if data: headers['Content-Type']='application/json'
        try:
            with request.urlopen(request.Request(self.url+path,method=method,data=data,headers=headers),timeout=3) as r:return r.status,json.load(r)
        except error.HTTPError as e:return e.code,json.load(e)
    def test_auth_and_capabilities_fail_closed(self):
        self.assertEqual(self.call('/v1/capabilities',authorized=False)[0],401)
        status,value=self.call('/v1/capabilities');self.assertEqual(status,200)
        self.assertEqual(next(x for x in value['backends'] if x['id']=='openshell')['enabled'],False)
        self.assertEqual(value['runtimes'],['claude','deepagents','sdk'])
    def test_project_escape_refused(self):
        with self.assertRaises(ValueError): self.module.confined_project('../outside')
    def test_commands_are_fixed_and_bounded(self):
        project=self.workspace/'project'
        sdk=self.module.command_for('sdk','hello',False,project,'a'*32)
        self.assertEqual(sdk[:6],['/usr/local/bin/dsh-unattended','sdk','--task-id','a'*32,'--cwd',str(project)])
        self.assertEqual(sdk[-3:],['--','--prompt','hello'])
        resumed=self.module.command_for('sdk','',False,project,'a'*32,True)
        self.assertIn('--resume',resumed);self.assertEqual(resumed[-2:],['--','--resume'])
        claude=self.module.command_for('claude','hello',True,project,'a'*32)
        self.assertIn('acceptEdits',claude);self.assertIn('--output-format',claude)
    @mock.patch('subprocess.Popen')
    def test_create_stream_and_recovery_record(self,popen):
        child=popen.return_value;child.stdout=iter(['first\n','second\n']);child.wait.return_value=0
        body={'runtime':'sdk','backend':'private','project':'project','prompt':'read README','writes':False,'approved':True}
        status,value=self.call('/v1/tasks','POST',body);self.assertEqual(status,202)
        task=self.module.REGISTRY.get(value['taskId'])
        for _ in range(100):
            if task.state=='completed':break
            threading.Event().wait(.01)
        self.assertEqual(task.state,'completed')
        status,events=self.call('/v1/tasks/'+task.id+'/events?after=0');self.assertEqual(status,200)
        self.assertIn('first', ''.join(e['data'].get('text','') for e in events['events']))
        self.assertTrue((task.directory/'task.json').exists())
    def test_invalid_shape_and_openshell_refused(self):
        body={'runtime':'sdk','backend':'openshell','project':'project','prompt':'x','writes':False,'approved':True}
        self.assertEqual(self.call('/v1/tasks','POST',body)[0],400)
    @mock.patch('subprocess.Popen')
    def test_sdk_interrupt_requires_explicit_resume_approval(self,popen):
        first=mock.Mock();first.stdout=iter(['approval required\n']);first.wait.return_value=75
        second=mock.Mock();second.stdout=iter(['resumed\n']);second.wait.return_value=0
        popen.side_effect=[first,second]
        body={'runtime':'sdk','backend':'private','project':'project','prompt':'write file','writes':True,'approved':True}
        status,value=self.call('/v1/tasks','POST',body);self.assertEqual(status,202)
        task=self.module.REGISTRY.get(value['taskId'])
        for _ in range(100):
            if task.state=='awaiting_approval':break
            threading.Event().wait(.01)
        self.assertEqual(task.state,'awaiting_approval')
        self.assertEqual(self.call('/v1/tasks/'+task.id+'/approve','POST',{'approved':False})[0],400)
        self.assertEqual(self.call('/v1/tasks/'+task.id+'/approve','POST',{'approved':True})[0],202)
        for _ in range(100):
            if task.state=='completed':break
            threading.Event().wait(.01)
        self.assertEqual(task.state,'completed')
        self.assertIn('--resume',popen.call_args.args[0])
    def test_one_active_task_is_enforced(self):
        request_value={'runtime':'sdk','backend':'private','project':'project','prompt':'x','writes':False,'approved':True}
        task=self.module.Task('b'*32,request_value);task.state='running';self.module.REGISTRY.tasks[task.id]=task
        with self.assertRaisesRegex(RuntimeError,'TASK_ALREADY_ACTIVE'): self.module.REGISTRY.create(request_value)
        task.state='completed';self.module.REGISTRY.tasks.pop(task.id,None)
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
