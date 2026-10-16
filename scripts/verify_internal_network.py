"""Execute inside one worker; receive endpoint metadata on stdin, not credentials."""
import concurrent.futures
import json
import os
import socket
import struct
import subprocess
import sys
import urllib.error
import urllib.request

settings=json.load(sys.stdin)
mode=os.environ['DSH_ENVIRONMENT']
record={'environment':mode,'uid':os.getuid(),'actualRdtAuthenticationTested':False}


def dns(server,name,kind=1,expect_reply=True):
    wire=b''.join(bytes([len(x)])+x.encode() for x in name.split('.'))+b'\0'+struct.pack('!HH',kind,1)
    packet=struct.pack('!6H',4123,256,1,0,0,0)+wire
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        try:
            sock.sendto(packet,(server,53));reply=sock.recv(4096)
            if not expect_reply:return {'denied':False}
            values=struct.unpack('!6H',reply[:12]);return {'rcode':values[1]&15,'answers':values[3]}
        except (OSError,socket.timeout):return {'denied':True}


def curl(url):
    p=subprocess.run(['curl','--noproxy','*','--max-time','3','-s','-o','/dev/null','-w','%{http_code}',url],capture_output=True,text=True)
    return {'target':url,'exitCode':p.returncode,'HTTP':p.stdout}


def port_denied(ip,port):
    try:
        with socket.create_connection((ip,port),timeout=2):return False
    except OSError:return True


request=urllib.request.Request('http://litellm.llm.svc.cluster.local:4000/v1/chat/completions',
    data=json.dumps({'model':'deepseek-v4.1-flash','messages':[{'role':'user','content':'Reply exactly INTERNAL_POLICY_OK'}],
                    'max_tokens':32,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}).encode(),
    headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']})
with urllib.request.urlopen(request,timeout=30) as response:
    record['internalInferenceExact']=json.load(response)['choices'][0]['message']['content'].strip()=='INTERNAL_POLICY_OK'
assert record['internalInferenceExact']
urls=['https://github.com','https://pypi.org','https://registry.npmjs.org']
if mode=='secure':urls.append('https://1.1.1.1')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:record['public']=list(pool.map(curl,urls))
if mode=='secure':
    assert all(r['HTTP']=='000' and r['exitCode']!=0 for r in record['public'])
    record['publicDNSLocalDenial']=dns(settings['resolver'],'example.com')
    record['encodedNameLocalDenial']=dns(settings['resolver'],'synthetic-payload.example.com')
    assert record['publicDNSLocalDenial']['rcode']==3 and record['encodedNameLocalDenial']['rcode']==3
    record['kerberosSRV']=dns(settings['resolver'],'_kerberos._tcp.bot.or.th',33)
    assert record['kerberosSRV']['rcode']==0 and record['kerberosSRV']['answers']>0
    record['directCoreDNSDenied']=dns(settings['coreDNS'],'containment-test.invalid',expect_reply=False)['denied']
    record['directPublicDNSDenied']=dns('8.8.8.8','containment-test.invalid',expect_reply=False)['denied']
    record['directCoreDNSTCPDenied']=port_denied(settings['coreDNS'],53)
    assert record['directCoreDNSDenied'] and record['directPublicDNSDenied'] and record['directCoreDNSTCPDenied']
    with socket.create_connection((settings['kdc'],88),timeout=3):record['kerberosPortReachable']=True
    # No credentials, session creation or data query: inspect the anonymous gate.
    try:
        with urllib.request.urlopen('http://botdlk-gw3-p1.bot.or.th:28998/sessions',timeout=5) as response:
            status=response.status;negotiate='negotiate' in response.headers.get('WWW-Authenticate','').lower()
    except urllib.error.HTTPError as response:
        status=response.code;negotiate='negotiate' in response.headers.get('WWW-Authenticate','').lower()
    record['livyAnonymousStatus']=status;record['kerberosChallengePresent']=negotiate
    if status not in (401,403):raise RuntimeError('Datalake endpoint did not deny anonymous access; real RDT permissions remain unverified')
else:
    assert all(r['HTTP']=='200' for r in record['public'])
    record['unrelatedInternalServiceDenied']=port_denied(settings['postgres'],5432)
    record['datalakeFromInternetDenied']=port_denied(settings['livy'],28998)
    record['kdcFromInternetDenied']=port_denied(settings['kdc'],88)
    assert record['unrelatedInternalServiceDenied'] and record['datalakeFromInternetDenied'] and record['kdcFromInternetDenied']
print(json.dumps(record))
