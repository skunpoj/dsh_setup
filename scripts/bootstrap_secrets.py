"""Create fresh-install Secrets without printing or writing their values."""
import argparse
import base64
import getpass
import hashlib
import json
import secrets
import subprocess
from pathlib import Path
import yaml

def create(ns,name,values):
    # create, not apply: repeating this must not reset live passwords/keys.
    document={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':ns},'type':'Opaque',
              'data':{k:base64.b64encode(v.encode()).decode() for k,v in values.items()}}
    subprocess.run(['kubectl','create','-f','-'],input=json.dumps(document),text=True,check=True,stdout=subprocess.DEVNULL)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);a=p.parse_args()
    c=yaml.safe_load(a.config.read_text());ns=c['namespace']
    for name in ['platform-secrets','account-seed']:
        r=subprocess.run(['kubectl','get','secret',name,'-n',ns,'--ignore-not-found','-o','name'],capture_output=True,text=True,check=True)
        if r.stdout.strip():raise RuntimeError('Existing Secret; refuse credential reset: '+name)
    users={}
    for user in c['users']:
        password=getpass.getpass('Initial private password for '+user+': ')
        again=getpass.getpass('Confirm: ')
        if password!=again or password!=password.strip() or len(password)<12 or len(password.encode())>1024:raise ValueError('Passwords must match, have no leading/trailing whitespace and be 12+ characters')
        salt=secrets.token_bytes(16)
        users[user]={'scheme':'scrypt-v1','salt':salt.hex(),'hash':hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=1,dklen=32,maxmem=64*1024*1024).hex()}
        password=again=None
    db=secrets.token_hex(32)
    database_url='postgresql://' + 'gateway' + ':' + db + '@database:5432/gateway'
    create(ns,'platform-secrets',{'POSTGRES_PASSWORD':db,'DATABASE_URL':database_url,
         'LITELLM_MASTER_KEY':'sk-'+secrets.token_hex(32),'LITELLM_SALT_KEY':'sk-'+secrets.token_hex(32)})
    create(ns,'account-seed',{'users.json':json.dumps(users)})
    print('Fresh platform/account Secrets created. No values printed; no existing credentials changed.')

if __name__=='__main__':main()
