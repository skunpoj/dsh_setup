from pathlib import Path
import hashlib,json,shutil,re,subprocess
HERE=Path(__file__).parent
BASE=Path('C:/Users/skunpojt/outputs/dsh-app-entry-completion-20261021/dsh-environment-gateway')
OUT=HERE/'runtime';OUT.mkdir(exist_ok=True)
for p in BASE.glob('*.js'):shutil.copy2(p,OUT/p.name)
shutil.copy2(HERE/'app_signin.js',OUT/'app_signin.js')
s=(BASE/'auth_proxy.js').read_text(encoding='utf8')
baseline=hashlib.sha256(s.encode()).hexdigest()
assert baseline=='9e2e87791cb1bbba29ad1c53b340d06706302a49f6df9427c645726169643e51'
def patch(old,new):
 global s
 assert s.count(old)==1,(old,s.count(old))
 s=s.replace(old,new)
patch("const APP_DOMAIN = (process.env.DSH_APP_DOMAIN || '').toLowerCase();", """const APP_DOMAIN = (process.env.DSH_APP_DOMAIN || '').toLowerCase();
const APP_SIGNIN = process.env.DSH_APP_LOGIN_ENABLED === 'true' ? new (require('./app_signin').AppSignIn)({domain:APP_DOMAIN, issuer:'https://'+process.env.DSH_TRUSTED_HOST, mappings:appLinks}) : null;""")
patch("  const parsedUrl = url.parse(req.url, true);\n  if(parsedUrl.pathname==='/api/signup-capacity')", """  const parsedUrl = url.parse(req.url, true);
  if(APP_SIGNIN && req.method==='GET' && parsedUrl.pathname==='/login' && Object.hasOwn(parsedUrl.query,'app')) {
    const headers={'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY', 'Content-Security-Policy':\"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'\"};
    try {if(req.headers.host!==process.env.DSH_TRUSTED_HOST)throw Error();const body=APP_SIGNIN.begin(parsedUrl.query.app,res,'',parsedUrl.query.environment);res.writeHead(200,headers);return res.end(body);}
    catch {res.writeHead(404,headers);return res.end('Application sign-in unavailable.');}
  }
  if(parsedUrl.pathname==='/api/signup-capacity')""")
start=s.index('  // Handle Login Form Submission')
end=s.index('  // Handle User Registration Form Submission',start)
login=s[start:end]
old="      const internet = normalizeInternetMode(params.get('internet'));"
assert login.count(old)==1
login=login.replace(old,"""      let appContext=null;
      if(params.has('app_login')) {
        try {if(!APP_SIGNIN)throw Error();appContext=APP_SIGNIN.consume(req,params);}
        catch {res.writeHead(403,{'Content-Type':'text/plain; charset=utf-8','Cache-Control':'no-store'});return res.end('Application sign-in expired or access denied. Reopen the application.');}
      }
      const loginPage=options=>appContext?APP_SIGNIN.begin(appContext.name,res,options.errorMsg||'',appContext.internet):renderAuthPage(options);
      const internet = appContext ? appContext.internet : normalizeInternetMode(params.get('internet'));""")
login=login.replace("const application = params.get('application') || 'dsh';","const application = appContext ? 'dsh' : params.get('application') || 'dsh';")
# Preserve normal auth/account/mode/runtime/audit/session checks. App visits never
# mint a workspace-runtime cookie or land in workspace/terminal/Jupyter.
marker='        // Create personal workspace folder for user if not exists'
assert login.count(marker)==1
login=login.replace(marker,"""        if(appContext) {
          res.writeHead(303,{'Set-Cookie':`${COOKIE_NAME}=${sessionId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400${getCookieDomain()}${COOKIE_TRANSPORT}`,'Location':appContext.destination,'Cache-Control':'no-store'});
          return res.end();
        }

"""+marker)
login=login.replace('return res.end(renderAuthPage({','return res.end(loginPage({')
login,n=re.subn(r"res.writeHead\((\d+), \{ 'Content-Type': 'text/html; charset=utf-8' \}\);\s+return res.end\(loginPage\((\{[^\n]+\})\)\);",r"const body=loginPage(\2);\n          res.writeHead(\1, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control':'no-store' });\n          return res.end(body);",login)
assert n==2,n
s=s[:start]+login+s[end:]
(OUT/'auth_proxy.js').write_text(s,encoding='utf8',newline='\n')
# Integrate the already-qualified external/Public feature, preserving the current
# capacity/session changes. Normalize LF before three-way merging.
COMMON=Path('C:/Users/skunpojt/outputs/dsh-proxy-triage-Test-20261021/dsh-live-source/auth_proxy.js')
FEATURE=Path('C:/Users/skunpojt/outputs/dsh-normal-login-Test-20261021/dsh-proxy-test-gateway/auth_proxy.js')
MERGE=Path('C:/Users/skunpojt/outputs/dsh-app-entry-completion-20261021/merge');MERGE.mkdir(exist_ok=True)
args=[]
for n,p in enumerate([OUT/'auth_proxy.js',COMMON,FEATURE]):
 q=MERGE/(str(n)+'.js');q.write_text(p.read_text(encoding='utf8'),encoding='utf8',newline='\n');args.append(str(q))
r=subprocess.run(['git','merge-file','-p',*args],capture_output=True)
assert r.returncode==1 and r.stdout.count(b'<<<<<<<')==1
s=r.stdout.decode('utf8')
s,n=re.subn(r'<<<<<<< [^\n]+\n(.*?)=======\n.*?>>>>>>> [^\n]+\n',lambda m:m.group(1),s,flags=re.S)
assert n==1 and '<<<<<<<' not in s
s=s.replace("const launchPaths = {dsh:'/', terminal:'/terminal', jupyter:'/proxy/8888/lab'};", "const launchPaths = {dsh:'/', terminal:'/terminal', jupyter:'/proxy/8888/lab', applications:'/applications'};")
s=s.replace("appContext ? 'dsh' : params.get('application') || 'dsh'", "appContext ? 'dsh' : params.get('application') || process.env.DSH_DEFAULT_APPLICATION || 'dsh'")
old="  const login='https://'+process.env.DSH_TRUSTED_HOST+'/login';"
assert s.count(old)==1
s=s.replace(old,"  const login='https://'+process.env.DSH_TRUSTED_HOST+'/login'+(APP_SIGNIN?'?app='+encodeURIComponent(alias):'');")
# The existing canonical redirect for platform paths must retain app context only
# for app sign-in, never route a visitor to management/terminal pages.
old="    res.writeHead(302,{Location:'https://'+process.env.DSH_TRUSTED_HOST+parsedUrl.pathname});return res.end();"
assert s.count(old)==1
s=s.replace(old,"    const app=appHostName(req.headers.host);\n    res.writeHead(302,{Location:'https://'+process.env.DSH_TRUSTED_HOST+(APP_SIGNIN?'/login?app='+encodeURIComponent(app):parsedUrl.pathname)});return res.end();")
marker='  if (!authenticated) {\n    if (courseRoute)'
assert s.count(marker)==1
s=s.replace(marker,"  if (!authenticated && APP_SIGNIN && appHostName(req.headers.host) && req.method==='GET' && !parsedUrl.pathname.startsWith('/api/')) {\n    res.writeHead(303,{Location:'https://'+process.env.DSH_TRUSTED_HOST+'/login?app='+encodeURIComponent(appHostName(req.headers.host)), 'Cache-Control':'no-store'});return res.end();\n  }\n"+marker)
(OUT/'auth_proxy.js').write_text(s,encoding='utf8',newline='\n')
shutil.copy2(FEATURE.parent/'external_upstream.js',OUT/'external_upstream.js')
receipt={'baseline_live_source_sha256':baseline,'candidate_auth_proxy_sha256':hashlib.sha256(s.encode()).hexdigest(),'feature_flag':'DSH_APP_LOGIN_ENABLED=true','production_deployment':False,'integration_scope':'Normal issuer app-focused presentation and fixed registered-alias return only. General-domain proxy integration remains separate.'}
receipt['integration_scope']='Latest Main capacity/session source plus already-qualified general-domain/Public proxy feature and new app-focused normal issuer login. Not deployed.'
receipt['proxy_merge_inputs_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in [COMMON,FEATURE]}
(HERE/'BUILD.json').write_text(json.dumps(receipt,indent=2),encoding='utf8')
print(json.dumps(receipt))
