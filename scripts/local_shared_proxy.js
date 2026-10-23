'use strict';
// Only the gateway supplies the owner runtime and saved port. Never resolve a
// host/port from a visitor's URL, headers, path or query string.
const http=require('node:http');
const policy=require('./app_signin');
const headers=require('./external_upstream');
function prepare(req,options,websocket=false) {
  const {host,port,publicOrigin,protectedCookies,authorize}=options;
  if(!host||policy.privateLocalPort(port)||!authorize||!authorize())throw Error('Shared application unavailable');
  const target={url:new URL(publicOrigin),basePath:''};
  return {target,path:headers.requestPath(req.url,target),headers:headers.outgoingHeaders(req,target,publicOrigin,protectedCookies,websocket)};
}
function responseHeaders(input,options,target) {
  const copy={...input};
  if(copy.location){
    const location=new URL(copy.location,options.publicOrigin);
    if(location.protocol==='http:'&&[options.host,'127.0.0.1','localhost'].includes(location.hostname)&&Number(location.port||80)===options.port)
      copy.location=options.publicOrigin+location.pathname+location.search+location.hash;
  }
  return {...headers.responseHeaders(copy,target,options.publicOrigin,options.protectedCookies),'cache-control':'no-store'};
}
function proxyHTTP(req,res,options) {
  const prepared=prepare(req,options);
  const upstream=http.request({host:options.host,port:options.port,path:prepared.path,method:req.method,headers:prepared.headers},response=>{
    try {
      if(!options.authorize())throw Error('Access revoked');
      res.writeHead(response.statusCode,responseHeaders(response.headers,options,prepared.target));
      response.on('error',()=>res.destroy());response.pipe(res);
    }catch{response.destroy();if(!res.headersSent){res.writeHead(502);res.end('Application response refused');}else res.destroy();}
  });
  upstream.setTimeout(60000,()=>upstream.destroy(Error('Application timeout')));
  upstream.on('error',()=>{if(!res.headersSent){res.writeHead(502);res.end('Application unavailable');}else res.destroy();});
  req.on('aborted',()=>upstream.destroy());req.on('error',()=>upstream.destroy());res.on('close',()=>upstream.destroy());
  req.pipe(upstream);
}
function proxyWebSocket(req,socket,head,options) {
  const prepared=prepare(req,options,true);
  const upstream=http.request({host:options.host,port:options.port,path:prepared.path,method:'GET',headers:prepared.headers});
  upstream.setTimeout(60000,()=>upstream.destroy(Error('Application timeout')));
  upstream.on('upgrade',(response,remote,remoteHead)=>{
    try {
      if(!options.authorize())throw Error('Access revoked');
      const result=responseHeaders(response.headers,options,prepared.target);result.connection='Upgrade';result.upgrade='websocket';
      socket.write('HTTP/1.1 101 Switching Protocols\r\n'+Object.entries(result).flatMap(([k,v])=>[].concat(v).map(x=>k+': '+x)).join('\r\n')+'\r\n\r\n');
      if(remoteHead.length)socket.write(remoteHead);if(head.length)remote.write(head);
      remote.on('error',()=>socket.destroy());socket.on('error',()=>remote.destroy());
      remote.on('close',()=>socket.destroy());socket.on('close',()=>remote.destroy());remote.pipe(socket);socket.pipe(remote);
    }catch{remote.destroy();socket.destroy();}
  });
  upstream.on('response',response=>{socket.end('HTTP/1.1 '+response.statusCode+' Upstream refused\r\nConnection: close\r\n\r\n');response.destroy();});
  upstream.on('error',()=>socket.destroy());socket.on('error',()=>upstream.destroy());socket.on('close',()=>upstream.destroy());upstream.end();
}
module.exports={proxyHTTP,proxyWebSocket};
