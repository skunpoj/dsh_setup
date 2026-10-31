"""Export only this runtime's rotating launch token to its private gateway view."""
import json
import os
from pathlib import Path
import secrets
import socket
import re
import stat
import math
import time
import urllib.request

root=Path('/published')
environment=os.environ['DSH_ENVIRONMENT']
assert environment in ['secure','internet']


def write(name, value, directory=root):
    temp=directory/('.'+name+'.'+secrets.token_hex(6))
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w')as file:
        file.write(value);file.flush();os.fsync(file.fileno())
    os.replace(temp,directory/name)


def status_projection(file="/private-status/status.json"):
    fd=os.open(file,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        meta=os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode)or meta.st_size>65536:raise ValueError('Invalid status')
        with os.fdopen(fd,'rb',closefd=False)as source:body=source.read(65537)
        if len(body)>65536:raise ValueError('Oversized status')
        value=json.loads(body)
        if not isinstance(value,dict):raise ValueError('Invalid status object')
        observed=value.get('observedAt')
        if type(observed)not in [int,float]or not math.isfinite(observed)or abs(time.time()-observed)>30:raise ValueError('Stale status')
        services=value.get('services')
        if not isinstance(services,list)or len(services)>4:raise ValueError('Invalid services')
        result=[]
        for row in services:
            if not isinstance(row,dict):raise ValueError('Invalid service row')
            if not re.fullmatch(r'[a-z][a-z0-9-]{2,39}',row.get('name',''))or row.get('phase')not in ['running','disabled','access-disabled','backoff','start-failed','port-in-use']:raise ValueError('Invalid service status')
            result.append({'name':row['name'],'phase':row['phase']})
        return {'observedAt':observed,'services':result}
    finally:os.close(fd)


def qualify_network():
    # Same pod/network namespace and DNS policy as the execution container.
    tests=[]
    for host in ['1.1.1.1','8.8.8.8']:
        try:
            with socket.create_connection((host,443),timeout=3):pass
            tests.append(True)
        except OSError:tests.append(False)
    try:
        with urllib.request.urlopen('https://example.com',timeout=8)as response:
            public_http=response.status==200
    except Exception:public_http=False
    if environment=='secure':
        return {'passed':not any(tests) and not public_http,'publicDirectIPBlocked':not any(tests),'publicHTTPSBlocked':not public_http}
    return {'passed':public_http,'publicHTTPSAvailable':public_http}


def main():
    network=None;last=None;checked=0
    while True:
        try:
            token=Path('/runtime-tokens',environment).read_text().strip()
            if not token or len(token)>4096:raise ValueError('Invalid launch token')
            if token!=last:
                write('token',token);last=token
            if network is None or not network['passed'] or time.monotonic()-checked>60:
                network=qualify_network()
                checked=time.monotonic()
                write('qualification.json',json.dumps({'observedAt':time.time(),'environment':environment,**network}))
            try:write('status.json',json.dumps(status_projection()),Path('/published-status'))
            except (OSError,ValueError,TypeError):pass
        except (OSError,ValueError):pass
        time.sleep(5)


if __name__=='__main__':main()
