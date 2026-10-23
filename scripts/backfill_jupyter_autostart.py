"""One-time, operator-owned backfill of missing managed Jupyter policies.

Never changes Internet entitlement or an existing Jupyter definition, including
Admin Stop. Does not signal, restart, adopt, or delete any application process.
"""
from pathlib import Path
import argparse,hashlib,json,os,re,secrets,stat,datetime
DEFAULT={'name':'jupyter','kind':'jupyter','cwd':'/workspace','argv':['jupyter','lab'],'port':8888,'enabled':True,'generation':1}
def digest(b):return hashlib.sha256(b).hexdigest()
def load(p):
 fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
 try:
  s=os.fstat(fd)
  if not stat.S_ISREG(s.st_mode)or s.st_nlink!=1 or s.st_size>16384:raise ValueError('Unsafe policy file')
  b=os.read(fd,16385)
  if len(b)>16384:raise ValueError('Policy too large')
  v=json.loads(b)
  if set(v)!={'allowed','services'}or type(v['allowed'])is not bool or not isinstance(v['services'],dict)or len(v['services'])>4:raise ValueError('Invalid policy shape')
  return b,v,s
 finally:os.close(fd)
def private_write(p,b):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 try:
  with os.fdopen(fd,'wb')as f:f.write(b);f.flush();os.fsync(f.fileno())
 except BaseException:
  p.unlink(missing_ok=True);raise

def fsync_dir(p):
 if hasattr(os,'O_DIRECTORY'):
  fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
def apply_plan(root,plan,backup,audit_file,apply=False):
 root=Path(root);backup=Path(backup);audit_file=Path(audit_file)
 if not root.is_absolute()or root.is_symlink()or not root.is_dir():raise ValueError('Use a real absolute control root')
 if not isinstance(plan,list)or not 1<=len(plan)<=64:raise ValueError('Bounded plan required')
 keys=set();pending=[];skipped=[]
 for row in plan:
  if set(row)!={'key','sha256'}or not re.fullmatch('[a-f0-9]{24}',row['key'])or not re.fullmatch('[a-f0-9]{64}',row['sha256'])or row['key']in keys:raise ValueError('Invalid or repeated plan key')
  key=row['key'];keys.add(key);folder=root/key
  if folder.is_symlink()or not folder.is_dir():raise ValueError('Unsafe policy directory')
  p=folder/'config.json';b,v,s=load(p)
  if 'jupyter'in v['services']:skipped.append(key);continue
  if digest(b)!=row['sha256']:raise ValueError('Policy changed; re-review before migration')
  if len(v['services'])>=4:raise ValueError('Managed service limit reached')
  desired=json.loads(b);desired['services']['jupyter']=dict(DEFAULT);after=json.dumps(desired,separators=(',',':')).encode()
  pending.append((key,p,b,after,s))
 result={'eligible':[x[0]for x in pending],'preservedExistingJupyter':skipped,'applied':[],'changesInternetEntitlement':False,'signalsProcesses':False}
 if not apply or not pending:return result
 if not backup.is_absolute()or backup.exists():raise ValueError('Use a new private backup directory')
 backup.mkdir(parents=True,mode=0o700);os.chmod(backup,0o700)
 # Open audit before changing any policy; never follow a substituted log link.
 afd=os.open(audit_file,os.O_WRONLY|os.O_APPEND|os.O_CREAT|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
 try:
  ast=os.fstat(afd)
  if not stat.S_ISREG(ast.st_mode)or ast.st_nlink!=1 or ast.st_size>5*1024*1024-65536:raise ValueError('Audit log needs operator review')
  def event(key,outcome):
   v={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'event':'application.lifecycle','user':'operator','environment':'internet','subject':key,'application':{'owner':key,'name':'jupyter','target':'main','mode':'on','action':'service-start','outcome':outcome},'maintenance':backup.name}
   os.write(afd,(json.dumps(v)+'\n').encode());os.fsync(afd)
  for key,p,b,after,oldstat in pending:
   current,_,s=load(p)
   if current!=b or (s.st_ino,s.st_mtime_ns)!=(oldstat.st_ino,oldstat.st_mtime_ns):raise ValueError('Policy changed; no overwrite')
   event(key,'requested');private_write(backup/(key+'.json'),b);temp=p.parent/('.jupyter-backfill-'+secrets.token_hex(12))
   try:
    private_write(temp,after)
    current,_,s=load(p)
    if current!=b or (s.st_ino,s.st_mtime_ns)!=(oldstat.st_ino,oldstat.st_mtime_ns):raise ValueError('Concurrent policy edit; no overwrite')
    os.replace(temp,p);fsync_dir(p.parent)
   finally:temp.unlink(missing_ok=True)
   got,_,_=load(p)
   if got!=after:raise ValueError('Policy readback changed; inspect without resetting active services')
   result['applied'].append({'key':key,'beforeSHA256':digest(b),'afterSHA256':digest(after)})
   event(key,'applied')
   manifest=backup/'result.json';tmp=backup/('.result-'+secrets.token_hex(8));private_write(tmp,json.dumps(result,indent=2).encode());os.replace(tmp,manifest);fsync_dir(backup)
 finally:os.close(afd)
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--backup',type=Path,required=True);p.add_argument('--audit-file',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();print(json.dumps(apply_plan(a.root,json.loads(a.plan.read_text()),a.backup,a.audit_file,a.apply)))
