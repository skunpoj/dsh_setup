"""Auth-page presentation overlay; native DSH appearance remains plugin-owned."""
from pathlib import Path
MARKER='// DSH auth-page presentation overlay v2'
OLD_MARKER='// DSH institutional presentation overlay v1'
AUTH_WRAPPER='function renderAuthPage(...args){return applyBOTPlatformTheme(unskinned_renderAuthPage(...args));}'
OLD_APP_WRAPPER='function injectLogoutControl(...args){return applyBOTPlatformTheme(unskinned_injectLogoutControl(...args));}'
NATIVE_APP_WRAPPER='function injectLogoutControl(...args){return unskinned_injectLogoutControl(...args);}'

def _validate(source):
    if source.count(MARKER)!=1 or OLD_MARKER in source:
        raise ValueError('Ambiguous presentation marker')
    if source.count(AUTH_WRAPPER)!=1 or source.count('function unskinned_renderAuthPage(')!=1:
        raise ValueError('Changed auth presentation wrapper')
    if source.count('function injectLogoutControl(')!=1 or OLD_APP_WRAPPER in source:
        raise ValueError('Native app presentation is not preserved')
    if NATIVE_APP_WRAPPER in source and source.count('function unskinned_injectLogoutControl(')!=1:
        raise ValueError('Changed native app delegate')
    return source

def integrate(source):
    if MARKER in source:
        return _validate(source)
    if OLD_MARKER in source:
        if source.count(OLD_MARKER)!=1 or source.count(AUTH_WRAPPER)!=1:
            raise ValueError('Changed v1 auth presentation wrapper')
        if source.count('function unskinned_injectLogoutControl(')!=1:
            raise ValueError('Changed v1 application renderer')
        if source.count(OLD_APP_WRAPPER)==1 and NATIVE_APP_WRAPPER not in source:
            source=source.replace(OLD_APP_WRAPPER,NATIVE_APP_WRAPPER,1)
        elif source.count(NATIVE_APP_WRAPPER)!=1 or OLD_APP_WRAPPER in source:
            raise ValueError('Changed v1 application wrapper')
        return _validate(source.replace(OLD_MARKER,MARKER,1))
    for name in ['renderAuthPage','injectLogoutControl']:
        if source.count('function '+name+'(')!=1:
            raise ValueError('Changed gateway target: '+name)
    if 'unskinned_renderAuthPage' in source or 'unskinned_injectLogoutControl' in source:
        raise ValueError('Reserved presentation symbol')
    source=source.replace('function renderAuthPage(','function unskinned_renderAuthPage(',1)
    return _validate(MARKER+"\nconst {platformTheme:applyBOTPlatformTheme}=require('./platform_ui');\n"+AUTH_WRAPPER+'\n'+source)

def overlay(data):
    result=dict(data)
    result['auth_proxy.js']=integrate(data['auth_proxy.js'])
    for name in ['platform_ui.js','bot_platform.css']:
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
