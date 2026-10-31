#!/usr/bin/env python3
"""Launch only the installed managed coding agent; never invoke a subscription login."""
import os,sys
from pathlib import Path
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
