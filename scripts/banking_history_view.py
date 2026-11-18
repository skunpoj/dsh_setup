"""Read-only legacy event view under UID10001, never accounting/replay authority."""
import json,os,re,subprocess,sys
from pathlib import Path
LEGACY=Path('/state/web-tasks')

def read_view(task_id,subject,after,*,root=LEGACY):
    if not re.fullmatch(r'[a-f0-9]{32}',task_id) or not isinstance(subject,str) or len(subject)>256 or type(after) is not int or after<0:raise ValueError('EXACT_HISTORY_QUERY_REQUIRED')
    root=Path(root);directory=root/task_id
    try:
        if directory.is_symlink() or not directory.resolve().is_relative_to(root.resolve()):raise ValueError('HISTORY_PATH_ESCAPE')
        def read(name,maximum):
            path=directory/name
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):raise ValueError('HISTORY_PATH_ESCAPE')
            with path.open('rb') as stream:
                raw=stream.read(maximum+1)
                if len(raw)>maximum:raise ValueError('HISTORY_SIZE_LIMIT')
                return raw
        task=json.loads(read('task.json',1048576))
    except FileNotFoundError:return dict(status=404,body={'error':'TASK_NOT_FOUND'})
    if task.get('id')!=task_id:raise ValueError('HISTORY_TASK_ID_CHANGED')
    expected=task.get('authenticatedSubject');native=task.get('nativeSdk')
    if expected is not None and expected!=subject or isinstance(native,dict) and native.get('subject')!=subject:return dict(status=403,body={'error':'FOREIGN_TASK_SUBJECT'})
    try:raw=read('events.jsonl',8*1024*1024)
    except FileNotFoundError:raw=b''
    rows=[]
    for line in raw.splitlines():
        row=json.loads(line)
        if not isinstance(row,dict) or type(row.get('sequence')) is not int:raise ValueError('HISTORY_EVENTS_REFUSED')
        if row['sequence']>after:rows.append(row)
    more=len(rows)>200;rows=rows[:200];state=task.get('state')
    # A retained nonterminal state is never interpreted as a live process or
    # offered a saved approval; the original bytes remain untouched.
    state=state if state in {'completed','failed','cancelled','interrupted'} else 'interrupted'
    return dict(status=200,body=dict(taskId=task_id,state=state,events=rows,next=rows[-1]['sequence'] if rows else after,more=more,nativeApproval=None,historicalReadOnly=True))

def legacy_response(task_id,subject,after):
    from scripts.banking_process_identity import agent_kwargs
    if sys.platform!='linux' or os.geteuid()!=0:raise ValueError('ROOT_HISTORY_READER_SUPERVISOR_REQUIRED')
    result=subprocess.run([sys.executable,'-I','-S','/opt/dsh/scripts/banking_history_view.py','--read',task_id,subject,str(after)],env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8'},capture_output=True,timeout=5,check=True,**agent_kwargs())
    if len(result.stdout)>16*1024*1024:raise ValueError('HISTORY_VIEW_SIZE_LIMIT')
    value=json.loads(result.stdout)
    if not isinstance(value,dict) or set(value)!={'status','body'} or value['status'] not in {200,403,404} or not isinstance(value['body'],dict):raise ValueError('HISTORY_VIEW_SCHEMA_REFUSED')
    return value['status'],value['body']

def read_token(environment):
    if environment not in {'secure','internet'}:raise ValueError('FIXED_RUNTIME_TOKEN_SCOPE_REQUIRED')
    path=Path('/runtime-tokens')/environment
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:raw=stream.read(4097)
    token=raw.decode('utf-8').strip()
    if len(raw)>4096 or not re.fullmatch(r'[A-Za-z0-9_-]{20,512}',token):raise ValueError('RUNTIME_TOKEN_FORMAT_REFUSED')
    return token

def runtime_token(environment):
    from scripts.banking_process_identity import agent_kwargs
    if sys.platform!='linux' or os.geteuid()!=0:raise ValueError('ROOT_TOKEN_READER_SUPERVISOR_REQUIRED')
    if environment not in {'secure','internet'}:raise ValueError('FIXED_RUNTIME_TOKEN_SCOPE_REQUIRED')
    result=subprocess.run([sys.executable,'-I','-S','/opt/dsh/scripts/banking_history_view.py','--token',environment],env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8'},capture_output=True,timeout=5,check=True,**agent_kwargs())
    if len(result.stdout)>4096:raise ValueError('RUNTIME_TOKEN_SIZE_LIMIT')
    token=json.loads(result.stdout)
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,512}',token):raise ValueError('RUNTIME_TOKEN_FORMAT_REFUSED')
    return token

if __name__=='__main__':
    if sys.platform!='linux' or os.geteuid()!=10001 or os.getegid()!=10001 or os.getgroups():raise ValueError('UNPRIVILEGED_HISTORY_READER_REQUIRED')
    if len(sys.argv)==3 and sys.argv[1]=='--token':value=read_token(sys.argv[2])
    elif len(sys.argv)==5 and sys.argv[1]=='--read':value=read_view(sys.argv[2],sys.argv[3],int(sys.argv[4]))
    else:raise ValueError('FIXED_HISTORY_READ_ONLY_COMMAND_REQUIRED')
    # Private captured pipe to root broker, never a runtime log or tool output.
    print(json.dumps(value,separators=(',',':')))
