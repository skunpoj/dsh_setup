'use strict';
const assert = require('node:assert/strict');
const {authorizeCredentialUse: check} = require('../scripts/credential_policy');
const base = {principal:'alice',environment:'off',workspace:'project-a',now:100,
  credential:{id:'git-read',owner:'alice',expiresAt:1000,environments:['off'],workspaces:['project-a'],
    rules:[{connector:'git',operation:'read',resource:'repo-a'}]},
  request:{connector:'git',operation:'read',resource:'repo-a'}};
assert.equal(check(base).owner,'alice');
for (const change of [{principal:'bob'},{environment:'on'},{workspace:'project-b'},
  {credential:{...base.credential,revoked:true}}, {credential:{...base.credential,expiresAt:100}},
  {request:{...base.request,operation:'push'}},{request:{...base.request,resource:'repo-b'}}])
  assert.throws(()=>check({...base,...change}),/denied/);
const write = {...base,credential:{...base.credential,rules:[{...base.credential.rules[0],requiresApproval:true}]},
  request:{...base.request,digest:'a'.repeat(64)}};
assert.throws(()=>check(write),/denied/);
const approval={owner:'alice',credentialId:'git-read',operation:'read',resource:'repo-a',workspace:'project-a',
  environment:'off',requestDigest:'a'.repeat(64),expiresAt:200,used:false};
assert.equal(check({...write,approval}).credentialId,'git-read');
for (const change of [{used:true},{expiresAt:100},{owner:'bob'},{requestDigest:'b'.repeat(64)},
  {workspace:'project-b'},{environment:'on'}])
  assert.throws(()=>check({...write,approval:{...approval,...change}}),/denied/);
assert(!JSON.stringify(check(base)).includes('secret'));
console.log('Credential policy: owner/environment/workspace/scope/expiry/revocation/approval checks passed');
