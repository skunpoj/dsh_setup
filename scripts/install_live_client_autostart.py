import hashlib,json,os,re,stat,subprocess,sys,time
from pathlib import Path
from install_live_client_layer import BASE,regular,private_directory,exclusive

PROFILE=Path('/state/profiles/web/cordis.patch.yml')

def install(request):
 profile=PROFILE
 before,info=regular(profile)
 if hashlib.sha256(before).hexdigest()!=request['expected_profile_sha256']:raise ValueError('Profile changed before installation')
 if re.search(rb'!<|!!|!js',before):raise ValueError('Custom YAML tags require explicit review')
 package=request['package'];identity=package['identity']
 if not re.fullmatch('[a-f0-9]{16}',identity):raise ValueError('Invalid boot identity')
 private_directory(BASE);private_directory(BASE/'boot');root=BASE/'boot'/identity;private_directory(root)
 for n,content in package['files'].items():
  if not re.fullmatch('[A-Za-z0-9_.-]+',n):raise ValueError('Unexpected boot asset')
  p=root/n
  if not p.exists():exclusive(p,content.encode(),0o600)
  if regular(p)[0]!=content.encode():raise ValueError('Existing boot asset differs')
 entry={'id':'','insert':[{'id':'dsh-managed-client-autostart','name':root.as_uri()+'/startup.mjs','config':{'selfSha256':hashlib.sha256(package['files']['startup.mjs'].encode()).hexdigest()}}]}
 block=('\n# DSH MANAGED CLIENT AUTOSTART BEGIN\n- id: ""\n  insert: '+json.dumps([{'id':'dsh-managed-client-autostart','name':root.as_uri()+'/startup.mjs','config':{'selfSha256':hashlib.sha256(package['files']['startup.mjs'].encode()).hexdigest()}}])+'\n# DSH MANAGED CLIENT AUTOSTART END\n').encode()
 inspector="const fs=require('fs'),Y=require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']})),eq=require('util').isDeepStrictEqual,x=JSON.parse(fs.readFileSync(0,'utf8')),a=Y.parse(x.before);if(!Array.isArray(a))process.exit(77);const found=a.filter(e=>Array.isArray(e?.insert)&&e.insert.some(i=>i?.id==='dsh-managed-client-autostart'));if(found.length&&(found.length!==1||!eq(found[0],x.expected)))process.exit(78);console.log(JSON.stringify({registered:found.length===1}));"
 env={k:v for k,v in os.environ.items()if k!='NODE_OPTIONS'}
 probe=subprocess.run(['/usr/local/bin/node','-e',inspector],input=json.dumps({'before':before.decode(),'expected':entry}),text=True,capture_output=True,env=env,timeout=10)
 if probe.returncode:raise ValueError('Existing native registration differs or profile is invalid')
 if regular(profile)[0]!=before:raise ValueError('Concurrent profile edit')
 if json.loads(probe.stdout)['registered']:
  return {'already_registered':True,'profile_after_sha256':hashlib.sha256(before).hexdigest(),'path':str(root)}
 if b'DSH MANAGED CLIENT AUTOSTART BEGIN'in before:
  if before.count(block)!=1:raise ValueError('Unrecognized existing boot registration')
  return {'already_registered':True,'profile_after_sha256':hashlib.sha256(before).hexdigest(),'path':str(root)}
 if b'dsh-managed-client-autostart'in before:raise ValueError('Conflicting native plugin identity')
 after=before+block
 validator="const fs=require('fs');const Y=require(require.resolve('yaml',{paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh']}));const x=JSON.parse(fs.readFileSync(0,'utf8'));const a=Y.parse(x.before),b=Y.parse(x.after);if(!Array.isArray(a)||!Array.isArray(b)||b.length!==a.length+1||b.some(x=>typeof x.id!=='string'||['__proto__','constructor','prototype'].includes(x.id))||new Set(b.map(x=>x.id)).size!==b.length||JSON.stringify(a)!==JSON.stringify(b.slice(0,-1)))process.exit(77);console.log(JSON.stringify({preservedEntries:a.length}));"
 env={k:v for k,v in os.environ.items()if k!='NODE_OPTIONS'}
 check=subprocess.run(['/usr/local/bin/node','-e',validator],input=json.dumps({'before':before.decode(),'after':after.decode()}),text=True,capture_output=True,env=env,timeout=10)
 if check.returncode:raise ValueError('Native profile YAML validation refused')
 preserved=json.loads(check.stdout)['preservedEntries']
 private_directory(BASE/'boot-recovery');recovery=BASE/'boot-recovery'/str(time.time_ns());private_directory(recovery);exclusive(recovery/'profile.before',before,0o600)
 if regular(profile)[0]!=before:raise ValueError('Concurrent profile edit')
 fd=os.open(profile,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
 try:
  if os.fstat(fd).st_ino!=info.st_ino:raise ValueError('Profile inode changed')
  if os.write(fd,block)!=len(block):raise OSError('Incomplete registration')
  os.fsync(fd)
 finally:os.close(fd)
 if regular(profile)[0]!=after:raise ValueError('Profile readback differs; preserve recovery')
 receipt={'path':str(root),'profile':str(profile),'before_sha256':hashlib.sha256(before).hexdigest(),'profile_after_sha256':hashlib.sha256(after).hexdigest(),'profile_prefix_preserved':True,'preserved_native_entries':preserved,'recovery':str(recovery),'mode':stat.S_IMODE(info.st_mode),'processes_signalled':0}
 exclusive(recovery/'completed.json',json.dumps(receipt,indent=2).encode(),0o600)
 return receipt

def rollback(request):
 recovery=Path(request['recovery'])
 if recovery.parent!=BASE/'boot-recovery'or recovery.is_symlink():raise ValueError('Unexpected boot recovery')
 record=json.loads(regular(recovery/'completed.json')[0]);profile=Path(record['profile']);before=regular(recovery/'profile.before')[0];after,info=regular(profile)
 if hashlib.sha256(after).hexdigest()!=record['profile_after_sha256']or hashlib.sha256(before).hexdigest()!=record['before_sha256']:raise ValueError('Owner edit or recovery drift; refuse overwrite')
 tmp=profile.with_name('.cordis-autostart-restore-'+str(time.time_ns()));exclusive(tmp,before,record['mode'])
 if regular(profile)[0]!=after:raise ValueError('Concurrent edit during rollback')
 tmp.replace(profile)
 if regular(profile)[0]!=before:raise ValueError('Rollback readback differs')
 return {'native_profile_restored_exactly':True,'boot_assets_retained':True,'processes_signalled':0}
