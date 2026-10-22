import hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=json.loads((ROOT/'boot.json').read_text())
# The native loader pins this helper and the qualified installer before launch.
sys.path.insert(0,str(ROOT))
from install_live_client_layer import regular,install,BASE,private_directory

def main():
 private_directory(BASE)
 bundle_raw,_=regular(ROOT/'bundle.json')
 if hashlib.sha256(bundle_raw).hexdigest()!=spec['bundle_sha256']:raise ValueError('Bundle fingerprint differs')
 bundle=json.loads(bundle_raw)
 if not (BASE/'current').is_symlink()or os.readlink(BASE/'current')!=bundle['path']:raise ValueError('Activation pointer differs')
 for n,h in bundle['manifest']['files'].items():
  raw,_=regular(Path(bundle['path'])/n)
  if hashlib.sha256(raw).hexdigest()!=h:raise ValueError('Release fingerprint differs')
 profile=Path.home()/'.bashrc';raw,_=regular(profile)
 hashes={}
 for n,rule in bundle['manifest']['modules'].items():
  h=hashlib.sha256(Path(n).read_bytes()).hexdigest()
  if h not in rule['accepted']:raise ValueError('Unqualified installed module')
  hashes[n]=h
 n='/etc/kilo/kilo.json';h=hashlib.sha256(Path(n).read_bytes()).hexdigest()
 if h!=bundle['manifest']['base_policy_sha256']:raise ValueError('Unqualified installed policy')
 hashes[n]=h
 if bundle['bashrc_block'].encode()in raw:
  return {'activation':'already-present','profile_preserved':True}
 result=install({'bundle':bundle,'expected_bashrc_sha256':hashlib.sha256(raw).hexdigest(),'expected_system_hashes':hashes})
 return {'activation':'restored','profile_preserved':result['profile_prefix_preserved'],'recovery':result['recovery']}
if __name__=='__main__':
 try:result={'ok':True,**main()}
 except Exception as error:result={'ok':False,'error_type':type(error).__name__}
 result.update(pid=os.getpid(),boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),observed_ns=time.time_ns(),model_calls=0,pod=os.environ.get('HOSTNAME'),pid1_start=Path('/proc/1/stat').read_text().split()[21])
 # A bounded private receipt; never include profile text or credential values.
 target=BASE/'boot-status.json';temporary=BASE/('.boot-status-'+str(os.getpid()))
 try:
  fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'w')as f:json.dump(result,f);f.flush();os.fsync(f.fileno())
  os.replace(temporary,target)
 except OSError:pass
 print(json.dumps(result))
