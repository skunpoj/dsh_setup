"""Run admin-approved services in one user's environment, without shell or K8S access."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time


def validate(service):
    import re
    if not isinstance(service, dict) or not re.fullmatch(r'[a-z][a-z0-9-]{2,39}', service.get('name', '')):
        raise ValueError('Invalid service')
    if type(service.get('enabled')) is not bool or type(service.get('generation')) is not int:
        raise ValueError('Invalid desired state')
    port = service.get('port')
    if type(port) is not int or not 1024 <= port <= 65535 or port in [3080,3081,4000,4001,7681]:
        raise ValueError('Invalid port')
    root = Path('/workspace').resolve(strict=True)
    cwd = Path(service.get('cwd', '')).resolve(strict=True)
    if not cwd.is_relative_to(root) or not cwd.is_dir():
        raise ValueError('Working directory outside workspace')
    args = service.get('argv')
    if service.get('kind') == 'jupyter':
        if service['name'] != 'jupyter' or port != 8888 or args != ['jupyter', 'lab']:
            raise ValueError('Managed notebook settings are fixed')
    elif service.get('kind') == 'command':
        if not isinstance(args,list) or not 2 <= len(args) <= 32 or any(not isinstance(a,str) or len(a)>512 or '\x00' in a for a in args):
            raise ValueError('Invalid argv')
        if args[0] not in ['python3','node','npm']:
            raise ValueError('Executable not approved')
        if args[0] == 'npm' and (len(args)<3 or args[1]!='run' or not re.fullmatch(r'[a-zA-Z0-9:_-]{1,64}',args[2])):
            raise ValueError('Only a named npm script is supported')
        if args[0] in ['python3','node'] and args[1] != '-m':
            script=Path(args[1]) if Path(args[1]).is_absolute() else cwd/args[1]
            if not script.resolve(strict=True).is_relative_to(root):raise ValueError('Script outside workspace')
        if args[0]=='python3' and args[1]=='-m' and (len(args)<3 or args[2]!='http.server'):
            raise ValueError('Only the built-in HTTP module is supported')
        if args[0]=='node' and args[1].startswith('-'):raise ValueError('Supply a workspace script')
    else:
        raise ValueError('Unknown service kind')
    return args, str(cwd)


class Supervisor:
    def __init__(self, control, status):
        self.control=Path(control);self.status=Path(status);self.children={};self.last={};self.stopping=False

    def stop(self, name):
        state=self.children.pop(name,None)
        if state and state['process'].poll() is None:
            try:os.killpg(state['process'].pid,signal.SIGTERM)
            except ProcessLookupError:return
            try:state['process'].wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:os.killpg(state['process'].pid,signal.SIGKILL)
                except ProcessLookupError:pass
                state['process'].wait(timeout=5)

    def tick(self):
        try:
            raw=self.control.read_bytes()
            if len(raw)>16384:raise ValueError('Control too large')
            desired=json.loads(raw)
            if type(desired.get('allowed')) is not bool or not isinstance(desired.get('services'),dict) or len(desired['services'])>4:raise ValueError('Invalid control')
            services=desired['services']
            for key,s in services.items():
                if key!=s.get('name'):raise ValueError('Invalid key')
                validate(s)
            error=None
        except Exception:
            desired={'allowed':False,'services':{}};services={};error='Control unavailable or invalid; services stopped'
        for name in list(self.children):
            state=self.children[name];s=services.get(name)
            if not s or not s['enabled'] or not desired['allowed'] or state['signature']!=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest():
                self.stop(name);self.last.pop(name,None)
        rows=[]
        for name,s in services.items():
            state=self.children.get(name);last=self.last.setdefault(name,{'failures':0,'next':0})
            if state and state['process'].poll() is not None:
                last['failures']+=1;last['next']=time.monotonic()+min(60,2**min(last['failures'],6));self.stop(name);last.pop('started',None);state=None
            phase='disabled' if not s['enabled'] else 'access-disabled' if not desired['allowed'] else 'backoff'
            if s['enabled'] and desired['allowed'] and not state and time.monotonic()>=last['next']:
                sock=socket.socket();sock.settimeout(.2)
                busy=sock.connect_ex(('127.0.0.1',s['port']))==0;sock.close()
                if busy:phase='port-in-use';last['next']=time.monotonic()+10
                else:
                    try:
                        args,cwd=validate(s)
                        env={k:v for k,v in os.environ.items() if k in ['PATH','HOME','LANG','DSH_TRUSTED_HOST','DSH_ENVIRONMENT','PIP_NO_INDEX','PIP_FIND_LINKS','npm_config_offline','npm_config_cache']}
                        env['HOME']='/tmp/service-home';Path(env['HOME']).mkdir(exist_ok=True)
                        process=subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                        state={'process':process,'signature':hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest()};self.children[name]=state
                    except Exception:last['failures']+=1;last['next']=time.monotonic()+min(60,2**min(last['failures'],6));phase='start-failed'
            if state:
                phase='running'
                if time.monotonic()-last.get('started',time.monotonic())>120:last['failures']=0
                last.setdefault('started',time.monotonic())
            rows.append({'name':name,'phase':phase,'port':s['port'],'generation':s['generation'],'restarts':last['failures']})
        self.status.parent.mkdir(parents=True,exist_ok=True)
        temp=self.status.with_suffix('.tmp');temp.write_text(json.dumps({'observedAt':time.time(),'services':rows,'error':error}));temp.replace(self.status)

    def run(self):
        def end(*_):self.stopping=True
        signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
        try:
            while not self.stopping:self.tick();time.sleep(2)
        finally:
            for name in list(self.children):self.stop(name)


if __name__=='__main__':
    if os.getuid()==0:raise SystemExit('Non-root execution required')
    Supervisor('/service-control/config.json','/service-status/status.json').run()
