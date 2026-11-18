"""Private banking evidence before UI caps; no hidden reasoning/auth/provider transport.

No truncation/drop policy: IO/inventory/drain failure fails task acceptance.
Filesystem hashes are read as agent10001; capture stores remain root0700/0600.
"""
import copy,hashlib,json,os,re,stat,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path('/state/banking-guard-protected/controller/web-tasks')

def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def sync_dir(path):
    if os.name=='posix':
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
def exclusive(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    sync_dir(path.parent)

def inventory(project):
    root=Path(project).resolve(strict=True)
    if not root.is_dir():raise ValueError('CAPTURE_PROJECT_DIRECTORY_REQUIRED')
    rows=[]
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in dirs:
            if (Path(parent)/name).is_symlink():raise ValueError('CAPTURE_SYMLINK_REFUSED')
        for name in sorted(files):
            path=Path(parent)/name
            if path.is_symlink():raise ValueError('CAPTURE_SYMLINK_REFUSED')
            fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0));h=hashlib.sha256()
            with os.fdopen(fd,'rb') as stream:
                before=os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode):raise ValueError('CAPTURE_REGULAR_FILE_REQUIRED')
                while True:
                    raw=stream.read(1048576)
                    if not raw:break
                    h.update(raw)
                after=os.fstat(stream.fileno())
            if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('CAPTURE_INPUT_CHANGED_DURING_HASH')
            rows.append(dict(path=path.relative_to(root).as_posix(),bytes=after.st_size,sha256=h.hexdigest()))
    return sorted(rows,key=lambda row:row['path'])

def agent_inventory(project):
    from scripts.banking_process_identity import agent_kwargs
    result=subprocess.run([sys.executable,'-I','-S','/opt/dsh/scripts/banking_private_capture.py','--inventory',str(project)],capture_output=True,timeout=60,check=True,env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8'},**agent_kwargs())
    value=json.loads(result.stdout)
    if not isinstance(value,list):raise ValueError('CAPTURE_INVENTORY_REQUIRED')
    return value

def visible_notification(method,payload):
    if method!='session.event' or not isinstance(payload,dict):return None
    event=payload.get('event')
    if not isinstance(event,dict) or type(event.get('seq')) is not int or not isinstance(event.get('data'),dict):return None
    kind=event.get('type');data=event['data'];base=dict(method=method,sessionId=payload.get('sessionId'),sequence=event['seq'],type=kind)
    if kind=='tool/call':
        if set(data)-{'turn','step','callId','name','arguments'}:raise ValueError('VISIBLE_TOOL_CALL_SCHEMA_REQUIRED')
        base['data']={key:data[key] for key in ('turn','step','callId','name','arguments') if key in data};return base
    if kind not in {'assistant/message','tool/result'}:return None
    message=data.get('message')
    if not isinstance(message,dict) or not isinstance(message.get('content'),list):raise ValueError('VISIBLE_MESSAGE_CONTENT_REQUIRED')
    content=[]
    for block in message['content']:
        if not isinstance(block,dict):raise ValueError('VISIBLE_CONTENT_BLOCK_REQUIRED')
        if block.get('type')=='text':content.append({'type':'text','text':block['text']})
        elif block.get('type')=='tool-call':content.append({key:block[key] for key in ('type','id','name','arguments')})
        elif block.get('type')!='reasoning':raise ValueError('UNSUPPORTED_VISIBLE_BLOCK_CAPTURE_REFUSED')
        # Reasoning and opaque provider/system/config/header/private metadata
        # are never retained; unsupported visible blocks refuse completeness.
    base['data']=dict(turn=data.get('turn'),step=data.get('step'),message={'role':message.get('role'),'content':content})
    if kind=='tool/result':base['data']['message'].update(toolCallId=message.get('toolCallId'),isError=message.get('isError',False))
    return base

def visible_cli_bytes(raw,runtime):
    if runtime!='claude':return raw
    try:value=json.loads(raw)
    except (ValueError,UnicodeDecodeError):return raw  # visible plain stdout/stderr
    if not isinstance(value,dict):return raw
    kind=value.get('type')
    if kind in {'assistant','user'}:
        message=value.get('message',{});content=[]
        blocks=message.get('content',[])
        if not isinstance(blocks,list):raise ValueError('UNSUPPORTED_VISIBLE_CLI_MESSAGE')
        for block in blocks:
            if not isinstance(block,dict):raise ValueError('UNSUPPORTED_VISIBLE_CLI_BLOCK')
            if block.get('type')=='text':content.append({'type':'text','text':block['text']})
            elif block.get('type')=='tool_use':content.append({k:block[k] for k in ('type','id','name','input') if k in block})
            elif block.get('type')=='tool_result':
                item={k:block[k] for k in ('type','tool_use_id','is_error') if k in block}
                body=block.get('content')
                if isinstance(body,str):item['content']=body
                elif isinstance(body,list):
                    visible=[]
                    for inner in body:
                        if not isinstance(inner,dict):raise ValueError('UNSUPPORTED_VISIBLE_CLI_TOOL_BLOCK')
                        if inner.get('type')=='text':visible.append({'type':'text','text':inner['text']})
                        elif inner.get('type') not in {'thinking','redacted_thinking','reasoning'}:raise ValueError('UNSUPPORTED_VISIBLE_CLI_TOOL_BLOCK')
                    item['content']=visible
                elif body is not None:raise ValueError('UNSUPPORTED_VISIBLE_CLI_TOOL_RESULT')
                content.append(item)
            elif block.get('type') not in {'thinking','redacted_thinking','reasoning'}:raise ValueError('UNSUPPORTED_VISIBLE_CLI_BLOCK')
        return encoded(dict(type=kind,message={'role':message.get('role'),'content':content}))+b'\n' if content else b''
    if kind=='result':return encoded({k:value[k] for k in ('type','subtype','is_error','result','errors','permission_denials') if k in value})+b'\n'
    if kind=='stream_event':
        event=value.get('event',{});delta=event.get('delta',{})
        if delta.get('type') in {'thinking_delta','signature_delta'}:return b''
        if delta.get('type') not in {'text_delta','input_json_delta'}:
            if event.get('type') in {'message_start','message_delta','message_stop','content_block_stop'}:return b''
            raise ValueError('UNSUPPORTED_VISIBLE_CLI_STREAM_EVENT')
        return encoded(dict(type=kind,event={'type':event.get('type'),'index':event.get('index'),'delta':{k:delta[k] for k in ('type','text','partial_json') if k in delta}}))+b'\n'
    # System/init/auth/usage/cost/opaque diagnostics are not response/tool text.
    if kind in {'system','rate_limit_event'}:return b''
    raise ValueError('UNSUPPORTED_VISIBLE_CLI_FRAME')

class PrivateCapture:
    def __init__(self,directory,*,request,identity,input_inventory,owner_check=True):
        self.root=Path(directory)/'private-capture';self.root.mkdir(mode=0o700,exist_ok=False)
        if owner_check and (os.name!='posix' or os.geteuid()!=0):raise ValueError('ROOT_PRIVATE_CAPTURE_REQUIRED')
        self.lock=threading.RLock();self.closed=False;self.failed=False;self.drain_verified=False;self.runtime=request.get('runtime')
        exclusive(self.root/'received-request.json',encoded(dict(request=request,identity=identity)))
        exclusive(self.root/'input-inventory.json',encoded(input_inventory))
        for name in ('combined-stdout-stderr.bin','visible-events.jsonl','states.jsonl'):exclusive(self.root/name,b'')
    def append(self,name,raw):
        with self.lock:
            if self.closed:raise ValueError('PRIVATE_CAPTURE_ALREADY_FINAL')
            try:
                with (self.root/name).open('ab') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            except BaseException:
                self.failed=True
                raise
    def stdout(self,raw):
        if not isinstance(raw,bytes):raise ValueError('EXACT_STDOUT_BYTES_REQUIRED')
        try:
            raw=visible_cli_bytes(raw,self.runtime)
            if raw:self.append('combined-stdout-stderr.bin',raw)
        except BaseException:
            self.failed=True
            raise
    def event(self,kind,data):
        if kind=='output':return  # stdout/native-visible/final-response already captured before UI projection
        self.append('visible-events.jsonl',encoded(dict(kind=kind,data=data))+b'\n')
    def notification(self,method,payload):
        try:
            value=visible_notification(method,payload)
            if value is not None:self.event('native-visible',value)
        except BaseException:
            self.failed=True
            raise
    def state(self,value):self.append('states.jsonl',encoded(value)+b'\n')
    def final_response(self,text):
        try:exclusive(self.root/'sdk-final-response.txt',text.encode('utf-8'))
        except BaseException:
            self.failed=True
            raise
    def finish(self,*,terminal,artifacts):
        with self.lock:
            if self.closed:return
            if self.failed:raise ValueError('PRIVATE_CAPTURE_FAILED_NO_COMPLETENESS')
            exclusive(self.root/'terminal.json',encoded(terminal));exclusive(self.root/'artifact-inventory.json',encoded(artifacts))
            rows=[]
            for path in sorted(self.root.iterdir()):
                h=hashlib.sha256();size=0
                with path.open('rb') as stream:
                    while True:
                        raw=stream.read(1048576)
                        if not raw:break
                        size+=len(raw);h.update(raw)
                rows.append(dict(path=path.name,bytes=size,sha256=h.hexdigest()))
            exclusive(self.root/'capture-manifest.json',encoded(dict(kind='DSH_PRIVATE_BANKING_CAPTURE_V1',complete=True,files=rows,hiddenReasoningCaptured=False,authTransportCaptured=False,stdoutRepresentation='visible-cli-projection' if self.runtime=='claude' else 'exact-visible-combined-bytes')))
            self.closed=True

def capture_for_task(task,project):
    directory=Path(task.directory)
    if directory.parent!=ROOT:return None
    if task.request.get('handoffRuntime') is not None:raise ValueError('INDEPENDENT_BANKING_RUN_REQUIRED')
    from scripts.banking_sdk_bootstrap import protected_bytes
    scope=json.loads(protected_bytes('/etc/dsh/banking-sdk-scope.json',65536))
    identity={key:scope[key] for key in ('sourceCommit','imageDigest','packageAdmissionSha256','scopeDigest','sourceHashes','placement')}
    identity.update(taskId=task.id,correlationId=task.correlation_id,authenticatedSubject=task.authenticated_subject)
    return PrivateCapture(directory,request=copy.deepcopy(task.request),identity=identity,input_inventory=agent_inventory(project))

def write_cli_terminal(state,*,task,correlation,maximum,completion,ledger):
    if not completion.get('descendantAbsenceVerified') or type(completion.get('trueExitCode')) is not int:raise ValueError('CLI_TRUE_TERMINAL_PROOF_REQUIRED')
    raw=Path(ledger).read_bytes()
    proof=dict(kind='DSH_BANKING_CLI_TERMINAL_V1',taskId=task,correlationId=correlation,maxRequests=maximum,wrapperPID=os.getpid(),guardStopped=True,guardLedgerSha256=hashlib.sha256(raw).hexdigest(),**completion)
    exclusive(Path(state)/'terminal-receipt.json',encoded(proof))

def cli_terminal(task,code,pid):
    path=Path('/state/banking-guard-protected/tasks/cli')/task.id/'terminal-receipt.json'
    proof=json.loads(path.read_bytes())
    expected=dict(kind='DSH_BANKING_CLI_TERMINAL_V1',taskId=task.id,correlationId=task.correlation_id,wrapperPID=pid,trueExitCode=code,guardStopped=True,descendantAbsenceVerified=True)
    actual=proof.get('trueExitCode');expected.pop('trueExitCode')
    if type(actual) is not int or code!=(actual&255) or any(proof.get(k)!=v for k,v in expected.items()):raise ValueError('CLI_TERMINAL_IDENTITY_MISMATCH')
    proof=dict(proof,wrapperExitCode=code)
    ledger=path.parent/'model-starts.jsonl'
    if hashlib.sha256(ledger.read_bytes()).hexdigest()!=proof.get('guardLedgerSha256'):raise ValueError('CLI_TERMINAL_LEDGER_CHANGED')
    return proof

def sdk_terminal(task):
    if not task.private_capture.drain_verified:raise ValueError('SDK_VISIBLE_CAPTURE_DRAIN_UNVERIFIED')
    path=Path('/state/banking-guard-protected/controller')/(task.id+'.backend.json')
    doc=json.loads(path.read_bytes());row=doc['tasks']['backend'];proof=row.get('terminalWorkerProof')
    if row.get('phase')!='stopped' or row.get('taskId')!=task.id or row.get('binding',{}).get('correlationId')!=task.correlation_id or not isinstance(proof,dict) or proof.get('processExitVerified') is not True or proof.get('descendantAbsenceVerified') is not True:raise ValueError('SDK_ACTUAL_TERMINAL_PROOF_REQUIRED')
    return dict(kind='DSH_BANKING_SDK_CAPTURE_TERMINAL_V1',taskId=task.id,correlationId=task.correlation_id,workerProof=proof,runtimeIdentity=row['receipt']['runtimeIdentity'],guardFence=row['fence'],providerExecutionStoppedVerified=False)

if __name__=='__main__':
    if sys.platform!='linux' or os.geteuid()!=10001 or os.getegid()!=10001 or os.getgroups():raise ValueError('UNPRIVILEGED_INVENTORY_READER_REQUIRED')
    if len(sys.argv)!=3 or sys.argv[1]!='--inventory':raise ValueError('FIXED_CAPTURE_INVENTORY_COMMAND_REQUIRED')
    root=Path(sys.argv[2]).resolve(strict=True)
    if root==Path('/workspace') or not root.is_relative_to('/workspace'):raise ValueError('FIXED_CAPTURE_WORKSPACE_REQUIRED')
    print(json.dumps(inventory(root),separators=(',',':')))


def stop_cli_after_capture_failure(process):
    """Stop only the same already-owned wrapper group; never launch/retry work.

    Missing terminal proof remains interrupted and its full reservation held.
    """
    import signal
    if process is None or process.poll() is not None:return
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=5)
