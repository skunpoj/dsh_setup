'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createAuthenticator} = require('../scripts/identity_auth');
const {DirectoryError} = require('../scripts/ldap_auth');
function fixture(initial = {}, options = {}) {
  let users=structuredClone(initial),saves=0,created=0,binds=0;const audit=[];let provisionPassword;
  const directory={config:{allowSignUp:true},async authenticate(){binds++;if(options.directory) return options.directory();return {username:'person',subject:'ab'.repeat(16)};}};
  const authenticate=createAuthenticator({directory:options.disabled?null:directory,loadUsers:()=>structuredClone(users),saveUsers:value=>{users=structuredClone(value);saves++;return true;},
    verifyPassword:async(pw,record)=>record?.hash===pw,newAccountRecord:(_all,_name,pw)=>{created++;provisionPassword=pw;return options.capacityError||{record:{scheme:'synthetic',hash:'random-placeholder',internetAllowed:true,runtimeSlot:'private-spare'}};},
    isAdmin:name=>name==='admin',audit:(event,user)=>{audit.push({event,user});return options.auditFailure!==true;}});
  return {authenticate,directory,audit,get users(){return users;},set users(v){users=v;},get saves(){return saves;},get created(){return created;},get binds(){return binds;},get provisionPassword(){return provisionPassword;}};
}
test('existing local collision is denied without creating or changing any account',async()=>{
  for(const name of ['person','PERSON']){
    const f=fixture({[name]:{hash:'local-password',runtimeSlot:'original'}}),before=JSON.stringify(f.users);
    await assert.rejects(f.authenticate('person','AD-password','ldap'),e=>e.code==='LDAP_LOCAL_ACCOUNT_CONFLICT'&&e.status===409&&e.message.includes('administrator to delete'));
    assert.equal(JSON.stringify(f.users),before);assert.equal(f.saves,0);assert.equal(f.created,0);assert.equal(f.audit.length,1);
  }
});
test('local sign-in remains available and never queries the directory',async()=>{
  const f=fixture({person:{hash:'local-password'}});assert.deepEqual(await f.authenticate('PERSON','local-password','local'),{user:'person',authProvider:'local'});assert.equal(f.binds,0);
});
test('LDAP never falls back to a matching local password',async()=>{
  const f=fixture({person:{hash:'local-password'}},{directory:async()=>{throw new DirectoryError('INVALID_CREDENTIALS',401,'Denied');}});
  await assert.rejects(f.authenticate('person','local-password','ldap'),{code:'INVALID_CREDENTIALS'});assert.equal(f.saves,0);
});
test('AD account creation uses the ordinary private slot and denies Internet by default',async()=>{
  const f=fixture();assert.deepEqual(await f.authenticate('person','AD-password','ldap'),{user:'person',authProvider:'ldap'});
  assert.equal(f.users.person.runtimeSlot,'private-spare');assert.equal(f.users.person.internetAllowed,false);assert.equal(f.users.person.authProvider,'ldap');assert.equal(f.users.person.ldapSubject,'ab'.repeat(16));
  assert.notEqual(f.provisionPassword,'AD-password');assert.ok(!JSON.stringify(f.users).includes('AD-password'));assert.equal(f.saves,1);
});
test('a directory subject change or disabled account cannot acquire an existing workspace',async()=>{
  for(const record of [{authProvider:'ldap',ldapSubject:'cd'.repeat(16)},{authProvider:'ldap',ldapSubject:'ab'.repeat(16),disabled:true}]){
    const f=fixture({person:record});assert.equal(await f.authenticate('person','AD-password','ldap'),null);assert.equal(f.saves,0);
  }
});
test('an existing approved LDAP account retains its Internet setting and private slot',async()=>{
  const original={authProvider:'ldap',ldapSubject:'ab'.repeat(16),internetAllowed:true,runtimeSlot:'kept'};const f=fixture({person:original});
  assert.ok(await f.authenticate('person','AD-password','ldap'));assert.deepEqual(f.users.person,original);assert.equal(f.saves,0);
});
test('LDAP accounts cannot use the local password placeholder',async()=>{
  const f=fixture({person:{hash:'placeholder',authProvider:'ldap',ldapSubject:'ab'.repeat(16)}});assert.equal(await f.authenticate('person','placeholder','local'),null);assert.equal(f.binds,0);
});
test('a local account created while the bind is in flight is not overwritten',async()=>{
  let release;const gate=new Promise(resolve=>release=resolve);const f=fixture({}, {directory:async()=>{await gate;return {username:'person',subject:'ab'.repeat(16)};}});
  const work=f.authenticate('person','AD-password','ldap');f.users={person:{hash:'new-local',runtimeSlot:'keep'}};release();
  await assert.rejects(work,{code:'LDAP_LOCAL_ACCOUNT_CONFLICT'});assert.equal(f.users.person.hash,'new-local');assert.equal(f.saves,0);
});
test('concurrent successful LDAP sign-ins create one account only',async()=>{
  const f=fixture();await Promise.all([f.authenticate('person','AD-password','ldap'),f.authenticate('person','AD-password','ldap')]);assert.equal(f.saves,1);assert.equal(f.created,1);
});
test('directory accounts never acquire a configured administrator name',async()=>{
  const f=fixture({}, {directory:async()=>({username:'admin',subject:'ab'.repeat(16)})});await assert.rejects(f.authenticate('admin','AD-password','ldap'),{code:'LDAP_LOCAL_ACCOUNT_CONFLICT'});assert.equal(f.created,0);
});
test('disabled signup, capacity denial and disabled provider have no account writes',async()=>{
  const f=fixture();f.directory.config.allowSignUp=false;await assert.rejects(f.authenticate('person','AD-password','ldap'),{code:'LDAP_SIGNUP_DISABLED'});assert.equal(f.created,0);
  const g=fixture({}, {capacityError:{status:503,error:'Capacity busy'}});await assert.rejects(g.authenticate('person','AD-password','ldap'),{code:'LDAP_WORKSPACE_UNAVAILABLE'});assert.equal(g.saves,0);
  const h=fixture({}, {disabled:true});await assert.rejects(h.authenticate('person','AD-password','ldap'),{code:'LDAP_DISABLED'});assert.equal(h.saves,0);
});
test('audit failure and noncreating probes do not persist a new account',async()=>{
  const f=fixture({}, {auditFailure:true});await assert.rejects(f.authenticate('person','AD-password','ldap'),{code:'ACCOUNT_STORAGE_UNAVAILABLE'});assert.equal(f.saves,0);assert.deepEqual(f.users,{});
  const g=fixture();assert.equal(await g.authenticate('person','AD-password','ldap',{create:false}),null);assert.equal(g.created,0);
});
