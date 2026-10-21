"""Inspect text, presentation XML and PDF text/metadata before public publication.

This check supplements review. It cannot prove that every image or string is safe.
Never print matching values. Supply additional private site terms through a local
newline-delimited file with --private-terms; that file must remain outside Git.
"""
from pathlib import Path
from zipfile import ZipFile
import argparse,json,re

RULES={
 'access-token':r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|kubeconfig-u-[A-Za-z0-9]+:',
 'private-key':r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
 'personal-path':r'[A-Za-z]:[/\\]Users[/\\](?!Public\b)[^/\\\s]+',
 'credential-url':r'://[^\s/:]+:[^\s/@]+@',
}
def scan(root,private_terms=()):
 findings=[]
 def check(name,text):
  for key,pattern in RULES.items():
   if re.search(pattern,text):findings.append({'path':name,'kind':key})
  lower=text.lower()
  if any(term.lower() in lower for term in private_terms if term.strip()):
   findings.append({'path':name,'kind':'private-site-term'})
 for f in root.rglob('*'):
  if not f.is_file() or any(p in {'.git','__pycache__','.pytest_cache','generated','private'} for p in f.relative_to(root).parts):continue
  name=str(f.relative_to(root))
  if f.suffix.lower() in {'.pptx','.docx','.xlsx'}:
   with ZipFile(f) as z:
    for n in z.namelist():
     if n.endswith(('.xml','.rels')):check(name+'!'+n,z.read(n).decode('utf-8',errors='replace'))
  elif f.suffix.lower()=='.pdf':
   from pypdf import PdfReader
   r=PdfReader(f);check(name+'!metadata',str(r.metadata));check(name+'!text','\n'.join(p.extract_text() or '' for p in r.pages))
  elif f.suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.webm','.mp4','.woff','.woff2'}:
   data=f.read_bytes()
   if b'\0' not in data[:8192]:check(name,data.decode('utf-8',errors='replace'))
 return findings
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path,nargs='?',default=Path.cwd());p.add_argument('--private-terms',type=Path);a=p.parse_args()
 terms=a.private_terms.read_text(encoding='utf-8').splitlines() if a.private_terms else []
 findings=scan(a.root,terms)
 print(json.dumps({'findings':findings,'finding_count':len(findings)},indent=2))
 raise SystemExit(bool(findings))
