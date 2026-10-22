'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), crypto = require('node:crypto');
const {Directory, normalizeUsername, filterValue, CLIENT_SHA256} = require('../scripts/ldap_auth');
function fixture(t, changes = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-ldap-'));
  t.after(() => fs.rmSync(dir, {recursive:true, force:true}));
  fs.writeFileSync(path.join(dir,'ca.pem'), 'synthetic-test-ca');
  fs.writeFileSync(path.join(dir,'binder'), 'synthetic-binder-password');
  const config = {version:1, domain:'example.com', urls:['ldaps://directory.example.com:636'], bindDN:'binder@example.com',
    bindPasswordFile:path.join(dir,'binder'), caFile:path.join(dir,'ca.pem'), timeoutMs:1000,
    searchBases:['DC=example,DC=com'], searchFilter:'(sAMAccountName=%s)', allowSignUp:true, ...changes};
  const file = path.join(dir,'config.json'); fs.writeFileSync(file,JSON.stringify(config));
  return {config, file};
}
const entry = () => ({dn:'CN=Example User,DC=example,DC=com',sAMAccountName:'person',objectGUID:Buffer.alloc(16,7),userAccountControl:'512'});
function factory(calls, options = {}) {
  return settings => {
    const number=calls.length, row={settings,binds:[],searches:[],closed:false};calls.push(row);
    return {async bind(dn,password){row.binds.push({dn,password});if(options.bind)await options.bind(row,number);},
      async search(base,query){row.searches.push({base,query});return options.result || {searchEntries:[entry()],searchReferences:[]};},
      async unbind(){row.closed=true;}};
  };
}
test('canonical bare, UPN and domain usernames resolve to one account',()=>{
  for(const value of ['PERSON','person@example.com','EXAMPLE\\person'])assert.equal(normalizeUsername(value,'example.com'),'person');
  for(const value of ['person@other.example','OTHER\\person','person*)(x=y)','__proto__','a'])assert.throws(()=>normalizeUsername(value,'example.com'));
  assert.equal(filterValue('*()\\\0'),'\\2a\\28\\29\\5c\\00');
});
test('configuration requires verified LDAPS and refuses endpoint credentials',t=>{
  for(const changes of [{urls:['ldap://directory.example.com:389']},{urls:['ldaps://directory.example.com:389']},
    {urls:['ldaps:'+'/'.repeat(2)+'name:synthetic'+'@directory.example.com:636']},{urls:['ldaps://directory.example.com/path']},
    {rejectUnauthorized:false},{sslSkipVerify:true},{searchFilter:'%s'},{timeoutMs:0}]){
    assert.throws(()=>new Directory(fixture(t,changes).file));
  }
});
test('search bind then user bind use strict TLS and close the connection',async t=>{
  const f=fixture(t),calls=[];const directory=new Directory(f.file,{clientFactory:factory(calls)});
  assert.deepEqual(await directory.authenticate('PERSON@example.com',' user password '),{username:'person',subject:'07'.repeat(16)});
  const c=calls[0];assert.equal(c.settings.tlsOptions.rejectUnauthorized,true);assert.equal(c.settings.tlsOptions.minVersion,'TLSv1.2');
  assert.deepEqual(c.binds.map(x=>x.dn),['binder@example.com',entry().dn]);assert.equal(c.binds[1].password,' user password ');
  assert.equal(c.searches[0].query.filter,'(sAMAccountName=person)');assert.equal(c.closed,true);assert.equal(directory.pending,0);
});
test('empty or oversized passwords and filter injection make no directory calls',async t=>{
  const calls=[],d=new Directory(fixture(t).file,{clientFactory:factory(calls)});
  for(const [name,pw]of [['person',''],['person','x'.repeat(1025)],['*)(objectClass=*)','password']])await assert.rejects(d.authenticate(name,pw),{code:'INVALID_CREDENTIALS'});
  assert.equal(calls.length,0);
});
test('invalid user password does not fan out to another controller',async t=>{
  const calls=[],d=new Directory(fixture(t,{urls:['ldaps://one.example.com','ldaps://two.example.com']}).file,
    {clientFactory:factory(calls,{bind:async row=>{if(row.binds.length===2)throw Object.assign(Error(),{code:49});}})});
  await assert.rejects(d.authenticate('person','wrong'),{code:'INVALID_CREDENTIALS'});assert.equal(calls.length,1);assert.equal(calls[0].closed,true);
});
test('binder credential failure is unavailable, not a user-password fallback',async t=>{
  const calls=[],d=new Directory(fixture(t).file,{clientFactory:factory(calls,{bind:async()=>{throw Object.assign(Error(),{code:49});}})});
  await assert.rejects(d.authenticate('person','password'),{code:'LDAP_UNAVAILABLE'});assert.equal(calls[0].binds.length,1);
});
test('network failure can fail over only to configured verified LDAPS servers',async t=>{
  const calls=[],d=new Directory(fixture(t,{urls:['ldaps://one.example.com','ldaps://two.example.com']}).file,
    {clientFactory:factory(calls,{bind:async(row,number)=>{if(number===0)throw Error('connection failed');}})});
  assert.equal((await d.authenticate('person','password')).username,'person');assert.equal(calls.length,2);assert.ok(calls.every(x=>x.closed&&x.settings.tlsOptions.rejectUnauthorized));
});
test('missing, ambiguous, disabled or wrong canonical identity is refused before user bind',async t=>{
  for(const entries of [[],[entry(),entry()],[{...entry(),userAccountControl:'514'}],[{...entry(),sAMAccountName:'different'}],[{...entry(),objectGUID:'not-binary'}]]){
    const calls=[],d=new Directory(fixture(t).file,{clientFactory:factory(calls,{result:{searchEntries:entries}})});
    await assert.rejects(d.authenticate('person','password'),{code:'INVALID_CREDENTIALS'});assert.equal(calls[0].binds.length,1);assert.equal(calls[0].closed,true);
  }
});
test('search referrals never create a connection to an unconfigured host',async t=>{
  const calls=[],d=new Directory(fixture(t).file,{clientFactory:factory(calls,{result:{searchEntries:[entry()],searchReferences:['ldap://foreign.invalid']}})});
  await d.authenticate('person','password');assert.equal(calls.length,1);
});
test('bounded concurrent directory attempts reject excess work and drain',async t=>{
  let release;const gate=new Promise(resolve=>release=resolve),calls=[];
  const d=new Directory(fixture(t).file,{clientFactory:factory(calls,{bind:async row=>{if(row.binds.length===1)await gate;}})});
  const pending=Array.from({length:4},()=>d.authenticate('person','password'));await assert.rejects(d.authenticate('person','password'),{code:'LDAP_UNAVAILABLE'});
  release();await Promise.all(pending);assert.equal(d.pending,0);assert.equal(calls.length,4);
});
test('redistributed client matches the pinned upstream package bytes',()=>{
  const body=fs.readFileSync(path.join(__dirname,'../vendor/ldapts/ldapts.cjs'));assert.equal(crypto.createHash('sha256').update(body).digest('hex'),CLIENT_SHA256);
});
