"""Explicit maintenance acceptance, using disposable identities only. Not an automatic CI test."""
import argparse,json,subprocess,sys
from pathlib import Path

NODE=r'''const http=require('http'),fs=require('fs'),crypto=require('crypto');const config=CONFIG;
async function request(route,method='GET',body,cookie){return await new Promise((resolve,reject)=>{let payload=body?Buffer.from(body):null;const q=http.request({host:'127.0.0.1',port:3080,path:route,method,headers:{Host:config.host,...(cookie?{Cookie:cookie}:{}),...(payload?{'Content-Type':'application/x-www-form-urlencoded','Content-Length':payload.length,Origin:'https://'+config.host}:{})}},s=>{let text='';s.on('data',b=>text+=b);s.on('end',()=>resolve({status:s.statusCode,headers:s.headers,text}));});q.setTimeout(20000,()=>q.destroy());q.on('error',reject);q.end(payload);});}
async function main(){let cookie=config.cookie;if(!cookie){const login=await request('/login','POST',new URLSearchParams({username:'cred-qa-a',password:config.passwords['cred-qa-a'],internet:'off',auth_provider:'local'}).toString());cookie=login.headers['set-cookie'].find(x=>x.startsWith('dsh_credential_canary=')).split(';')[0];}const state=await request('/api/user-credentials','GET',undefined,cookie);const loginPage=await request('/login');let metadataHash=null;if(state.status===200){const d=JSON.parse(state.text);if(!d.credentials.some(c=>c.id==='persistence-canary'))throw Error('Persistence fixture missing');metadataHash=crypto.createHash('sha256').update(JSON.stringify(d.credentials)).digest('hex');}console.log(JSON.stringify({cookie,status:state.status,loginStatus:loginPage.status,metadataHash,accountStoreHash:crypto.createHash('sha256').update(fs.readFileSync('/auth/users.json')).digest('hex')}));}main().catch(()=>{console.error('Restart acceptance failed');process.exitCode=1;});'''

def main():
 p=argparse.ArgumentParser();p.add_argument('--fixture',required=True);p.add_argument('--custody',required=True);p.add_argument('--receipt',required=True);a=p.parse_args();cfg=json.loads(Path(a.fixture).read_text(encoding='utf-8'))
 def call():
  r=subprocess.run(['kubectl','-n','llm','exec','-i','deployment/dsh-credential-canary','--','node','-'],input=NODE.replace('CONFIG',json.dumps(cfg)).encode(),capture_output=True,timeout=60)
  if r.returncode:raise RuntimeError('Canary restart request failed')
  return json.loads(r.stdout)
 def kube(*args):subprocess.run(['kubectl','-n','llm',*args],capture_output=True,check=True,timeout=150)
 before=call();assert before['status']==200;cfg['cookie']=before['cookie']
 kube('rollout','restart','deployment/dsh-credential-vault');kube('rollout','status','deployment/dsh-credential-vault','--timeout=120s')
 sealed=call();assert sealed['status']==503 and sealed['loginStatus']==200
 subprocess.run([sys.executable,'scripts/credential_vault_operator.py','unseal','--custody',a.custody],capture_output=True,check=True,timeout=60)
 after_vault=call();assert after_vault['status']==200 and before['metadataHash']==after_vault['metadataHash']
 kube('rollout','restart','deployment/dsh-credential-canary');kube('rollout','status','deployment/dsh-credential-canary','--timeout=120s')
 after_gateway=call();assert after_gateway['status']==200 and before['metadataHash']==after_gateway['metadataHash'] and before['accountStoreHash']==after_gateway['accountStoreHash']
 result={'vaultRestartSeals':True,'sealedVaultDeniesCredentialUse':True,'loginContinuesDuringVaultSeal':True,'externalCustodyUnsealVerified':True,'credentialMetadataSurvivesVaultRestart':True,'existingCanarySessionSurvivesGatewayReplacement':True,'credentialOwnershipAndAccountStorePreserved':True,'realProviderCredentialsUsed':False}
 Path(a.receipt).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':main()
