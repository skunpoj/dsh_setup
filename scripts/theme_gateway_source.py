"""Auth-page presentation overlay; native DSH appearance remains plugin-owned."""
import re
from pathlib import Path
MARKER='// DSH auth-page presentation overlay v3'
# Deployed v1/v2 overlays bound the platform theme under an older alias; integrate() migrates them to ALIAS.
LEGACY_MARKERS=('// DSH institutional presentation overlay v1','// DSH auth-page presentation overlay v2')
ALIAS='applyPlatformTheme'
IMPORT=re.compile(r"const \{platformTheme:(apply\w*PlatformTheme)\}=require\('\./platform_ui'\);")

def auth_wrapper(alias=ALIAS):
    return 'function renderAuthPage(...args){return '+alias+'(unskinned_renderAuthPage(...args));}'

def app_wrapper(alias=ALIAS):
    return 'function injectLogoutControl(...args){return '+alias+'(unskinned_injectLogoutControl(...args));}'

AUTH_WRAPPER=auth_wrapper()
NATIVE_APP_WRAPPER='function injectLogoutControl(...args){return unskinned_injectLogoutControl(...args);}'
IMPORT_LINE="const {platformTheme:"+ALIAS+"}=require('./platform_ui');"

def _validate(source):
    if source.count(MARKER)!=1 or any(m in source for m in LEGACY_MARKERS):
        raise ValueError('Ambiguous presentation marker')
    if [m.group(1) for m in IMPORT.finditer(source)]!=[ALIAS]:
        raise ValueError('Changed presentation import')
    if source.count(AUTH_WRAPPER)!=1 or source.count('function unskinned_renderAuthPage(')!=1:
        raise ValueError('Changed auth presentation wrapper')
    if source.count('function injectLogoutControl(')!=1 or 'PlatformTheme(unskinned_injectLogoutControl(' in source:
        raise ValueError('Native app presentation is not preserved')
    if NATIVE_APP_WRAPPER in source and source.count('function unskinned_injectLogoutControl(')!=1:
        raise ValueError('Changed native app delegate')
    return source

def _migrate(source):
    markers=[m for m in LEGACY_MARKERS if m in source]
    aliases=[m.group(1) for m in IMPORT.finditer(source)]
    if len(markers)!=1 or source.count(markers[0])!=1 or len(aliases)!=1:
        raise ValueError('Changed legacy presentation marker or import')
    alias=aliases[0]
    if source.count(auth_wrapper(alias))!=1 or source.count('function unskinned_renderAuthPage(')!=1:
        raise ValueError('Changed legacy auth presentation wrapper')
    if source.count('function unskinned_injectLogoutControl(')!=1:
        raise ValueError('Changed legacy application renderer')
    if source.count(app_wrapper(alias))==1 and NATIVE_APP_WRAPPER not in source:
        source=source.replace(app_wrapper(alias),NATIVE_APP_WRAPPER,1)
    elif source.count(NATIVE_APP_WRAPPER)!=1 or app_wrapper(alias) in source:
        raise ValueError('Changed legacy application wrapper')
    source=source.replace(markers[0],MARKER,1).replace(IMPORT.search(source).group(0),IMPORT_LINE,1)
    return _validate(source.replace(auth_wrapper(alias),AUTH_WRAPPER,1))

def integrate(source):
    if MARKER in source:
        return _validate(source)
    if any(m in source for m in LEGACY_MARKERS):
        return _migrate(source)
    for name in ['renderAuthPage','injectLogoutControl']:
        if source.count('function '+name+'(')!=1:
            raise ValueError('Changed gateway target: '+name)
    if 'unskinned_renderAuthPage' in source or 'unskinned_injectLogoutControl' in source:
        raise ValueError('Reserved presentation symbol')
    source=source.replace('function renderAuthPage(','function unskinned_renderAuthPage(',1)
    return _validate(MARKER+'\n'+IMPORT_LINE+'\n'+AUTH_WRAPPER+'\n'+source)

def overlay(data):
    result=dict(data)
    result['auth_proxy.js']=integrate(data['auth_proxy.js'])
    for name in ['platform_ui.js','platform.css']:
        result[name]=(Path(__file__).parent/name).read_text(encoding='utf8')
    return result

if __name__=='__main__':
    import argparse,json,hashlib
    parser=argparse.ArgumentParser(description='Prepare an immutable auth-page presentation ConfigMap. Native DSH remains theme-plugin owned. Does not contact Kubernetes.')
    parser.add_argument('--source-json',required=True)
    parser.add_argument('--output-json',required=True)
    args=parser.parse_args()
    destination=Path(args.output_json)
    if destination.exists():
        raise SystemExit('Refusing to overwrite an existing candidate')
    snapshot=json.loads(Path(args.source_json).read_text(encoding='utf8'))
    data=overlay(snapshot['data'])
    digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    candidate={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'dsh-native-theme-'+digest[:12]},'immutable':True,'data':data}
    destination.write_text(json.dumps(candidate),encoding='utf8')
    print(json.dumps({'prepared':True,'applied':False,'sourceDigest':digest,'nativeAppThemeInjected':False}))
