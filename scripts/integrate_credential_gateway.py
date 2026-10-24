"""Apply narrowly bounded credential integration to the actual gateway revision."""
from pathlib import Path
import argparse

def integrate(source):
    if 'DSH_USER_CREDENTIAL_GATEWAY_CONFIG' in source:return source
    anchor="const serveCourse = createCourseServer();"
    if source.count(anchor)!=1:raise ValueError('Gateway startup anchor changed')
    source=source.replace(anchor,anchor+"\nconst USER_CREDENTIALS = process.env.DSH_USER_CREDENTIAL_GATEWAY_CONFIG ? require('./credential_gateway').createGateway(process.env.DSH_USER_CREDENTIAL_GATEWAY_CONFIG) : null;")
    anchor='  bindAuthenticatedProxyIdentity(req, sessionUser, internetMode);'
    if source.count(anchor)!=1:raise ValueError('Authenticated routing anchor changed')
    route='''
  if (USER_CREDENTIALS && ['/credentials','/api/user-credentials'].includes(parsedUrl.pathname)) {
    if (req.headers.host !== process.env.DSH_TRUSTED_HOST) { res.writeHead(403); return res.end('Use the main DSH site to manage credentials.'); }
    const authorized=()=>accountEnabled(sessionUser)&&(internetMode==='off'||internetAllowed(sessionUser))&&
      Date.now()<activeSession.created+SESSION_TTL_MS&&activeSession.accountStamp===sessionAccountStamp(sessionUser)&&[...SESSIONS.values()].includes(activeSession);
    let credentialOwner;try{credentialOwner=require('./credential_identity').subjectFor(sessionUser,{load:loadUsers,save:saveUsers,audit:()=>auditEvent('credential.identity',sessionUser,internetMode)});}catch{res.writeHead(503);return res.end('Credential identity unavailable.');}
    return USER_CREDENTIALS.handle(req,res,{owner:credentialOwner,environment:internetMode,session:activeSession,authorized,
      reauthenticate:async password=>{const result=await authenticateIdentity(sessionUser,password,loadUsers()[sessionUser]?.authProvider==='ldap'?'ldap':'local',{create:false});return result?.user===sessionUser;},
      audit:event=>auditEvent(event,sessionUser,internetMode)});
  }
'''
    source=source.replace(anchor,anchor+route)
    anchor='server.listen(PROXY_PORT,'
    if source.count(anchor)!=1:raise ValueError('Listener anchor changed')
    listener='''if (USER_CREDENTIALS) USER_CREDENTIALS.startTools(authorization=>{
  const token=typeof authorization==='string'&&authorization.startsWith('Bearer ')?authorization.slice(7):'';
  if(token.length<16||token.length>4096)return null;
  const matches=[];
  for(const [owner,targets] of Object.entries(allUserTargets())) {
    if(!accountEnabled(owner))continue;
    for(const [name,target]of Object.entries(targets)) {
      const environment=name==='internet'?'on':'off';if(environment==='on'&&!internetAllowed(owner))continue;
      let expected;try{expected=getDshToken(target.tokenFile);}catch{continue;}
      if(require('./credential_broker').equal(token,expected))matches.push({owner,environment});
    }
  }
  if(matches.length!==1)return null;
  const identity=matches[0];identity.auditOwner=identity.owner;
  identity.owner=require('./credential_identity').subjectFor(identity.owner,{load:loadUsers,save:saveUsers,audit:()=>auditEvent('credential.identity',identity.auditOwner,identity.environment)});
  return identity;
},auditEvent);

'''
    source=source.replace(anchor,listener+anchor)
    anchor='  const adminLink = isAdmin ?'
    if source.count(anchor)!=1:raise ValueError('Navigation anchor changed')
    source=source.replace(anchor,"  const credentialLink = USER_CREDENTIALS ? '<a id=\"dsh-user-credentials\" href=\"/credentials\" style=\"position:fixed;right:18px;top:58px;z-index:2147483647;background:#003366;color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font:600 13px system-ui\">Credentials</a>' : '';\n"+anchor)
    # Preserve existing native navigation/session recovery, adding one separate link.
    anchor='${control}${appsLink}${adminLink}'
    if source.count(anchor)!=1:raise ValueError('Navigation insertion anchor changed')
    source=source.replace(anchor,anchor+'${credentialLink}')
    anchor='return html + control + appsLink + adminLink;'
    if source.count(anchor)!=1:raise ValueError('Navigation fallback anchor changed')
    source=source.replace(anchor,'return html + control + appsLink + adminLink + credentialLink;')
    anchor="'capacity.policy','package.request'"
    if source.count(anchor)!=1:raise ValueError('Audit projection anchor changed')
    source=source.replace(anchor,anchor+",'credential.identity','credential.save','credential.disable','credential.delete','credential.approve','credential.execute','credential.result','credential.tool.list','credential.tool.profiles','credential.tool.execute','credential.tool.result'")
    return source

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('--output');a=p.parse_args()
    source=Path(a.source);output=Path(a.output) if a.output else source
    output.write_text(integrate(source.read_text(encoding='utf-8')),encoding='utf-8')
