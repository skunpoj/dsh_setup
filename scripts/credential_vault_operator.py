"""Explicit operator recovery. No root/unseal material is printed or mounted in workers."""
import argparse,base64,hashlib,json,os,secrets,subprocess,time
from pathlib import Path
from deploy_credential_vault import protect

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['status','unseal','snapshot-restore-test']);p.add_argument('--custody',required=True);p.add_argument('--namespace',default='llm');p.add_argument('--output');a=p.parse_args()
 operator=json.loads(protect(Path(a.custody).read_bytes(),decrypt=True));ns=a.namespace
 def k(*args,body=None,allow_sealed=False):
  r=subprocess.run(['kubectl','-n',ns,*args],input=body,capture_output=True,timeout=180,env=dict(os.environ,KUBECTL_REMOTE_COMMAND_WEBSOCKETS='false',GODEBUG='http2client=0'))
  if r.returncode and not(allow_sealed and r.returncode==2):raise RuntimeError('Recovery operation failed: '+r.stderr.decode('utf-8',errors='replace')[:200])
  return r.stdout
 def cli(target,args,payload=None,root=False,allow_sealed=False):
  if root:
   return k('exec','-i','deployment/'+target,'--','sh','-c','read -r BAO_TOKEN; export BAO_TOKEN; exec bao "$@"','sh',*args,body=(operator['root_token']+'\n').encode()+(json.dumps(payload).encode() if payload is not None else b''),allow_sealed=allow_sealed)
  return k('exec','-i','deployment/'+target,'--','bao',*args,body=json.dumps(payload).encode() if payload is not None else None,allow_sealed=allow_sealed)
 target='dsh-credential-vault'
 if a.action=='status':
  state=json.loads(cli(target,['status','-format=json'],allow_sealed=True));print(json.dumps({k:state.get(k) for k in ['initialized','sealed','storage_type','version']}));return
 if a.action=='unseal':
  cli(target,['write','-format=json','sys/unseal','-'],{'key':operator['unseal_keys_b64'][0]})
  state=json.loads(cli(target,['status','-format=json'],allow_sealed=True));assert state['sealed'] is False
  print(json.dumps({'sealed':False}));return
 if not a.output:raise ValueError('Use a private output directory for the encrypted snapshot')
 output=Path(a.output).resolve();output.mkdir(exist_ok=True,parents=True)
 canary=secrets.token_hex(32);canary_path='recovery-acceptance-'+secrets.token_hex(4)
 cli(target,['write','-format=json','dsh-off/data/'+canary_path,'-'],{'options':{'cas':0},'data':{'marker':canary}},root=True)
 cli(target,['operator','raft','snapshot','save','/tmp/credential-recovery.snap'],root=True)
 snapshot=base64.b64decode(k('exec','deployment/'+target,'--','base64','/tmp/credential-recovery.snap'));backup=output/'credential-vault-encrypted.snap';backup.write_bytes(snapshot)
 subprocess.run(['icacls',str(backup),'/inheritance:r','/grant:r',os.environ['USERNAME']+':F'],capture_output=True,check=True)
 # An isolated clone with a NEW PVC. It has no network access to the production vault.
 clone='dsh-credential-restore-test';volume=clone+'-data'
 def apply(obj):k('apply','--server-side','--field-manager=dsh-credential-rollout','-f','-',body=json.dumps(obj).encode())
 live=json.loads(k('get','deployment',target,'-o','json'));template=live['spec']['template'];template['metadata']={'labels':{'app':clone}}
 for v in template['spec']['volumes']:
  if v['name']=='data':v['persistentVolumeClaim']['claimName']=volume
 assert all(v.get('persistentVolumeClaim',{}).get('claimName')!='dsh-credential-vault-data' for v in template['spec']['volumes'])
 apply({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':volume},'spec':{'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'1Gi'}}}})
 apply({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':clone},'spec':{'podSelector':{'matchLabels':{'app':clone}},'policyTypes':['Ingress','Egress'],'ingress':[],'egress':[]}})
 apply({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':clone},'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':{'app':clone}},'template':template}})
 restored=False
 try:
  k('rollout','status','deployment/'+clone,'--timeout=120s');time.sleep(3)
  temporary=json.loads(cli(clone,['operator','init','-key-shares=1','-key-threshold=1','-format=json']))
  cli(clone,['write','-format=json','sys/unseal','-'],{'key':temporary['unseal_keys_b64'][0]})
  # Windows exec streaming can acknowledge an empty upload. Transfer bounded encrypted
  # snapshot chunks (not plaintext credentials) and require the reconstructed hash.
  encoded=base64.b64encode(snapshot).decode('ascii')
  k('exec','deployment/'+clone,'--','sh','-c',': > /tmp/credential-recovery.b64')
  for start in range(0,len(encoded),4096):
   k('exec','deployment/'+clone,'--','sh','-c','printf %s "$1" >> /tmp/credential-recovery.b64','sh',encoded[start:start+4096])
  k('exec','deployment/'+clone,'--','sh','-c','base64 -d /tmp/credential-recovery.b64 > /tmp/credential-recovery.snap')
  uploaded=k('exec','deployment/'+clone,'--','sha256sum','/tmp/credential-recovery.snap').decode().split()[0]
  assert uploaded==hashlib.sha256(snapshot).hexdigest(),'Snapshot transport hash mismatch'
  # Restore authorization uses the temporary clone root, never its material in Git.
  original=operator['root_token'];operator['root_token']=temporary['root_token']
  try:cli(clone,['operator','raft','snapshot','restore','-force','/tmp/credential-recovery.snap'],root=True)
  finally:operator['root_token']=original
  time.sleep(3)
  state=json.loads(cli(clone,['status','-format=json'],allow_sealed=True))
  if state['sealed']:cli(clone,['write','-format=json','sys/unseal','-'],{'key':operator['unseal_keys_b64'][0]})
  check=json.loads(cli(clone,['read','-format=json','dsh-off/data/'+canary_path],root=True))
  assert check['data']['data']['marker']==canary;restored=True
 finally:
  k('delete','deployment',clone,'--wait=true');k('delete','pvc',volume,'--wait=true');k('delete','networkpolicy',clone)
  cli(target,['kv','metadata','delete','dsh-off/'+canary_path],root=True)
 print(json.dumps({'encryptedSnapshotSaved':True,'snapshotSHA256':hashlib.sha256(snapshot).hexdigest(),'bytes':len(snapshot),'isolatedRestoreVerified':restored,'cloneResourcesRemoved':True,'productionVaultReinitialized':False}))

if __name__=='__main__':main()
