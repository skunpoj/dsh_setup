"""Fail-closed presentation overlay; retain existing authentication functions."""
from pathlib import Path
MARKER='// DSH institutional presentation overlay v1'
def integrate(source):
    if MARKER in source:return source
    wrappers=[]
    for name in ['renderAuthPage','injectLogoutControl']:
        target='function '+name+'('
        if source.count(target)!=1:raise ValueError('Changed gateway target: '+name)
        original='unskinned_'+name
        if original in source:raise ValueError('Reserved presentation symbol')
        source=source.replace(target,'function '+original+'(',1)
        wrappers.append('function '+name+'(...args){return applyBOTPlatformTheme('+original+'(...args));}')
    return MARKER+"\nconst {platformTheme:applyBOTPlatformTheme}=require('./platform_ui');\n"+'\n'.join(wrappers)+'\n'+source

def overlay(data):
    result=dict(data);result['auth_proxy.js']=integrate(data['auth_proxy.js'])
    for name in ['platform_ui.js','bot_platform.css']:
        result[name]=(Path(__file__).parent/name).read_text(encoding='utf8')
    return result

if __name__=='__main__':
    import argparse,json,hashlib
    parser=argparse.ArgumentParser(description='Prepare an immutable presentation ConfigMap from an existing private source snapshot. Does not contact Kubernetes.')
    parser.add_argument('--source-json',required=True);parser.add_argument('--output-json',required=True)
    args=parser.parse_args();destination=Path(args.output_json)
    if destination.exists():raise SystemExit('Refusing to overwrite an existing candidate')
    snapshot=json.loads(Path(args.source_json).read_text(encoding='utf8'))
    data=overlay(snapshot['data']);digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    candidate={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'dsh-platform-theme-'+digest[:12]},'immutable':True,'data':data}
    destination.write_text(json.dumps(candidate),encoding='utf8')
    print(json.dumps({'prepared':True,'applied':False,'sourceDigest':digest}))
