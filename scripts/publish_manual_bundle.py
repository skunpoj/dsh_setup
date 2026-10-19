"""Publish a verified documentation-only bundle; does not restart workloads."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

REMOTE = r'''
import sys,tarfile,json,hashlib,pathlib,re,uuid,shutil,os
root=pathlib.Path('/auth/manuals');root.mkdir(exist_ok=True,mode=0o700)
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|') as archive:
 members=iter(archive);first=next(members);assert first.name=='manifest.json' and first.isfile() and first.size<1024*1024
 content=archive.extractfile(first).read();manifest=json.loads(content);files=manifest['files']
 digest=hashlib.sha256(content).hexdigest()[:16];target=root/digest
 assert len(files)<=256 and manifest['bytes']<=128*1024*1024
 stage=root/('.incoming-'+uuid.uuid4().hex);stage.mkdir(mode=0o700);seen=set()
 try:
  for member in members:
   name=member.name
   assert member.isfile() and name in files and name not in seen
   assert re.fullmatch(r'[a-zA-Z0-9_./-]+\.(html|md|json|png|svg)',name)
   assert all(p not in ('','.','..') for p in name.split('/'))
   entry=files[name];assert member.size==entry['bytes'] and member.size<=8*1024*1024
   data=archive.extractfile(member).read();assert hashlib.sha256(data).hexdigest()==entry['sha256']
   path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);seen.add(name)
  assert seen==set(files)
  (stage/'manifest.json').write_bytes(content)
  if target.exists():
   assert (target/'manifest.json').read_bytes()==content
   for name,e in files.items():assert hashlib.sha256((target/name).read_bytes()).hexdigest()==e['sha256']
   shutil.rmtree(stage)
  else:os.rename(stage,target)
 except BaseException:
  shutil.rmtree(stage);raise
print(json.dumps({'manualDir':str(target),'files':len(files),'bytes':manifest['bytes'],'allFileHashesVerified':True}))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--kubectl',default='kubectl')
    parser.add_argument('--namespace',default='llm')
    parser.add_argument('--deployment',default='dsh-environment-gateway')
    args=parser.parse_args()
    content=(args.bundle/'manifest.json').read_bytes()
    manifest=json.loads(content)
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode='w') as archive:
        for name in ['manifest.json',*manifest['files']]:
            source=(args.bundle/name).resolve()
            if not source.is_relative_to(args.bundle.resolve()):
                raise ValueError('Unscoped bundle file')
            data=source.read_bytes()
            if name!='manifest.json' and hashlib.sha256(data).hexdigest()!=manifest['files'][name]['sha256']:
                raise ValueError('Local manual integrity mismatch')
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
            archive.addfile(info,io.BytesIO(data))
    result=subprocess.run([args.kubectl,'--request-timeout=120s','-n',args.namespace,'exec','-i',
                           'deploy/'+args.deployment,'--','python3','-c',REMOTE],input=buffer.getvalue(),capture_output=True,timeout=140)
    if result.returncode:
        raise RuntimeError(result.stderr.decode()[-500:])
    print(result.stdout.decode().strip())


if __name__=='__main__':
    main()
