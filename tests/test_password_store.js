const assert = require('assert');
const fs = require('fs'), os = require('os'), path = require('path');
const { hashPassword, verifyPassword, migrateUsers, writeAtomicUsers } = require('../scripts/password_store');
(async () => {
 const a = hashPassword('example-password'), b = hashPassword('example-password');
 assert.notEqual(a.salt,b.salt); assert.notEqual(a.hash,b.hash);
 assert(await verifyPassword('example-password',a));
 assert(!await verifyPassword('wrong',a));
 assert(!await verifyPassword('example-password','example-password'));
 assert(!await verifyPassword('example-password',{...a,hash:'invalid'}));
 assert(!await verifyPassword('x'.repeat(1025),a));
 assert.throws(()=>migrateUsers({alice:{scheme:'unknown'}}));
 const users=migrateUsers({alice:'example-password',bob:b});
 assert(await verifyPassword('example-password',users.alice));
 assert.deepEqual(migrateUsers(users),users);
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-password-'));
 try {
  const file=path.join(dir,'users.json');writeAtomicUsers(file,users);
  assert(!fs.readFileSync(file,'utf8').includes('example-password'));
  assert.throws(()=>writeAtomicUsers(file,{alice:'plaintext'}));
  assert.deepEqual(JSON.parse(fs.readFileSync(file)).alice,users.alice);
  assert.equal(fs.readdirSync(dir).length,1);
 } finally {fs.rmSync(dir,{recursive:true,force:true});}
 console.log('Password salts, validation, migration, verification and atomic persistence passed');
})().catch(e=>{console.error(e.message);process.exitCode=1;});
