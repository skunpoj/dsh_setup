"""Credential-free MCP stdio facade for the owner-bound DSH credential broker.
Provider bearer tokens never enter the worker. Users save alias pc140032646
for the current project in DSH Credentials and approve each operation there.
"""
import base64, hashlib, json, pathlib, re, subprocess, sys, time

ADAPTER='/opt/dsh/container/dsh-connection.cjs'
ALIAS='pc140032646'

def broker(action, value):
    # Existing adapter accepts JSON argv. Set its in-process argv from stdin;
    # user code is never put in the operating-system command line.
    bootstrap="const fs=require('fs'),p=process.argv[1],a=process.argv[2];process.argv=[process.execPath,p,a,fs.readFileSync(0,'utf8')];require(p)"
    run=subprocess.run(['/usr/bin/node','-e',bootstrap,ADAPTER,action],
        input=json.dumps(value),text=True,capture_output=True,timeout=70)
    if run.returncode: raise RuntimeError('Manage the MCP alias in DSH Credentials')
    envelope=json.loads(run.stdout)
    if not isinstance(envelope,dict) or not isinstance(envelope.get('data'),dict):
        raise RuntimeError('Credential broker unavailable')
    return envelope['data']

def execute(name, args):
    if name=='verify_base64':
        if set(args)!={'data','expected_sha256'} or not isinstance(args['data'],str) or len(args['data'])>16384 or not re.fullmatch('[a-f0-9]{64}',args.get('expected_sha256','')):
            raise ValueError('Invalid bounded verification input')
        data=base64.b64decode(args['data'],validate=True)
        actual=hashlib.sha256(data).hexdigest()
        result={'bytes':len(data),'sha256':actual,'matches':actual==args['expected_sha256']}
        return {'content':[{'type':'text','text':json.dumps(result)}],'isError':not result['matches']}
    project=pathlib.Path.cwd().resolve()
    if not project.is_relative_to(pathlib.Path('/workspace').resolve()):
        raise RuntimeError('Private project required')
    if name=='run_python' and set(args)=={'code'} and isinstance(args['code'],str) and len(args['code'].encode())<=4096:
        operation='run-python'
    elif name=='download_file' and set(args)=={'filename'} and isinstance(args['filename'],str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,127}',args['filename']):
        operation='download-file'
    else: raise ValueError('Unsupported MCP operation')
    value={'id':ALIAS,'workspace':project.name,'operation':operation,'parameters':args}
    response=broker('execute',value)
    if response.get('approvalRequired'):
        approval=response['approvalId']
        deadline=time.monotonic()+110
        while time.monotonic()<deadline:
            status=broker('result',{'id':approval})
            if status.get('state')=='approved':
                response=broker('execute',{**value,'approvalId':approval})
                break
            if status.get('state') not in {'pending'}:
                raise RuntimeError('Operation requires a fresh owner decision')
            time.sleep(1)
        else: raise RuntimeError('Approve this operation in DSH Credentials, then retry')
    result=response.get('result')
    if not isinstance(result,dict) or not isinstance(result.get('content'),list):
        raise RuntimeError('MCP result unavailable')
    return result

TOOLS=[
 {'name':'run_python','description':'Run Python on PC140032646 MCP. Requires owner approval in DSH Credentials. Never include credentials in code.',
  'inputSchema':{'type':'object','properties':{'code':{'type':'string','maxLength':4096}},'required':['code'],'additionalProperties':False}},
 {'name':'download_file','description':'Receive an approved MCP file as base64. Requires owner approval in DSH Credentials.',
  'inputSchema':{'type':'object','properties':{'filename':{'type':'string','pattern':'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'}},'required':['filename'],'additionalProperties':False}},
 {'name':'verify_base64','description':'Decode base64 in DSH memory and compare its SHA-256. Pure local verification; no files, secrets or network.',
  'annotations':{'readOnlyHint':True,'destructiveHint':False,'idempotentHint':True,'openWorldHint':False},
  'inputSchema':{'type':'object','properties':{'data':{'type':'string','maxLength':16384},'expected_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}},'required':['data','expected_sha256'],'additionalProperties':False}}
]

def dispatch(request):
    method=request.get('method');params=request.get('params') or {}
    if method=='initialize':
        return {'protocolVersion':'2025-03-26','capabilities':{'tools':{}},'serverInfo':{'name':'dsh-owner-bound-mcp','version':'1'}}
    if method=='ping': return {}
    if method=='tools/list': return {'tools':TOOLS}
    if method=='tools/call':
        try: return execute(params.get('name'),params.get('arguments') or {})
        except Exception: return {'isError':True,'content':[{'type':'text','text':'MCP operation denied or unavailable. Check existing pending/results in DSH Credentials before retrying a write. Save/enable alias pc140032646 for this project and approve the exact operation there.'}]}
    raise ValueError('Unsupported MCP method')

def main():
    while True:
        line=sys.stdin.buffer.readline(65537)
        if not line: return
        if len(line)>65536: return
        try:
            request=json.loads(line)
            if 'id' not in request: continue
            response={'jsonrpc':'2.0','id':request['id'],'result':dispatch(request)}
        except Exception:
            response={'jsonrpc':'2.0','id':request.get('id') if isinstance(locals().get('request'),dict) else None,'error':{'code':-32600,'message':'Invalid MCP request'}}
        print(json.dumps(response),flush=True)

if __name__=='__main__': main()
