"""Fail a public export on common secret, personal-path or private-host values.

This deterministic check supplements source review; it cannot prove the absence
of every possible secret. Never print matching values.
"""
import argparse
from pathlib import Path
import re

PATTERNS={
 'access-token':r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|sk-[a-f0-9]{40,}|kubeconfig-u-[A-Za-z0-9]+:',
 'private-key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
 'personal-path':r'[A-Za-z]:[/\\]Users[/\\](?!Public\b)[^/\\\s]+|/home/(?!developer\b|dsh\b)[A-Za-z0-9_.-]+/',
 'credential-in-url':r'://[^\s/:]+:[^\s/@]+@',
}

def scan(root):
 findings=[]
 for p in root.rglob('*'):
  if not p.is_file() or any(x in {'.git','__pycache__','generated','private'} for x in p.relative_to(root).parts):continue
  data=p.read_bytes()
  if b'\0' in data:continue
  text=data.decode('utf-8',errors='replace')
  for kind,pattern in PATTERNS.items():
   if re.search(pattern,text):findings.append((str(p.relative_to(root)),kind))
 return findings

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path,nargs='?',default=Path.cwd());a=p.parse_args();findings=scan(a.root)
 for name,kind in findings:print(name+': '+kind)
 if findings:raise SystemExit(1)
 print('Public-source pattern scan passed (not an absolute secrecy guarantee).')
