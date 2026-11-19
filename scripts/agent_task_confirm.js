'use strict';
// Gateway-side signing of chat-delegation confirmations (option C).
// The browser asks the gateway to confirm a proposed task the person has read; the gateway signs a short-lived receipt
// with an Ed25519 key that exists only in the gateway pod. The workspace broker holds the PUBLIC key and refuses any
// confirmation it cannot verify, so a process inside the workspace (the chat shell, an agent) cannot approve its own task.
const fs=require('fs'),crypto=require('crypto');
const KEY_FILE=()=>process.env.DSH_AGENT_CONFIRM_KEY_FILE||'/etc/dsh-confirm/confirm-receipt-private.pem';
const RECEIPT_TTL_SECONDS=90;                                   // broker accepts exp in [now, now+120]
const FIELDS=['taskId','runtime','project','writes','backend','promptSha256','subject','origin','expiresAt','exp','nonce'];
let cached=null;

// Fail closed: a missing, unreadable, wrongly typed or group/other-readable key means no confirmation can be signed.
function loadKey(file=KEY_FILE()){
 try{
  // A Kubernetes Secret volume exposes each file as a symlink into its ..data directory, so the RESOLVED file is checked:
  // it must be a regular file and (on Linux) not readable by others and not writable by group: defaultMode 0400, or 0440 with an fsGroup when the gateway is not root.
  const info=fs.statSync(file);
  if(!info.isFile())return null;
  if(process.platform!=='win32'&&(info.mode&0o027)!==0)return null;   // 0400 or 0440 (fsGroup); never writable by group, never readable by others
  if(cached&&cached.file===file&&cached.mtimeMs===info.mtimeMs)return cached.key;
  const key=crypto.createPrivateKey(fs.readFileSync(file));
  if(key.asymmetricKeyType!=='ed25519')return null;
  cached={file,mtimeMs:info.mtimeMs,key};return key;
 }catch{return null;}
}
const available=file=>loadKey(file)!==null;

// Sorted keys, no spaces, ASCII only (every code point above 0x7e as \uXXXX), identical to Python's
// json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=True) for the fields used here.
const sorted=v=>Array.isArray(v)?v.map(sorted):(v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,sorted(v[k])])):v);
function canonical(value){
 const text=JSON.stringify(sorted(value));
 return text.replace(/[\u007f-￿]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
}
const sha256Hex=text=>crypto.createHash('sha256').update(String(text),'utf8').digest('hex');

// Builds and signs the receipt for exactly the proposal the person was shown. `shown` is what the browser displayed:
// the gateway re-reads the proposal from the broker and refuses if the prompt, its hash or the flags differ.
function buildReceipt(proposal,subject,shown,now=Date.now(),key=loadKey()){
 if(!key)return {error:'CONFIRMATION_KEY_UNAVAILABLE',status:503};
 if(!proposal||proposal.state!=='proposed'||typeof proposal.prompt!=='string')return {error:'PROPOSAL_NOT_PENDING',status:409};
 const hash=sha256Hex(proposal.prompt);
 if(hash!==proposal.promptSha256)return {error:'PROPOSAL_HASH_MISMATCH',status:409};
 if(!shown||shown.promptSha256!==hash)return {error:'PROPOSAL_CHANGED',status:409};
 if(typeof subject!=='string'||!subject)return {error:'SUBJECT_REQUIRED',status:400};
 const seconds=Math.floor(now/1000);
 if(!Number.isInteger(proposal.expiresAt)||proposal.expiresAt<=seconds)return {error:'PROPOSAL_EXPIRED',status:410};
 const receipt={taskId:proposal.id,runtime:proposal.runtime,project:proposal.project,writes:proposal.writes,backend:proposal.backend,
  promptSha256:hash,subject,origin:proposal.origin,expiresAt:proposal.expiresAt,exp:seconds+RECEIPT_TTL_SECONDS,
  nonce:crypto.randomBytes(18).toString('base64url')};
 receipt.sig=crypto.sign(null,Buffer.from(canonical(receipt),'utf8'),key).toString('base64');
 return {receipt};
}
function verify(receipt,publicKey){
 const {sig,...rest}=receipt;
 return crypto.verify(null,Buffer.from(canonical(rest),'utf8'),publicKey,Buffer.from(sig,'base64'));
}

// Operator tooling (never used by the gateway at run time). The private key is generated here and leaves only on stdout, to be piped straight into
// `kubectl create -f -`: it is never written to a file and never appears in a command line. `create` (not `apply`) so that no last-applied annotation copies it.
const SECRET_NAME='dsh-confirm-signing-key',SECRET_KEY='confirm-receipt-private.pem';
function secretManifest(name=SECRET_NAME,namespace='llm'){
 const pem=crypto.generateKeyPairSync('ed25519').privateKey.export({type:'pkcs8',format:'pem'});
 return {apiVersion:'v1',kind:'Secret',metadata:{name,namespace,labels:{'app.kubernetes.io/managed-by':'dsh-orchestrator','dsh.example/purpose':'agent-task-confirmation'}},type:'Opaque',stringData:{[SECRET_KEY]:pem}};
}
// The PUBLIC half, derived from the key the gateway actually loaded: this is what is committed as config/confirm-receipt-public.pem.
const publicPem=key=>crypto.createPublicKey(key).export({type:'spki',format:'pem'});
function cli(argv,out=process.stdout,err=process.stderr){
 if(argv.includes('--secret-manifest')){out.write(JSON.stringify(secretManifest())+'\n');return 0;}
 if(argv.includes('--public-pem')){
  const key=loadKey();
  if(!key){err.write('CONFIRMATION_KEY_UNAVAILABLE: no usable Ed25519 key at '+KEY_FILE()+'\n');return 3;}
  out.write(publicPem(key));return 0;
 }
 err.write('usage: node agent_task_confirm.js --secret-manifest | kubectl -n llm create -f -\n       node agent_task_confirm.js --public-pem    (inside the gateway pod: prints the public key only)\n');return 2;
}
if(require.main===module)process.exitCode=cli(process.argv.slice(2));
module.exports={loadKey,available,canonical,sha256Hex,buildReceipt,verify,FIELDS,RECEIPT_TTL_SECONDS,secretManifest,publicPem,cli,SECRET_NAME,SECRET_KEY};
