"use strict";
const test = require("node:test"), assert = require("node:assert/strict"), fs = require("node:fs"), os = require("node:os"), path = require("node:path"), crypto = require("node:crypto"), https = require("node:https"), cp = require("node:child_process");
const { createNativeBridge } = require("./registry_native_bridge"), { createRuntime, readBounded } = require("./registry_runtime");
function removeSyntheticTemp(dir) {
 const root=fs.realpathSync(os.tmpdir()), actual=fs.realpathSync(dir);
 assert.equal(path.dirname(actual),root);assert.match(path.basename(actual),/^registry-(?:bound|tls-synthetic|machine-tls)-/);
 fs.rmSync(actual,{recursive:true,force:true});
}
const nativeRoot = process.env.DSH_NATIVE_SOURCE_ROOT;
function bridgeFixture() {
  const identity = require(path.join(nativeRoot,"identity_auth.js")), passwords = require(path.join(nativeRoot,"password_store.js"));
  const users = { alice: passwords.hashPassword("synthetic-test-only-123") };
  const bridge = createNativeBridge({ identity, passwords, readUsers: () => users, readGrants: () => ({ alice: { "synthetic/marker": ["pull"] } }), isAdmin: () => false, audit: () => true });
  return { bridge, users };
}
test("read-only bridge uses actual native password verifier and exact account stamp", {skip:!nativeRoot}, async () => {
  const {bridge,users}=bridgeFixture(); const before=JSON.stringify(users), s=bridge.snapshotAccount(" ALICE ");
  assert.equal(s.user,"alice");assert.equal(s.accountStamp,crypto.createHash("sha256").update(JSON.stringify([users.alice.scheme,users.alice.salt,users.alice.hash])).digest("hex"));
  assert.deepEqual(await bridge.authenticateIdentity("alice","synthetic-test-only-123","local",{create:false}),{user:"alice",authProvider:"local"});
  assert.equal(await bridge.authenticateIdentity("alice","wrong","local",{create:false}),null);assert.equal(JSON.stringify(users),before);
  users.alice.disabled=true;assert.equal(bridge.snapshotAccount("alice"),null);assert.equal(bridge.snapshotAccount("constructor"),null);
});
test("native bridge grants reload and provider/account revocation are reflected", {skip:!nativeRoot}, () => {
  const {bridge,users}=bridgeFixture();const a=bridge.snapshotAccount("alice");users.alice.hash="0".repeat(64);assert.notEqual(bridge.snapshotAccount("alice").accountStamp,a.accountStamp);
  assert.equal(bridge.snapshotAccount("alice@untrusted.invalid"),null);assert.equal(bridge.snapshotAccount("unavailable"),null);
  assert.deepEqual(bridge.loadGrants(),{alice:{"synthetic/marker":["pull"]}});
});
test("bounded protected-file reader refuses relative/oversize files", () => {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"registry-bound-"));try{const f=path.join(dir,"fixture");fs.writeFileSync(f,"12345");assert.throws(()=>readBounded("relative",10));assert.throws(()=>readBounded(f,4));assert.equal(readBounded(f,5).toString(),"12345");}finally{removeSyntheticTemp(dir);}
});
test("standalone TLS runtime actually authenticates synthetic existing DSH account and refuses revoked account", {skip:!nativeRoot}, async () => {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"registry-tls-synthetic-"));let server;
  try {
    const key=path.join(dir,"key.pem"),cert=path.join(dir,"cert.pem");
    const openssl=process.env.DSH_TEST_OPENSSL;assert.ok(openssl,"Explicit test-only OpenSSL path required");
    const c=cp.spawnSync(openssl,["req","-x509","-newkey","rsa:2048","-nodes","-days","1","-subj","/CN=localhost","-addext","subjectAltName=IP:127.0.0.1","-keyout",key,"-out",cert],{timeout:15000,stdio:"ignore"});assert.equal(c.status,0);
    const passwords=require(path.join(nativeRoot,"password_store.js")), userPath=path.join(dir,"users.json"),grantsPath=path.join(dir,"grants.json"),machinePrincipalsPath=path.join(dir,"machines.json");fs.writeFileSync(machinePrincipalsPath,"{}");
    const users={alice:passwords.hashPassword("synthetic-test-only-123")};fs.writeFileSync(userPath,JSON.stringify(users));fs.writeFileSync(grantsPath,JSON.stringify({alice:{"synthetic/marker":["pull"]}}));
    const original=fs.readFileSync(userPath), nativeSourceHashes={};for(const n of["identity_auth.js","password_store.js","ldap_auth.js"])nativeSourceHashes[n]=crypto.createHash("sha256").update(fs.readFileSync(path.join(nativeRoot,n))).digest("hex");
    const cfg={version:1,mode:"native-and-machine",adminUsers:[],nativeSourceRoot:nativeRoot,nativeSourceHashes,userStorePath:userPath,grantsPath,machinePrincipalsPath,signingKeyPath:key,tlsKeyPath:key,tlsCertPath:cert,issuer:"token.synthetic.invalid",service:"registry.synthetic.invalid",allowedPeers:["127.0.0.1"]};
    assert.throws(()=>createRuntime({...cfg,nativeSourceHashes:{...nativeSourceHashes,"identity_auth.js":"0".repeat(64)}}));
    server=createRuntime(cfg);await new Promise(r=>server.listen(0,"127.0.0.1",r));const port=server.address().port;
    const req=(password="synthetic-test-only-123",scope="repository:synthetic/marker:pull,push")=>new Promise((resolve,reject)=>{
      const q=https.request({host:"127.0.0.1",port,ca:fs.readFileSync(cert),rejectUnauthorized:true,path:"/api/registry/token?service=registry.synthetic.invalid&scope="+encodeURIComponent(scope),headers:{Authorization:"Basic "+Buffer.from("alice:"+password).toString("base64")}},res=>{let b="";res.on("data",v=>{b+=v;assert.ok(b.length<16384);});res.on("end",()=>resolve({status:res.statusCode,body:JSON.parse(b)}));});q.setTimeout(5000,()=>q.destroy(Error("timeout")));q.on("error",reject);q.end();});
    const good=await req();assert.equal(good.status,200);const claims=JSON.parse(Buffer.from(good.body.token.split(".")[1],"base64url"));assert.deepEqual(claims.access,[{type:"repository",name:"synthetic/marker",actions:["pull"]}]);
    assert.equal((await req("wrong")).status,401);assert.equal((await req("synthetic-test-only-123","registry:catalog:*")).status,400);assert.deepEqual(fs.readFileSync(userPath),original);
    users.alice.disabled=true;fs.writeFileSync(userPath,JSON.stringify(users));assert.equal((await req()).status,401);
  } finally { if(server)await new Promise(r=>server.close(r));removeSyntheticTemp(dir); }
});

test("machine-only HTTPS listener needs no native source/store and never falls back to human auth", async () => {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),"registry-machine-tls-"));let server;
 try {
  const key=path.join(dir,"key.pem"),cert=path.join(dir,"cert.pem"),mp=path.join(dir,"machines.json"),password="synthetic-"+"m".repeat(64),id="robot~smp-test-pull";
  const c=cp.spawnSync(process.env.DSH_TEST_OPENSSL,["req","-x509","-newkey","rsa:2048","-nodes","-days","1","-subj","/CN=localhost","-addext","subjectAltName=IP:127.0.0.1","-keyout",key,"-out",cert],{timeout:15000,stdio:"ignore"});assert.equal(c.status,0);
  const records={[id]:{enabled:true,rotationStamp:"1".repeat(32),secretSha256:crypto.createHash("sha256").update(password).digest("hex"),grants:{"smp/pipeline":["pull"]}}};fs.writeFileSync(mp,JSON.stringify(records));
  server=createRuntime({version:1,mode:"machine-only",machinePrincipalsPath:mp,signingKeyPath:key,tlsKeyPath:key,tlsCertPath:cert,issuer:"token.synthetic.invalid",service:"registry.synthetic.invalid",allowedPeers:["127.0.0.1"]});await new Promise(r=>server.listen(0,"127.0.0.1",r));
  async function request(username){return new Promise((resolve,reject)=>{const q=https.request({host:"127.0.0.1",port:server.address().port,ca:fs.readFileSync(cert),rejectUnauthorized:true,path:"/api/registry/token?service=registry.synthetic.invalid&scope=repository:smp/pipeline:pull,push",headers:{Authorization:"Basic "+Buffer.from(username+":"+password).toString("base64")}},r=>{let b="";r.on("data",x=>b+=x);r.on("end",()=>resolve({status:r.statusCode,body:JSON.parse(b)}));});q.setTimeout(5000,()=>q.destroy(Error("timeout")));q.on("error",reject);q.end();});}
  const r=await request(id);assert.equal(r.status,200);assert.deepEqual(JSON.parse(Buffer.from(r.body.token.split(".")[1],"base64url")).access,[{type:"repository",name:"smp/pipeline",actions:["pull"]}]);assert.equal((await request("admin")).status,401);records[id].enabled=false;fs.writeFileSync(mp,JSON.stringify(records));assert.equal((await request(id)).status,401);
 } finally {if(server)await new Promise(r=>server.close(r));removeSyntheticTemp(dir);}
});
