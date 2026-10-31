#!/usr/bin/env python3
"""Friendly aliases for the existing DSH CLI, using the fixed operator model patch."""
import os,sys,re
from pathlib import Path
TOKEN=Path('/harness-credentials/api-key')
def invocation(name,args):
 mode={'dsh-cli':'tui','dsh-run':'headless','dsh-sdk':'sdk'}.get(name)
 if mode is None:raise ValueError('Unknown managed CLI alias')
 if args in [['--help'],['--version']]:return mode,args
 if mode=='tui' and (not args or len(args)==2 and args[0]=='--resume' and re.fullmatch('[A-Za-z0-9_-]{1,128}',args[1])):return mode,args
 if mode=='headless' and len(args)==1 and 0<len(args[0])<=65536 and not args[0].startswith('-'):return mode,args
 if mode=='sdk' and not args:return mode,args
 raise ValueError('Configuration, provider, model and plugin overrides are not supported')
def main():
 mode,args=invocation(Path(sys.argv[0]).name,sys.argv[1:])
 if args not in [['--help'],['--version']] and not Path.cwd().resolve().is_relative_to(Path('/workspace').resolve()):raise ValueError('Use a private workspace project')
 e={k:os.environ[k] for k in ['TERM','COLORTERM','LANG','LC_ALL','DSH_ENVIRONMENT','KRB5CCNAME'] if k in os.environ}
 e.update({'HOME':'/home/dsh','DSH_HOME':'/state','PATH':'/usr/local/bin:/usr/bin:/bin','DEEPSEEK_API_KEY':TOKEN.read_text().strip(),'DSH_MANAGED_TRANSPORT':'1','NODE_OPTIONS':'--require /opt/dsh/scripts/managed_inference_transport.cjs','LANGSMITH_TRACING':'false','DO_NOT_TRACK':'1'})
 binary='/usr/local/bin/dsh'
 os.execve(binary,[binary,mode,'--patch','/opt/dsh/config/managed-llm.patch.yml',*args],e)
if __name__=='__main__':
 try:main()
 except (ValueError,OSError):print('Managed DSH CLI refused: use the assigned project and operator configuration.',file=sys.stderr);raise SystemExit(64)
