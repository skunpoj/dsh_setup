#!/usr/bin/env python3
"""Launch only the installed managed coding agent; never invoke a subscription login."""
import os,sys,re
from pathlib import Path
from urllib.parse import urlsplit
def arguments(argv):
 if len(argv)>3: raise ValueError('Use deepagents, --help, --version, or -n TASK')
 if argv and argv[0] not in ['--help','--version','-n']: raise ValueError('Only the managed launch options are available')
 if argv and argv[0]=='-n' and (len(argv)!=2 or len(argv[1])>65536): raise ValueError('One bounded task required')
 if argv and argv[0]!='-n' and len(argv)!=1: raise ValueError('Unexpected launch arguments')
 return argv
def environment(parent):
 # Do not inherit provider keys, endpoint overrides, proxies, Python hooks or tracing.
 e={k:parent[k] for k in ['TERM','COLORTERM','LANG','LC_ALL','DSH_ENVIRONMENT'] if k in parent}
 e.update({'HOME':'/home/dsh','PATH':'/usr/local/bin:/usr/bin:/bin','DEEPAGENTS_HOME':'/state/deepagents','LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false','DO_NOT_TRACK':'1','OTEL_SDK_DISABLED':'true','DEEPAGENTS_CODE_AUTO_UPDATE':'0','DEEPAGENTS_CODE_NO_UPDATE_CHECK':'1'})
 keys=['DSH_GUARDED_MODEL_BASE_URL','DSH_UNATTENDED_TASK','DSH_CORRELATION_ID']
 if any(k in parent for k in keys):
  if not all(isinstance(parent.get(k),str) for k in keys):raise ValueError('Incomplete managed guard identity')
  u=urlsplit(parent[keys[0]])
  if u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.path!='/v1' or u.username or u.password or u.query or u.fragment:raise ValueError('Invalid managed guard endpoint')
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',parent[keys[1]]) or not re.fullmatch(r'[a-f0-9]{32}',parent[keys[2]]):raise ValueError('Invalid managed guard identity')
  e.update({k:parent[k] for k in keys})
 return e
def main():
 args=arguments(sys.argv[1:]);cwd=Path.cwd().resolve()
 if not cwd.is_relative_to(Path('/workspace').resolve()): raise ValueError('Start from your project under /workspace')
 p=Path('/state/deepagents');p.mkdir(mode=0o700,parents=True,exist_ok=True)
 if p.is_symlink() or p.stat().st_uid!=os.getuid() or p.stat().st_mode & 0o077: raise ValueError('Private Deep Agents state required')
 exe='/opt/dsh/deepagents/bin/python'
 os.execve(exe,[exe,'-I','-m','deepagents_code',*args],environment(os.environ))
if __name__=='__main__':
 try:main()
 except (ValueError,OSError):
  print('Managed Deep Agents refused: check the project, operator policy and installed image.',file=sys.stderr);raise SystemExit(64)
