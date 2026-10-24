'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {subjectFor}=require('../scripts/credential_identity');
test('credential ownership survives password replacement but cannot follow a recycled username',()=>{
 let state={alice:{hash:'old'}};const context={load:()=>structuredClone(state),save:x=>{state=x;return true;},audit:()=>true};
 const id=subjectFor('alice',context);state.alice.hash='new';assert.equal(subjectFor('alice',context),id);
 state={alice:{hash:'recreated'}};assert.notEqual(subjectFor('alice',context),id);
});
test('disabled account, invalid ID, failed audit and failed persistence do not obtain a credential identity',()=>{
 for(const row of [{disabled:true},{credentialSubject:'alice'}])assert.throws(()=>subjectFor('alice',{load:()=>({alice:row}),save:()=>true,audit:()=>true}));
 assert.throws(()=>subjectFor('alice',{load:()=>({alice:{}}),save:()=>true,audit:()=>false}));
 assert.throws(()=>subjectFor('alice',{load:()=>({alice:{}}),save:()=>false,audit:()=>true}));
});
