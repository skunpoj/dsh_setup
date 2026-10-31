"""Fixed package-job entry point: wheel download OR network-denied installation.

No shell, source distributions, user URLs, credentials or arbitrary destinations.
The online task never mounts the No Internet workspace. The install task gets
only its owner's workspace/notebook data and read-only private artifacts.
"""
import email.parser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

MAX_BYTES = 300 * 1024 * 1024
MAX_WHEELS = 40
PIN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}==[A-Za-z0-9][A-Za-z0-9_.+-]{0,49}')


def validate_request(value):
    if set(value) != {'id', 'owner', 'specs', 'environment'}:
        raise ValueError('Unexpected request fields')
    if not re.fullmatch('[a-f0-9]{32}', value['id']) or not re.fullmatch('[a-z0-9_.-]{3,30}', value['owner']):
        raise ValueError('Invalid identity')
    if not re.fullmatch('[a-z][a-z0-9-]{0,23}', value['environment']):
        raise ValueError('Invalid environment name')
    specs = value['specs']
    if not isinstance(specs, list) or not 1 <= len(specs) <= 8 or any(not isinstance(s, str) or not PIN.fullmatch(s) for s in specs):
        raise ValueError('Use one to eight exact name==version pins')
    if len(set(s.split('==')[0].lower().replace('_', '-') for s in specs)) != len(specs):
        raise ValueError('Duplicate package')
    return value


def atomic(path, value):
    tmp = path.with_name('.' + path.name + '-' + os.urandom(8).hex())
    with tmp.open('x', encoding='utf-8') as stream:
        json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp, path)


def clean_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PIP_', 'PYTHON', 'UV_', 'HTTP_', 'HTTPS_', 'ALL_PROXY'))}
    env.update(HOME='/tmp/package-home', PYTHONNOUSERSITE='1', PIP_CONFIG_FILE=os.devnull,
               PIP_DISABLE_PIP_VERSION_CHECK='1', TMPDIR='/tmp')
    return env


def run(arguments, **kwargs):
    result = subprocess.run(arguments, env=clean_environment(), capture_output=True, timeout=240, **kwargs)
    if result.returncode:
        # Operator-only bounded diagnostic; never return tool output in the UI.
        Path('/result/tool-error.txt').write_bytes(result.stderr[-8192:])
        raise ValueError('Package tool failed; check wheel availability, compatibility and version pins')


def wheel_metadata(path):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if sum(m.file_size for m in members) > 1024 * 1024 * 1024:
            raise ValueError('Expanded wheel exceeds limit')
        for entry in members:
            parts = entry.filename.split('/')
            if entry.filename.startswith('/') or '\\' in entry.filename or '..' in parts or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Unsafe wheel member')
            if entry.filename.endswith('.pth'):
                raise ValueError('Startup .pth hooks require operator review')
        metadata = [m for m in members if m.filename.endswith('.dist-info/METADATA')]
        if len(metadata) != 1 or metadata[0].file_size > 2 * 1024 * 1024:
            raise ValueError('Invalid wheel metadata')
        value = email.parser.BytesParser().parsebytes(archive.read(metadata[0]))
    name, version = value.get('Name', ''), value.get('Version', '')
    if not PIN.fullmatch(name + '==' + version):
        raise ValueError('Invalid wheel distribution identity')
    return name, version


def download(request, artifacts, status):
    # One active request per owner. Retain environments, but reclaim only
    # old staging directories on this private artifact-only PVC.
    for old in artifacts.parent.iterdir():
        if old.name == request['id']:
            continue
        if not re.fullmatch('[a-f0-9]{32}', old.name) or old.is_symlink() or not old.is_dir():
            raise ValueError('Unexpected artifact staging entry')
        shutil.rmtree(old)
    artifacts.mkdir(mode=0o700, exist_ok=False)
    python = '/opt/dsh/jupyter/bin/python'
    run([python, '-m', 'pip', '--isolated', 'download', '--disable-pip-version-check',
         '--only-binary=:all:', '--index-url', 'https://pypi.org/simple',
         '--dest', str(artifacts), *request['specs']])
    wheels = sorted(artifacts.iterdir())
    if not 1 <= len(wheels) <= MAX_WHEELS or any(p.suffix != '.whl' or p.is_symlink() for p in wheels):
        raise ValueError('Only bounded wheel sets are supported')
    if sum(p.stat().st_size for p in wheels) > MAX_BYTES:
        raise ValueError('Download size exceeds limit')
    rows = []
    for wheel in wheels:
        name, version = wheel_metadata(wheel)
        url = 'https://pypi.org/pypi/' + urllib.parse.quote(name, safe='') + '/' + urllib.parse.quote(version, safe='') + '/json'
        with urllib.request.urlopen(url, timeout=25) as response:
            if urllib.parse.urlsplit(response.url).hostname != 'pypi.org':
                raise ValueError('Unexpected metadata origin')
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError('Metadata exceeds limit')
            metadata = json.loads(raw)
        expected = [r['digests']['sha256'] for r in metadata['urls'] if r['filename'] == wheel.name]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if expected != [digest]:
            raise ValueError('Published artifact hash mismatch')
        rows.append({'filename': wheel.name, 'sha256': digest, 'bytes': wheel.stat().st_size})
    # The trusted result is on a separate job-status mount, never exposed to
    # an Internet user or accepted from the artifact directory itself.
    atomic(status / 'result.json', {'state': 'downloaded', 'wheels': rows,
                                  'bytes': sum(x['bytes'] for x in rows)})


def stage_verified(manifest, artifacts, destination):
    destination.mkdir(mode=0o700)
    if not 1 <= len(manifest['wheels']) <= MAX_WHEELS:
        raise ValueError('Invalid wheel count')
    total = 0
    for row in manifest['wheels']:
        name, digest = row['filename'], row['sha256']
        if not re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl', name) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Invalid artifact record')
        fd = os.open(artifacts / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            meta = os.fstat(source.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size != row['bytes']:
                raise ValueError('Artifact type or length changed')
            total += meta.st_size
            if total > MAX_BYTES:
                raise ValueError('Wheel set exceeds limit')
            data = source.read(MAX_BYTES + 1)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Artifact changed after download')
        target = destination / name
        target.write_bytes(data)
        wheel_metadata(target)


def install(request, manifest, artifacts, status):
    # Network denial is enforced by the installer pod NetworkPolicy as well
    # as --no-index; pip reads only private verified copies, not shared paths.
    wheelhouse = Path('/tmp/verified-wheels')
    stage_verified(manifest, artifacts, wheelhouse)
    base = Path('/workspace/.venvs')
    if base.is_symlink():
        raise ValueError('Environment parent must not be a symlink')
    base.mkdir(exist_ok=True)
    name = 'pkg-' + request['environment'] + '-' + request['id'][:8]
    target = base / name
    if target.exists() or target.is_symlink():
        raise ValueError('Refusing to replace an existing environment')
    # SMB/CIFS may not support Unix symlinks. Python venv otherwise creates
    # lib64 -> lib even with --copies. A real lib64 directory avoids that link;
    # copied executables keep this environment portable across our two stores.
    target.mkdir(mode=0o700)
    (target / 'lib64').mkdir()
    run(['/opt/dsh/jupyter/bin/python', '-m', 'venv', '--copies', '--system-site-packages', str(target)])
    # --ignore-installed ensures the requested locked wheel set is installed
    # into this venv even when a different base-image package is present.
    requirements = Path('/tmp/requirements.lock')
    requirements.write_text('\n'.join(str(wheelhouse / w['filename']) + ' --hash=sha256:' + w['sha256'] for w in manifest['wheels']))
    run([str(target / 'bin/python'), '-m', 'pip', '--isolated', 'install', '--no-index',
         '--no-deps', '--ignore-installed', '--require-hashes', '-r', str(requirements)])
    # Only the owner's notebook data subdirectory is mounted here, never
    # DSH profiles, model credentials, Kerberos tickets or another workspace.
    kernels = Path('/notebook/data/kernels'); kernels.mkdir(parents=True, exist_ok=True)
    kernel = kernels / name; kernel.mkdir(exist_ok=False)
    # A venv created from another venv does not inherit that parent's site
    # packages. Append the managed kernel libraries after the new venv's own
    # packages, keeping requested versions ahead of the base environment.
    managed_site = '/opt/dsh/jupyter/lib/python' + str(sys.version_info.major) + '.' + str(sys.version_info.minor) + '/site-packages'
    if not Path(managed_site, 'ipykernel').is_dir():
        raise ValueError('Managed Jupyter kernel libraries are unavailable')
    bootstrap = target / 'dsh_kernel.py'
    bootstrap.write_text('import sys\nsys.path.append(' + repr(managed_site) + ')\nfrom ipykernel.kernelapp import launch_new_instance\nlaunch_new_instance()\n')
    atomic(kernel / 'kernel.json', {'argv': [str(target / 'bin/python'), str(bootstrap), '-f', '{connection_file}'],
                                  'display_name': request['environment'] + ' (' + request['id'][:8] + ')', 'language': 'python'})
    atomic(status / 'result.json', {'state': 'complete', 'environmentPath': str(target), 'kernelName': name,
                                  'wheelCount': len(manifest['wheels']), 'networkDisabled': True})


def main():
    phase = sys.argv[1]
    if phase not in ['download', 'install']:
        raise ValueError('Unknown package phase')
    request = validate_request(json.loads(Path('/request/request.json').read_text()))
    status = Path('/result')
    try:
        if phase == 'download':
            download(request, Path('/artifacts') / request['id'], status)
        else:
            install(request, json.loads(Path('/request/download.json').read_text()),
                    Path('/artifacts') / request['id'], status)
    except Exception as error:
        atomic(status / 'result.json', {'state': 'failed', 'reason': str(error)[:180] if isinstance(error, ValueError) else type(error).__name__})
        raise SystemExit(1)


if __name__ == '__main__':
    main()
