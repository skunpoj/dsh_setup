#!/usr/bin/env python3
"""Launch only the installed managed coding agent; never invoke a subscription login."""
import os,re,sys,time
from pathlib import Path
def arguments(argv):
 if len(argv)>3: raise ValueError('Use deepagents, --help, --version, or -n TASK')
 if argv and argv[0] not in ['--help','--version','-n']: raise ValueError('Only the managed launch options are available')
 if argv and argv[0]=='-n' and (len(argv)!=2 or len(argv[1])>65536): raise ValueError('One bounded task required')
 if argv and argv[0]!='-n' and len(argv)!=1: raise ValueError('Unexpected launch arguments')
 return argv
def guard_environment(parent):
 # The unattended task wrapper (dsh-unattended) hands the managed client its per-task model guard. If this launcher drops it, the
 # model class falls back to the direct gateway route and the guard is bypassed (run of 9 Nov, L7: guard ledger empty). Pass exactly
 # the two guard variables, validated; refuse a half-set or malformed pair; leave interactive sessions (neither set) unchanged.
 base=parent.get('DSH_GUARDED_MODEL_BASE_URL','');task=parent.get('DSH_UNATTENDED_TASK','')
 if not base and not task: return {}
 if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{2,5}/v1',base) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',task): raise ValueError('Unattended model guard route is invalid')
 return {'DSH_GUARDED_MODEL_BASE_URL':base,'DSH_UNATTENDED_TASK':task}
def environment(parent):
 # Do not inherit provider keys, endpoint overrides, proxies, Python hooks or tracing.
 e={k:parent[k] for k in ['TERM','COLORTERM','LANG','LC_ALL','DSH_ENVIRONMENT'] if k in parent}
 e.update({'HOME':'/home/dsh','PATH':'/usr/local/bin:/usr/bin:/bin','DEEPAGENTS_HOME':'/state/deepagents','LANGSMITH_TRACING':'false','LANGCHAIN_TRACING_V2':'false','DO_NOT_TRACK':'1','OTEL_SDK_DISABLED':'true','DEEPAGENTS_CODE_AUTO_UPDATE':'0','DEEPAGENTS_CODE_NO_UPDATE_CHECK':'1'})
 e.update(guard_environment(parent))
 return e
BANKING_SHELL='dsh-banking-python,dsh-banking-unzip'
def shell_allow_list(parent,cwd,now=None,allowance_file=None):
 # The Deep Agents worker has file tools only (no shell, UTF-8 read_file), so a banking task could not unzip its data or run the numeric Python. The ONLY shell commands
 # ever allowed are the two bounded wrappers, and only for an unattended task whose project has a live deepagents grant in the root-owned banking allowance
 # (scripts/banking_allowance.py: root-owned, not writable, enabled, validated). Anything else, interactive sessions included, keeps the CLI default: no shell.
 if not parent.get('DSH_UNATTENDED_TASK'): return None
 try:
  if '/opt/dsh/scripts' not in sys.path: sys.path.append('/opt/dsh/scripts')
  import banking_allowance
  document=banking_allowance.load_allowance(allowance_file)
 except Exception: return None
 if document is None: return None
 moment=time.time() if now is None else now
 for grant in document['grants']:
  # A standing grant carries expiresAt: null (no end time; load_allowance validates it), which must mean 'no expiry', never a float<=None comparison (TypeError, uncaught here).
  expires=grant.get('expiresAt')
  if grant['runtime']=='deepagents' and grant['project']==cwd.name and (expires is None or moment<=expires): return BANKING_SHELL
 return None
def main():
 args=arguments(sys.argv[1:]);cwd=Path.cwd().resolve()
 if not cwd.is_relative_to(Path('/workspace').resolve()): raise ValueError('Start from your project under /workspace')
 p=Path('/state/deepagents');p.mkdir(mode=0o700,parents=True,exist_ok=True)
 if p.is_symlink() or p.stat().st_uid!=os.getuid() or p.stat().st_mode & 0o077: raise ValueError('Private Deep Agents state required')
 shell=shell_allow_list(os.environ,cwd) if args[:1]==['-n'] else None
 if shell: args=['-S',shell,*args]
 exe='/opt/dsh/deepagents/bin/python'
 os.execve(exe,[exe,'-I','-m','deepagents_code',*args],environment(os.environ))
if __name__=='__main__':
 try:main()
 except (ValueError,OSError):
  print('Managed Deep Agents refused: check the project, operator policy and installed image.',file=sys.stderr);raise SystemExit(64)
