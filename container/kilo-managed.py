#!/usr/bin/env python3
"""Launch the pinned Kilo CLI with operator policy and private local state."""
import json
import os
from pathlib import Path
import re
import sys

MODEL = 'dsh-internal/deepseek-v4.1-flash'
POLICY = Path('/etc/kilo/kilo.json')
BINARY = '/usr/local/lib/node_modules/@kilocode/cli/bin/kilo'
GUARDED_CONFIG_ROOT = Path('/state/kilo/guarded-config')
TASK_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')


def validate(arguments):
    allowed = {'run', 'models', 'session', 'stats', 'export', '--help', '-h', '--version', '-v'}
    if arguments and arguments[0] not in allowed:
        raise ValueError('Use the managed terminal interface or run/models/session/stats/export commands')
    forbidden = {'--share', '--attach', '--cloud-fork', '--port', '--password', '--username', '--command', '--auto', '--dir'}
    for i, arg in enumerate(arguments):
        flag = arg.split('=', 1)[0]
        if flag in forbidden:
            raise ValueError('Remote, sharing and policy-changing options are unavailable')
        if flag in {'--model', '-m'}:
            value = arg.split('=', 1)[1] if '=' in arg else arguments[i+1] if i+1 < len(arguments) else ''
            if value != MODEL:
                raise ValueError('Only the operator-managed internal model is available')
    return arguments


def guarded_policy(parent, policy, root=GUARDED_CONFIG_ROOT):
    guarded = parent.get('DSH_GUARDED_MODEL_BASE_URL', '')
    if not guarded:
        return POLICY
    if not guarded.startswith('http://127.0.0.1:') or not guarded.endswith('/v1'):
        raise ValueError('Unattended model guard must be a loopback /v1 endpoint')
    task = parent.get('DSH_UNATTENDED_TASK', '')
    if not TASK_PATTERN.fullmatch(task):
        raise ValueError('Unattended task id is missing or invalid')
    policy['provider']['dsh-internal']['options']['baseURL'] = guarded
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = root / f'{task}.json'
    temporary = root / f'.{task}.{os.getpid()}.tmp'
    temporary.write_text(json.dumps(policy, separators=(',', ':')), encoding='utf-8')
    temporary.chmod(0o600)
    os.replace(temporary, destination)
    return destination


def environment(parent, policy_path=POLICY):
    env = {k: v for k, v in parent.items() if not k.startswith(('KILO_', 'OPENCODE_', 'OTEL_'))
           and k.upper() not in {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NODE_OPTIONS', 'NODE_TLS_REJECT_UNAUTHORIZED'}}
    env.update({
        'KILO_CONFIG': str(policy_path),
        'KILO_DISABLE_PROJECT_CONFIG': 'true', 'KILO_DISABLE_AUTOUPDATE': 'true',
        'KILO_DISABLE_MODELS_FETCH': 'true', 'KILO_DISABLE_DEFAULT_PLUGINS': 'true',
        'KILO_DISABLE_LSP_DOWNLOAD': 'true', 'KILO_DISABLE_EXTERNAL_SKILLS': 'true',
        'KILO_DISABLE_CLAUDE_CODE': 'true', 'KILO_DISABLE_FFF': 'true',
        'KILO_SESSION_RETRY_LIMIT': '1', 'OTEL_SDK_DISABLED': 'true',
        'XDG_CONFIG_HOME': '/etc/dsh-kilo-config', 'XDG_DATA_HOME': '/state/kilo/data',
        'XDG_STATE_HOME': '/state/kilo/state', 'XDG_CACHE_HOME': '/state/kilo/cache',
    })
    return env


def validate_project(directory, workspace=Path('/workspace')):
    if not directory.resolve().is_relative_to(workspace.resolve()):
        raise ValueError('Start Kilo from a project inside /workspace')


def main():
    arguments = validate(sys.argv[1:])
    # Edit approvals are confined to the private workspace project. Never start
    # a coding session with /state, the credential mount or the image as cwd.
    if not arguments or arguments[0] == 'run':
        validate_project(Path.cwd())
    policy = json.loads(POLICY.read_text(encoding='utf-8'))
    if policy['model'] != MODEL or policy['enabled_providers'] != ['dsh-internal'] or policy['share'] != 'disabled':
        raise ValueError('Unexpected operator policy')
    for directory in ['data', 'state', 'cache']:
        path = Path('/state/kilo') / directory
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    policy_path = guarded_policy(os.environ, policy)
    os.execve('/usr/local/bin/node', ['node', BINARY, *arguments], environment(os.environ, policy_path))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError) as error:
        print('Managed Kilo: ' + str(error), file=sys.stderr)
        raise SystemExit(64)
