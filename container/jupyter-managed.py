#!/opt/dsh/jupyter/bin/python
"""Private JupyterLab behind the existing authenticated DSH app gateway.

Gateway app forwarding strips /proxy/8888. Restore that prefix at Tornado's
routing boundary so generated assets, REST URLs, cookies and kernel WebSockets
all use the same browser-visible base URL. No gateway/upstream package patch.
"""
import os
from pathlib import Path
import re
import sys

BASE_URL = '/proxy/8888/'
PORT = 8888


def serve(root, state, trusted_host):
    from jupyter_server.auth import IdentityProvider, User
    from jupyter_server.serverapp import ServerApp
    from traitlets.config import Config

    if os.getuid() == 0:
        raise RuntimeError('Jupyter must run as the private non-root runtime user')
    root = Path(root).resolve(strict=True)
    state = Path(state)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ['config', 'data', 'runtime', 'ipython', 'site-packages']:
        folder = state / name
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
    os.environ.update(JUPYTER_CONFIG_DIR=str(state/'config'),
                      JUPYTER_DATA_DIR=str(state/'data'),
                      JUPYTER_RUNTIME_DIR=str(state/'runtime'),
                      IPYTHONDIR=str(state/'ipython'))
    private_packages = str(state/'site-packages')
    os.environ['PYTHONPATH'] = private_packages

    class GatewayIdentity(IdentityProvider):
        # The upstream gateway authenticates every HTTP/WS request and replaces
        # this header. NetworkPolicy permits gateway ingress, not peer workers.
        # Do not persist a second login cookie or accept token/password bypasses.
        @property
        def auth_enabled(self):
            return True

        def get_user(self, handler):
            from tornado.web import HTTPError
            user = handler.request.headers.get('X-DSH-User', '')
            forwarded_host = handler.request.headers.get('X-Forwarded-Host', '')
            websocket = handler.request.headers.get('Upgrade', '').lower() == 'websocket'
            if (forwarded_host != trusted_host and not (websocket and not forwarded_host)) or not re.fullmatch(r'[a-zA-Z0-9_.-]{3,30}', user):
                return None
            if handler.request.method not in ['GET', 'HEAD', 'OPTIONS'] or websocket:
                if handler.request.headers.get('Origin') not in ['https://'+trusted_host, 'http://'+trusted_host]:
                    raise HTTPError(403, 'Notebook requests require the trusted DSH origin')
            return User(username=user)

    config = Config()
    config.ServerApp.ip = '0.0.0.0'
    config.ServerApp.port = PORT
    config.ServerApp.port_retries = 0
    config.ServerApp.open_browser = False
    config.ServerApp.root_dir = str(root)
    config.ServerApp.base_url = BASE_URL
    config.ServerApp.default_url = '/lab'
    config.ServerApp.allow_root = False
    config.ServerApp.allow_remote_access = True
    config.ServerApp.trust_xheaders = True
    config.ServerApp.allow_origin_pat = r'^https?://' + re.escape(trusted_host) + r'$'
    config.ServerApp.disable_check_xsrf = False
    config.ServerApp.identity_provider_class = GatewayIdentity
    config.IdentityProvider.token = ''
    config.ServerApp.jpserver_extensions = {'jupyterlab': True}
    config.ServerApp.log_level = 'WARN'
    config.ServerApp.browser_open_file = False
    app = ServerApp.instance(config=config)
    app.initialize([])
    native_find_handler = app.web_app.find_handler

    def prefixed(request, **kwargs):
        if not request.path.startswith(BASE_URL):
            request.path = BASE_URL.rstrip('/') + request.path
            request.uri = BASE_URL.rstrip('/') + request.uri
        return native_find_handler(request, **kwargs)

    app.web_app.find_handler = prefixed
    app.start()


def main():
    args = sys.argv[1:]
    if args in [['--version'], ['lab', '--version']]:
        from importlib.metadata import version
        print('JupyterLab ' + version('jupyterlab'))
        return
    if args not in [[], ['lab'], ['notebook'], ['server']]:
        raise SystemExit('usage: jupyter lab | jupyter --version; managed port/root/auth settings are fixed')
    if os.environ.get('DSH_ENVIRONMENT') not in ['secure', 'internet']:
        raise SystemExit('Run Jupyter inside a provisioned DSH environment')
    host = os.environ.get('DSH_TRUSTED_HOST', '')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+(?::[0-9]{1,5})?', host):
        raise SystemExit('A valid DSH_TRUSTED_HOST is required')
    serve('/workspace', '/state/jupyter', host)


if __name__ == '__main__':
    main()
