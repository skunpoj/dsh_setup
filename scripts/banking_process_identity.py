"""Fixed privilege boundary for an already-authorized root banking controller."""
import os,stat
from pathlib import Path
AGENT_UID=10001
PROTECTED=Path('/state/banking-guard-protected')

def agent_kwargs(*,platform=None,euid=None):
    platform=os.name if platform is None else platform
    if platform!='posix':return {}
    euid=os.geteuid() if euid is None else euid
    if euid==0:return dict(user=AGENT_UID,group=AGENT_UID,extra_groups=[],umask=0o077)
    if euid!=AGENT_UID:raise ValueError('FIXED_AGENT_IDENTITY_REQUIRED')
    return {}

def banking_guard_state(task,*,scope_file=Path('/etc/dsh/banking-sdk-scope.json')):
    if os.name!='posix' or os.geteuid()!=0 or not scope_file.exists():return None
    from banking_allowance import _unique_json
    fd=os.open(scope_file,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>65536:raise ValueError('PROTECTED_BANKING_SCOPE_REQUIRED')
        scope=_unique_json(stream.read(65537))
    if scope.get('kind')!='DSH_BANKING_SDK_SCOPE_V1' or scope.get('mode')!='banking':raise ValueError('BANKING_CONTROLLER_SCOPE_REQUIRED')
    info=PROTECTED.stat()
    if not os.path.ismount(PROTECTED) or PROTECTED.is_symlink() or info.st_uid!=0 or info.st_mode&0o077:raise ValueError('PROTECTED_BANKING_GUARD_ROOT_REQUIRED')
    if not isinstance(task,str) or not __import__('re').fullmatch(r'[A-Za-z0-9_-]{1,128}',task):raise ValueError('EXACT_GUARD_TASK_REQUIRED')
    parent=PROTECTED/'tasks'/'cli'
    parent.mkdir(mode=0o700,exist_ok=True)
    if parent.is_symlink() or parent.stat().st_uid!=0 or parent.stat().st_mode&0o077:raise ValueError('ROOT_PRIVATE_CLI_GUARD_STATE_REQUIRED')
    return parent/task
