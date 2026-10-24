'use strict';
const crypto=require('node:crypto');
function subjectFor(user,{load,save,audit}){
 const users=load();if(!Object.hasOwn(users,user)||users[user].disabled)throw Error('Credential identity unavailable');
 if(users[user].credentialSubject){if(!/^u-[a-f0-9]{32}$/.test(users[user].credentialSubject))throw Error('Invalid credential subject');return users[user].credentialSubject;}
 const subject='u-'+crypto.randomBytes(16).toString('hex');
 if(!audit())throw Error('Credential identity audit unavailable');
 users[user]={...users[user],credentialSubject:subject};if(!save(users))throw Error('Credential identity persistence unavailable');return subject;
}
module.exports={subjectFor};
