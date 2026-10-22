'use strict';
const {Resolver}=require('node:dns').promises;
const net=require('node:net');
// Dedicated DNS for approved application forwarding only. The gateway's system
// resolver and every worker's offline DNS policy remain unchanged.
function createLookup(value,ResolverClass=Resolver){
  const servers=String(value||'').split(',').map(x=>x.trim());
  if(!servers.length||servers.length>3||servers.some(x=>net.isIP(x)!==4))throw Error('Invalid external proxy DNS servers');
  const resolver=new ResolverClass({timeout:2000,tries:1});resolver.setServers(servers);
  return async hostname=>{
    if(typeof hostname!=='string'||hostname.length>253||!/^[a-z0-9.-]+$/i.test(hostname)||net.isIP(hostname))throw Error('Invalid upstream DNS name');
    const query=async(method,family)=>{
      try{return (await resolver[method](hostname)).map(address=>({address,family}));}
      catch(e){if(['ENODATA','ENOTFOUND'].includes(e.code))return [];throw e;}
    };
    const [a,aaaa]=await Promise.all([query('resolve4',4),query('resolve6',6)]);
    const answers=[...a,...aaaa];if(!answers.length)throw Error('No approved upstream DNS answers');
    // connectionOptions subsequently checks every answer against the exact
    // approved private address set or public-only range before connecting.
    return answers;
  };
}
module.exports={createLookup};
