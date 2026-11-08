"""Physical SDK stdio relay for one admitted PRIVATE PID-namespace worker.

Not a broker-local subprocess fallback or a qualification flag. Root init owns
descendant cleanup; the unprivileged official control child owns authenticated
SDK frames. Kubernetes identity and provider credentials are never passed in.
"""
import base64
import copy
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import threading
import time
import uuid
if __name__=='__main__':sys.path.insert(0,'/opt/dsh')
from scripts.a2a_pid_namespace_worker import (ControlPipe,WorkerCancellation,
    require_private_init,namespace_members,stop_namespace,unique_json)
from scripts.a2a_worker_stream import write_frame_once
from scripts.official_sdk_control_peer import COMMAND,MAX_FRAME
from scripts.a2a_worker_receipt import TerminationSink


def prepare_request(request,*,pod_uid):
    if (not isinstance(request,dict) or set(request)!={'context','bootstrap','timeoutSeconds'}
            or type(request['timeoutSeconds']) not in (int,float)
            or not 0<request['timeoutSeconds']<=120):raise ValueError('BOUNDED_SDK_WORKER_REQUEST_REQUIRED')
    context=request['context'];boot=copy.deepcopy(request['bootstrap'])
    if (not isinstance(context,dict) or set(context)!={'subject','stageId','correlationId','project','runtime','scopeUid'}
            or any(not isinstance(value,str) or not value or len(value)>256 for value in context.values())
            or context['runtime']!='sdk' or context['scopeUid']!=pod_uid or str(uuid.UUID(pod_uid))!=pod_uid
            or any(not re.fullmatch(r'[a-f0-9]{32}',context[k]) for k in ('stageId','correlationId'))):
        raise ValueError('EXACT_SDK_WORKER_CONTEXT_REQUIRED')
    if not isinstance(boot,dict) or set(boot)!={'key','binding','options'}:
        raise ValueError('EXACT_SDK_BOOTSTRAP_REQUIRED')
    if not isinstance(boot['key'],str) or len(base64.b64decode(boot['key'],validate=True))!=32:
        raise ValueError('EPHEMERAL_SDK_PIPE_KEY_REQUIRED')
    binding=boot['binding']
    if (not isinstance(binding,dict) or set(binding)!={'subject','generation','taskId','sessionId','project','correlationId','packageAdmissionSha256'}
            or any(binding.get(key)!=context[other] for key,other in
                [('subject','subject'),('taskId','stageId'),('sessionId','stageId'),('project','project'),('correlationId','correlationId')])
            or not isinstance(binding['generation'],str) or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',binding['generation'])
            or not re.fullmatch(r'[a-f0-9]{64}',str(binding['packageAdmissionSha256']))):
        raise ValueError('SDK_BOOTSTRAP_BINDING_MISMATCH')
    options=boot['options']
    required={'provider','model','profile','cwd','runtime_cwd','dsh_bin','dsh_home','approval_requests',
        'base_url','api_key','max_tokens','initialize_timeout_seconds','request_timeout_seconds','shutdown_timeout_seconds','env'}
    if not isinstance(options,dict) or set(options)!=required:
        raise ValueError('FIXED_SDK_WORKER_OPTIONS_REQUIRED')
    fixed=dict(provider='deepseek-official',model='deepseek-v4.1-flash',profile='sdk',
        dsh_bin='/usr/local/bin/dsh-official-sdk-runtime',approval_requests=True,
        base_url='http://127.0.0.1:4001/v1',api_key='local-guard-placeholder',
        max_tokens=256,initialize_timeout_seconds=15,request_timeout_seconds=120,shutdown_timeout_seconds=2)
    if any(type(options[k]) is not type(value) or options[k]!=value for k,value in fixed.items()):
        raise ValueError('SDK_FIXED_GUARD_OR_POLICY_CHANGED')
    env=dict(PATH='/usr/local/bin:/usr/bin:/bin',LANG='C.UTF-8',HOME='/home/dsh/official-sdk',
        PYTHONDONTWRITEBYTECODE='1',OTEL_SDK_DISABLED='true',DO_NOT_TRACK='1',LANGSMITH_TRACING='false',
        DSH_UNATTENDED_TASK=context['stageId'],DSH_CORRELATION_ID=context['correlationId'],
        DSH_GUARDED_MODEL_BASE_URL=fixed['base_url'])
    supplied=options['env']
    if (not isinstance(supplied,dict) or set(supplied)!=set(env)
            or any(supplied.get(k)!=value for k,value in env.items() if k!='HOME')
            or any(not isinstance(options[k],str) or '\0' in options[k] for k in ('cwd','runtime_cwd','dsh_home'))
            or not isinstance(supplied['HOME'],str)):
        raise ValueError('SDK_WORKER_ENVIRONMENT_REFUSED')
    # The admitted Pod mounts exactly this one project at /workspace. Never
    # carry a broker host path or environment through to the isolated child.
    options.update(cwd='/workspace',runtime_cwd='/workspace',dsh_home=env['HOME'],env=env)
    return context,boot,env


def relay_once(request,*,control,emit):
    inode=require_private_init()
    pod_uid=Path('/etc/dsh-worker-identity/pod-uid').read_text(encoding='ascii').strip()
    context,bootstrap,environment=prepare_request(request,pod_uid=pod_uid)
    if namespace_members():raise ValueError('SDK_WORKER_NOT_EMPTY_BEFORE_START')
    home=Path('/home/dsh/official-sdk');home.mkdir(mode=0o700)
    os.chown(home,10001,10001)
    cancel=WorkerCancellation(context);child=None;selector=None;reader=None
    abort=threading.Event();output_frames=0;output_bytes=0
    def send(raw):
        if len(raw)>MAX_FRAME or not raw.endswith(b'\n'):raise ValueError('BOUNDED_SDK_FRAME_REQUIRED')
        write_frame_once(child.stdin.fileno(),raw,abort)
    def commands():
        try:
            while not abort.is_set():
                raw=control.readline(MAX_FRAME+4097)
                if not raw:
                    if not control.closing.is_set():cancel.disconnect('SDK_CONTROLLER_DISCONNECTED')
                    return
                if len(raw)>MAX_FRAME+4096 or not raw.endswith(b'\n'):
                    raise ValueError('BOUNDED_SDK_CONTROL_FRAME_REQUIRED')
                value=unique_json(raw)
                if value.get('kind')=='cancel':cancel.request(value);return
                if (set(value)!={'kind','context','frame'} or value['kind']!='sdk-frame'
                        or value['context']!=context or not isinstance(value['frame'],str)
                        or '\n' in value['frame'] or '\r' in value['frame']):
                    raise ValueError('FOREIGN_SDK_RELAY_FRAME')
                send((value['frame']+'\n').encode())
        except BaseException:cancel.disconnect('SDK_RELAY_CONTROL_REFUSED')
    try:
        child=subprocess.Popen(COMMAND,cwd='/workspace',env=environment,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=0,close_fds=True,
            start_new_session=True,user=10001,group=10001,extra_groups=[],umask=0o077)
        selector=selectors.DefaultSelector()
        selector.register(child.stdout,selectors.EVENT_READ,'stdout')
        selector.register(child.stderr,selectors.EVENT_READ,'stderr')
        send(json.dumps(bootstrap,separators=(',',':')).encode()+b'\n')
        reader=threading.Thread(target=commands);reader.start()
        deadline=time.monotonic()+request['timeoutSeconds'];buffer=bytearray()
        while selector.get_map():
            if cancel.event.is_set():break
            if time.monotonic()>=deadline:raise TimeoutError('SDK_WORKER_DEADLINE')
            for key,_ in selector.select(.05):
                block=os.read(key.fileobj.fileno(),65536)
                if not block:selector.unregister(key.fileobj);continue
                output_bytes+=len(block)
                if output_bytes>4*MAX_FRAME:raise ValueError('SDK_WORKER_OUTPUT_BUDGET')
                if key.data=='stderr':continue  # Never export raw SDK stderr.
                buffer.extend(block)
                while b'\n' in buffer:
                    line,_,rest=buffer.partition(b'\n');buffer=bytearray(rest)
                    if len(line)>MAX_FRAME:raise ValueError('SDK_WORKER_FRAME_LIMIT')
                    output_frames+=1
                    if output_frames>256:raise ValueError('SDK_WORKER_FRAME_COUNT_LIMIT')
                    emit(dict(kind='sdk-frame',context=context,frame=line.decode('utf-8')))
                if len(buffer)>MAX_FRAME:raise ValueError('SDK_WORKER_FRAME_LIMIT')
            if child.poll() is not None:stop_namespace()
        if cancel.event.is_set():
            stop_namespace()
            if cancel.error:raise ValueError(cancel.error)
            return dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True,
                pidNamespaceInode=inode,exitCode=None,output='',cancelled=True,operationId=cancel.operation_id)
        if buffer:raise ValueError('SDK_WORKER_PARTIAL_OUTPUT_FRAME')
        exit_code=child.wait(timeout=max(.01,deadline-time.monotonic()));stop_namespace()
        # Seal the reader before selecting the terminal outcome. An already
        # received cancellation must not be lost during final pipe cleanup.
        control.stop()
        reader.join(timeout=6)
        if reader.is_alive():raise RuntimeError('SDK_RELAY_READER_EXIT_UNVERIFIED')
        # Waiting/reaping can overlap a stop already received by the control
        # reader. Preserve that outcome instead of turning it into success.
        if cancel.event.is_set():
            if cancel.error:raise ValueError(cancel.error)
            return dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True,
                pidNamespaceInode=inode,exitCode=exit_code,output='',cancelled=True,operationId=cancel.operation_id)
        return dict(context,stopped=True,processExitVerified=True,descendantAbsenceVerified=True,
            pidNamespaceInode=inode,exitCode=exit_code,output='')
    finally:
        abort.set();control.stop()
        try:stop_namespace()
        finally:
            try:
                if reader is not None:
                    reader.join(timeout=6)
                    if reader.is_alive():raise RuntimeError('SDK_RELAY_READER_EXIT_UNVERIFIED')
            finally:
                try:
                    if selector is not None:selector.close()
                finally:
                    if child is not None:
                        try:child.stdin.close()
                        finally:
                            try:child.stdout.close()
                            finally:child.stderr.close()


def main():
    require_private_init();sink=TerminationSink();control=ControlPipe(sys.stdin.fileno())
    abort=threading.Event()
    def emit(value):
        raw=json.dumps(value,separators=(',',':')).encode()+b'\n'
        write_frame_once(sys.stdout.fileno(),raw,abort)
    try:
        raw=control.readline(MAX_FRAME+1)
        if len(raw)>MAX_FRAME or not raw.endswith(b'\n'):raise ValueError('BOUNDED_SDK_BOOTSTRAP_FRAME_REQUIRED')
        result=relay_once(unique_json(raw),control=control,emit=emit)
        sink.write(result);emit(dict(kind='terminal',receipt=result))
    finally:control.close();sink.close()


if __name__=='__main__':main()
