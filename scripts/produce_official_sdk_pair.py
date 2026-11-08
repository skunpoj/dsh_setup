"""Bounded Linux-only producer; no Azure/PAT/provider or runtime deployment.

The approved DSO job supplies immutable locally present images and a separately
admitted offline dependency cache. All build/smoke containers have network=none,
no host credential mounts and no Docker socket. Missing prerequisites refuse;
this script never installs tools, pulls images, retries, prunes or asks for keys.
"""
import argparse
import hashlib
import types
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time

PRODUCER_PATH = Path(__file__).resolve(strict=True)
VERIFIER_PATH = PRODUCER_PATH.with_name('official_sdk_release_admission.py').resolve(strict=True)
if VERIFIER_PATH.parent != PRODUCER_PATH.parent:
    raise RuntimeError('VERIFIER_MODULE_ORIGIN_REFUSED')
VERSION = '0.2.2a2'
SOURCE = 'ce7073d51254c26cd63b22a60835b8f948deb447'
SOURCE_TREE = 'd3c6ee1d1f0ec8b71c92e1b62d0cf9a8d6553bf8'
PNPM_LOCK_SHA256 = '6dbb7b4d0117aa2a69d19e348cb22e2b46eba5b11af146ab24b7a2bcc3a9b86c'
SDK_NAME = f'deepseek_harness_sdk-{VERSION}-py3-none-any.whl'
RUNTIME_NAME = f'deepseek_harness_runtime_bin-{VERSION}-py3-none-manylinux_2_28_x86_64.whl'
IMAGE = re.compile(r'[^\s@]+@sha256:[a-f0-9]{64}')

PUBLIC_SOURCE = 'https://github.com/deepseek-ai/deepseek-harness.git'
STAGES = ('prepare.sh', 'manylinux.sh', 'compile.sh', 'keyless_approval.py')
CACHE_ROOTS = {'pnpm-store', 'node-gyp', 'python-wheels', 'pkg-cache'}
RESOURCE_LIMIT_KEYS = {'nanoCpus', 'memoryBytes', 'pidsLimit', 'storageBytes'}


def _immutable_image(value):
    return isinstance(value, str) and IMAGE.fullmatch(value) and not value.endswith(':'+'0'*64)


def _unique_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('DUPLICATE_PRODUCER_JSON_FIELD')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_bound_verifier(expected_sha256):
    """Hash the exact sibling module before executing any of its code."""
    raw = read_plain_file(VERIFIER_PATH)
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('PRODUCER_VERIFIER_CHANGED')
    # Compile the same bytes that were hashed; never reopen the path for exec.
    module = types.ModuleType('dsh_bound_official_sdk_release_admission')
    module.__file__ = str(VERIFIER_PATH)
    exec(compile(raw, str(VERIFIER_PATH), 'exec'), module.__dict__)
    expected = (VERSION, SOURCE, SOURCE_TREE, PNPM_LOCK_SHA256, SDK_NAME, RUNTIME_NAME)
    observed = (module.VERSION, module.SOURCE, module.SOURCE_TREE,
                module.PNPM_LOCK_SHA256, module.SDK_NAME, module.RUNTIME_NAME)
    if observed != expected:
        raise ValueError('VERIFIER_PINNED_CONSTANT_MISMATCH')
    return module


def require_plain_ancestors(path, *, leaf_may_be_missing=False):
    """Refuse symlinked or special path components, including root parents."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('ABSOLUTE_PRODUCER_PATH_REQUIRED')
    chain = list(reversed((path, *path.parents)))
    for index, part in enumerate(chain):
        try:
            mode = os.lstat(part).st_mode
        except FileNotFoundError:
            if leaf_may_be_missing and index == len(chain) - 1:
                continue
            raise ValueError('PRODUCER_PATH_ANCESTOR_MISSING')
        if stat.S_ISLNK(mode):
            raise ValueError('PRODUCER_PATH_SYMLINK_REFUSED')
        if index < len(chain) - 1 and not stat.S_ISDIR(mode):
            raise ValueError('PRODUCER_PATH_ANCESTOR_NOT_DIRECTORY')


def read_plain_file(path):
    require_plain_ancestors(path)
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise ValueError('PRODUCER_INPUT_NOT_REGULAR')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
    flags |= getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('PRODUCER_INPUT_NOT_REGULAR')
        return stream.read()


def verify_bounded_workspace(parent, *, maximum_bytes, minimum_free_bytes):
    """Require an existing bounded kernel tmpfs mount, never create/mount it.

    Docker storage-opt bounds only the container layer. The /work bind must
    have its own actual filesystem ceiling; a directory label/free-space check
    is insufficient. Platform admission must provide this exact dedicated mount.
    """
    require_plain_ancestors(parent)
    if sys.platform != 'linux':
        raise ValueError('DSO_LINUX_AGENT_REQUIRED')
    info = read_plain_file(Path('/proc') / str(os.getpid()) / 'mountinfo').decode('utf-8')
    def unescape(value):
        return re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), value)
    matches = []
    for line in info.splitlines():
        left, separator, right = line.partition(' - ')
        fields, filesystem = left.split(), right.split()
        if not separator or len(fields) < 6 or len(filesystem) < 3:
            raise ValueError('KERNEL_MOUNTINFO_INVALID')
        if unescape(fields[4]) == str(parent):
            matches.append((fields, filesystem))
    if len(matches) != 1:
        raise ValueError('DEDICATED_WORKSPACE_MOUNT_REQUIRED')
    fields, filesystem = matches[0]
    if (filesystem[0] != 'tmpfs' or fields[3] != '/'
            or not {'rw', 'nosuid', 'nodev'} <= set(fields[5].split(','))):
        raise ValueError('BOUNDED_WORKSPACE_FILESYSTEM_REQUIRED')
    usage = os.statvfs(parent)
    total = usage.f_blocks * usage.f_frsize
    available = usage.f_bavail * usage.f_frsize
    if total <= 0 or total > maximum_bytes or available < minimum_free_bytes:
        raise ValueError('WORKSPACE_CAPACITY_NOT_ADMITTED')
    return {'filesystem': 'tmpfs', 'capacityBytes': total, 'availableBytes': available,
            'mountId': fields[0], 'mountPoint': str(parent)}


def validate_admission(value, *, now):
    keys = {'kind','operationId','expiresAt','sourceCommit','sourceTree','pnpmLockSha256',
            'builderImage','manylinuxImage','cacheRoot','cacheManifest','cacheManifestSha256',
            'caFile','caSha256','workRoot','minimumFreeBytes','producerSha256',
            'verifierSha256','stageHashes','resourceLimits'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('EXACT_PRODUCER_ADMISSION_REQUIRED')
    if (value['kind'] != 'DSH_SDK_PRODUCER_ADMISSION_V1'
            or not re.fullmatch(r'[a-f0-9]{32}', str(value['operationId']))
            or value['operationId'] == '0'*32
            or type(value['expiresAt']) not in (int,float) or not 0 < value['expiresAt']-now <= 10800
            or value['sourceCommit'] != SOURCE or value['sourceTree'] != SOURCE_TREE
            or value['pnpmLockSha256'] != PNPM_LOCK_SHA256
            or not _immutable_image(value['builderImage']) or not _immutable_image(value['manylinuxImage'])
            or type(value['minimumFreeBytes']) is not int or value['minimumFreeBytes'] <= 0
            or not isinstance(value['stageHashes'], dict) or set(value['stageHashes']) != set(STAGES)
            or not isinstance(value['resourceLimits'], dict)
            or set(value['resourceLimits']) != RESOURCE_LIMIT_KEYS):
        raise ValueError('INVALID_PRODUCER_ADMISSION')
    for name in ('cacheManifestSha256','caSha256','producerSha256','verifierSha256'):
        if not re.fullmatch(r'[a-f0-9]{64}', str(value[name])) or value[name] == '0'*64:
            raise ValueError('ACTUAL_PRODUCER_INPUT_HASH_REQUIRED')
    for sha in value['stageHashes'].values():
        if not re.fullmatch(r'[a-f0-9]{64}', str(sha)) or sha == '0'*64:
            raise ValueError('ACTUAL_STAGE_HASH_REQUIRED')
    for key in ('cacheRoot','cacheManifest','caFile','workRoot'):
        path = Path(value[key])
        if not path.is_absolute() or any(part in {'task-secrets','.ssh','.azure'} for part in path.parts):
            raise ValueError('PRODUCER_SOFTWARE_PATH_REQUIRED')
    limits = value['resourceLimits']
    if (type(limits['nanoCpus']) is not int or not 100_000_000 <= limits['nanoCpus'] <= 8_000_000_000
            or type(limits['memoryBytes']) is not int or not 512*1024**2 <= limits['memoryBytes'] <= 32*1024**3
            or type(limits['pidsLimit']) is not int or not 16 <= limits['pidsLimit'] <= 4096
            or type(limits['storageBytes']) is not int or not 1024**3 <= limits['storageBytes'] <= 64*1024**3):
        raise ValueError('BOUNDED_PRODUCER_RESOURCES_REQUIRED')
    return value


def verify_cache(root, manifest_raw):
    require_plain_ancestors(root)
    manifest = _unique_json(manifest_raw)
    if not isinstance(manifest, dict) or set(manifest) != {'kind','files'} or manifest['kind'] != 'DSH_OFFLINE_SDK_CACHE_V1':
        raise ValueError('EXACT_OFFLINE_CACHE_MANIFEST_REQUIRED')
    entries = manifest['files']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500000:
        raise ValueError('BOUNDED_OFFLINE_CACHE_REQUIRED')
    seen = set(); total = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'path','bytes','sha256'}:
            raise ValueError('INVALID_CACHE_ENTRY')
        relative = PurePosixPath(entry['path'])
        if (relative.is_absolute() or '..' in relative.parts or '\\' in entry['path']
                or relative.parts[0] not in CACHE_ROOTS or str(relative) != entry['path']
                or entry['path'] in seen or type(entry['bytes']) is not int or entry['bytes'] < 0):
            raise ValueError('CACHE_PATH_REFUSED')
        seen.add(entry['path']); path = root / entry['path']
        require_plain_ancestors(path)
        if (not path.is_file() or path.stat().st_size != entry['bytes']
                or not re.fullmatch(r'[a-f0-9]{64}', str(entry['sha256']))
                or digest_file(path) != entry['sha256']):
            raise ValueError('CACHE_BYTES_CHANGED')
        total += entry['bytes']
        if total > 32 * 1024**3: raise ValueError('CACHE_SIZE_REFUSED')
    actual = set()
    for path in root.rglob('*'):
        mode = os.lstat(path).st_mode
        relative = path.relative_to(root).as_posix()
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError('CACHE_SPECIAL_FILE_REFUSED')
        actual.add(relative)
    if actual != seen or {PurePosixPath(p).parts[0] for p in seen} != CACHE_ROOTS:
        raise ValueError('CACHE_CLOSURE_MISMATCH')
    return total


class Producer:
    def __init__(self, admission, *, run=subprocess.run, clock=time.time):
        self.a = validate_admission(admission, now=clock()); self.run = run; self.clock = clock
        self.root = Path(self.a['workRoot']); self.containers = []; self.owns_root = False
        self.reserved_names = {}; self.pending_names = {}
        self.stages = Path(__file__).with_name('official-sdk-build')

    def _command_env(self):
        return {'PATH':os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin'),
                'HOME':str(self.root/'host-home'), 'LANG':'C.UTF-8',
                'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,
                'GIT_TERMINAL_PROMPT':'0','GIT_TRACE':'0','GIT_CURL_VERBOSE':'0'}

    def event(self, **value):
        # Metadata only: producer has no authentication input or secret reader.
        with (self.root/'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value,sort_keys=True)+'\n'); stream.flush(); os.fsync(stream.fileno())

    def command(self, args, *, log=None):
        remaining = self.a['expiresAt'] - self.clock()
        if remaining <= 0: raise ValueError('PRODUCER_WINDOW_EXPIRED')
        env = self._command_env()
        output = (self.root/'out'/log).open('xb') if log else None
        try:
            result = self.run(args, env=env, timeout=remaining, check=False,
                              stdout=output or subprocess.PIPE, stderr=output or subprocess.PIPE)
        finally:
            if output: output.close()
        if result.returncode != 0: raise ValueError('PRODUCER_COMMAND_FAILED_NO_RETRY')
        return result.stdout or b''

    def inspect_optional(self, identity):
        """One read only. Absence is None; any malformed/other result refuses."""
        remaining = self.a['expiresAt'] - self.clock()
        if remaining <= 0:
            raise ValueError('PRODUCER_WINDOW_EXPIRED')
        result = self.run(['docker','inspect',identity], env=self._command_env(),
                          timeout=remaining, check=False,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            if re.fullmatch(rb'(?:Error(?: response from daemon)?: )?No such (?:object|container): [^\r\n]+[\r\n]*', result.stderr):
                return None
            raise ValueError('DOCKER_ABSENCE_NOT_PROVEN')
        value = json.loads(result.stdout)
        if not isinstance(value, list) or len(value) != 1:
            raise ValueError('AMBIGUOUS_DOCKER_IDENTITY')
        return value[0]

    def _bind_uncertain(self, name, image):
        info = self.inspect_optional(name)
        if info is None:
            return False
        cid = info.get('Id', '')
        if (not re.fullmatch(r'[a-f0-9]{64}', cid)
                or info.get('Config', {}).get('Image') != image
                or info.get('Config', {}).get('Labels', {}).get('dsh.sdk.operation') != self.a['operationId']):
            raise ValueError('FOREIGN_UNCERTAIN_BUILD_CONTAINER')
        if (cid, image) not in self.containers:
            self.containers.append((cid, image))
        self.pending_names.pop(name, None)
        self.event(operation='create-uncertain-bound', name=name, id=cid)
        return True

    def retire(self):
        """Observe reserved names without recreating; remove only exact owned IDs.

        An absent uncertain create remains unresolved, even after bounded reads:
        its durable reserved name must be reconciled by the owner before any
        new execution. A timeout is never proof that daemon work is terminal.
        """
        if not self.owns_root:
            return
        # This separate finite cleanup grace works after the build deadline.
        deadline = time.monotonic() + 30
        def observed(args, *, absent_ok=False):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('PRODUCER_CLEANUP_WINDOW_EXPIRED')
            result = self.run(args, env=self._command_env(), timeout=remaining,
                              check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                if absent_ok and re.fullmatch(rb'(?:Error(?: response from daemon)?: )?No such (?:object|container): [^\r\n]+[\r\n]*', result.stderr):
                    return None
                raise ValueError('EXACT_PRODUCER_CLEANUP_FAILED')
            return result.stdout
        for name, image in list(self.pending_names.items()):
            # Multiple bounded observations allow a delayed daemon completion.
            for _ in range(3):
                raw = observed(['docker', 'inspect', name], absent_ok=True)
                if raw is None:
                    continue
                values = json.loads(raw)
                if not isinstance(values, list) or len(values) != 1:
                    raise ValueError('AMBIGUOUS_DOCKER_IDENTITY')
                info = values[0]; cid = info.get('Id', '')
                if (not re.fullmatch(r'[a-f0-9]{64}', cid)
                        or info.get('Config', {}).get('Image') != image
                        or info.get('Config', {}).get('Labels', {}).get('dsh.sdk.operation') != self.a['operationId']):
                    raise ValueError('FOREIGN_UNCERTAIN_BUILD_CONTAINER')
                self.containers.append((cid, image)); self.pending_names.pop(name)
                self.event(operation='create-uncertain-bound', name=name, id=cid)
                break
            else:
                self.event(operation='create-uncertain-unresolved', name=name, image=image,
                           cleanupVerified=False, reexecutionAllowed=False)
        for cid, image in list(self.containers):
            values = json.loads(observed(['docker', 'inspect', cid]))
            if not isinstance(values, list) or len(values) != 1:
                raise ValueError('AMBIGUOUS_DOCKER_IDENTITY')
            info = values[0]
            def own(value):
                return (value.get('Id') == cid and value.get('Config', {}).get('Image') == image
                        and value.get('Config', {}).get('Labels', {}).get('dsh.sdk.operation') == self.a['operationId'])
            if not own(info):
                raise ValueError('FOREIGN_PRODUCER_CLEANUP_REFUSED')
            if info['State'].get('Running'):
                self.event(operation='stop-reserved', id=cid)
                observed(['docker', 'stop', '--time=10', cid])
                info = json.loads(observed(['docker', 'inspect', cid]))[0]
                if not own(info) or info['State'].get('Running'):
                    raise ValueError('PRODUCER_EXIT_UNVERIFIED')
            self.event(operation='remove-reserved', id=cid, exitCode=info['State'].get('ExitCode'))
            observed(['docker', 'rm', cid])
            if observed(['docker', 'inspect', cid], absent_ok=True) is not None:
                raise ValueError('PRODUCER_REMOVAL_NOT_VERIFIED')
            self.containers.remove((cid, image))
            self.event(operation='container-removed', id=cid, absenceVerified=True)
        if self.pending_names:
            raise ValueError('PRODUCER_CREATE_OUTCOME_UNRESOLVED')

    def image(self, image):
        info = json.loads(self.command(['docker','image','inspect',image]))
        if (len(info)!=1 or image not in info[0].get('RepoDigests',[])
                or info[0].get('Os')!='linux' or info[0].get('Architecture')!='amd64'):
            raise ValueError('ADMITTED_LINUX_IMAGE_NOT_PRESENT')
        return info[0]['Id']

    def container(self, role, image, stage):
        name = 'dsh-sdk-'+self.a['operationId']+'-'+role
        if name in self.reserved_names:
            raise ValueError('PRODUCER_CREATE_ALREADY_RESERVED')
        if self.inspect_optional(name) is not None:
            raise ValueError('RESERVED_BUILD_CONTAINER_EXISTS')
        self.event(operation='create-reserved',name=name,image=image)
        self.reserved_names[name] = image
        self.pending_names[name] = image
        limits = self.a['resourceLimits']
        cpus = format(limits['nanoCpus']/1_000_000_000, '.9g')
        args = ['docker','create','--pull=never','--name',name,
                '--label','dsh.sdk.operation='+self.a['operationId'],
                '--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
                '--cpus',cpus,'--memory',str(limits['memoryBytes']),
                '--memory-swap',str(limits['memoryBytes']),
                '--pids-limit',str(limits['pidsLimit']),
                '--storage-opt','size='+str(limits['storageBytes']),
                '--mount','type=bind,src='+str(self.root)+',dst=/work',
                '--mount','type=bind,src='+str(self.stages)+',dst=/producer,readonly',
                '--mount','type=bind,src='+self.a['cacheRoot']+',dst=/deps,readonly',
                '--workdir','/work/source','--entrypoint','/bin/bash',image,'/producer/'+stage]
        try:
            cid = self.command(args).decode().strip()
        except Exception:
            self._bind_uncertain(name, image)
            raise
        if not re.fullmatch(r'[a-f0-9]{64}',cid): raise ValueError('EXACT_BUILD_CONTAINER_ID_REQUIRED')
        self.containers.append((cid,image))
        self.pending_names.pop(name, None)
        info = json.loads(self.command(['docker','inspect',cid]))[0]
        if (info['Id']!=cid or info['Config']['Image']!=image
                or info['Config'].get('Labels',{}).get('dsh.sdk.operation')!=self.a['operationId']
                or info['HostConfig'].get('NetworkMode')!='none'
                or info['HostConfig'].get('NanoCpus')!=limits['nanoCpus']
                or info['HostConfig'].get('Memory')!=limits['memoryBytes']
                or info['HostConfig'].get('MemorySwap')!=limits['memoryBytes']
                or info['HostConfig'].get('PidsLimit')!=limits['pidsLimit']
                or str(info['HostConfig'].get('StorageOpt',{}).get('size'))!=str(limits['storageBytes'])):
            raise ValueError('FOREIGN_BUILD_CONTAINER')
        self.event(operation='container-bound',id=cid,image=image,network='none')
        self.command(['docker','start','--attach',cid],log=role+'.log')
        state = json.loads(self.command(['docker','inspect',cid]))[0]['State']
        if state.get('Running') or state.get('ExitCode')!=0:
            raise ValueError('BUILD_CONTAINER_NOT_SUCCESSFULLY_EXITED')
        self.event(operation='container-exited',id=cid,exitCode=state['ExitCode'])

    def execute(self):
        if sys.platform != 'linux': raise ValueError('DSO_LINUX_AGENT_REQUIRED')
        require_plain_ancestors(self.root, leaf_may_be_missing=True)
        if self.root.exists(): raise ValueError('PRODUCER_OPERATION_ROOT_ALREADY_EXISTS')
        workspace = verify_bounded_workspace(self.root.parent,
            maximum_bytes=self.a['resourceLimits']['storageBytes'],
            minimum_free_bytes=self.a['minimumFreeBytes'])
        cache = Path(self.a['cacheRoot'])
        if cache.is_symlink() or not cache.is_dir(): raise ValueError('OFFLINE_CACHE_REQUIRED')
        manifest_path = Path(self.a['cacheManifest'])
        manifest_raw = read_plain_file(manifest_path)
        if hashlib.sha256(manifest_raw).hexdigest()!=self.a['cacheManifestSha256']:
            raise ValueError('UNADMITTED_CACHE_MANIFEST')
        verify_cache(cache,manifest_raw)
        ca = Path(self.a['caFile'])
        ca_raw = read_plain_file(ca)
        if hashlib.sha256(ca_raw).hexdigest()!=self.a['caSha256']:
            raise ValueError('EXPLICIT_PUBLIC_CA_REQUIRED')
        if b'PRIVATE KEY' in ca_raw or b'-----BEGIN CERTIFICATE-----' not in ca_raw:
            raise ValueError('PUBLIC_CA_BUNDLE_REQUIRED')
        if digest_file(PRODUCER_PATH)!=self.a['producerSha256']:
            raise ValueError('PRODUCER_SOURCE_CHANGED')
        verifier = load_bound_verifier(self.a['verifierSha256'])
        for stage,sha in self.a['stageHashes'].items():
            if hashlib.sha256(read_plain_file(self.stages/stage)).hexdigest()!=sha: raise ValueError('PRODUCER_STAGE_CHANGED')
        if shutil.disk_usage(self.root.parent).free < self.a['minimumFreeBytes']:
            raise ValueError('PRODUCER_CAPACITY_NOT_ADMITTED')
        self.root.mkdir(mode=0o700); self.owns_root = True
        (self.root/'out').mkdir(); (self.root/'home').mkdir()
        (self.root/'host-home').mkdir(); (self.root/'empty-hooks').mkdir()
        self.event(operation='bounded-workspace-observed', **workspace)
        builder_id = self.image(self.a['builderImage']); manylinux_id = self.image(self.a['manylinuxImage'])
        git = ['git','-c','protocol.allow=never','-c','protocol.https.allow=always',
               '-c','credential.helper=','-c','http.emptyAuth=false','-c','http.delegation=none',
               '-c','http.proactiveAuth=none','-c','http.followRedirects=false',
               '-c','http.sslVerify=true','-c','http.sslBackend=openssl',
               '-c','http.sslCAInfo='+str(ca),'-c','core.hooksPath='+str(self.root/'empty-hooks'),
               '-c','core.autocrlf=false','-c','submodule.recurse=false']
        source = self.root/'source'
        self.command(git+['init',str(source)])
        self.command(git+['-C',str(source),'fetch','--depth=1',PUBLIC_SOURCE,SOURCE],log='public-source-fetch.log')
        self.command(git+['-C',str(source),'checkout','--detach',SOURCE])
        if (self.command(git+['-C',str(source),'rev-parse','HEAD']).decode().strip()!=SOURCE
                or self.command(git+['-C',str(source),'rev-parse','HEAD^{tree}']).decode().strip()!=SOURCE_TREE
                or digest_file(source/'pnpm-lock.yaml')!=PNPM_LOCK_SHA256):
            raise ValueError('UPSTREAM_SOURCE_CHANGED')
        self.event(operation='source-bound',commit=SOURCE,tree=SOURCE_TREE,
                   builderId=builder_id,manylinuxId=manylinux_id)
        self.container('prepare',self.a['builderImage'],'prepare.sh')
        self.container('manylinux',self.a['manylinuxImage'],'manylinux.sh')
        self.container('compile',self.a['builderImage'],'compile.sh')
        if self.command(git+['-C',str(source),'status','--porcelain','--untracked-files=no']).strip():
            raise ValueError('TRACKED_UPSTREAM_SOURCE_MUTATED')
        tools = _unique_json((self.root/'out/tools.json').read_bytes())
        sdk = (self.root/'out/wheels'/SDK_NAME).read_bytes()
        runtime = (self.root/'out/wheels'/RUNTIME_NAME).read_bytes()
        receipt = {'kind':'DSH_OFFICIAL_SDK_PRODUCER_V1','sourceCommit':SOURCE,'sourceTree':SOURCE_TREE,
            'version':'0.2.2a2','platform':'manylinux_2_28_x86_64','pnpmLockSha256':PNPM_LOCK_SHA256,
            'builderImage':self.a['builderImage'],'manylinuxImage':self.a['manylinuxImage'],
            'operationId':self.a['operationId'],'nodeVersion':tools['nodeVersion'],
            'pnpmVersion':tools['pnpmVersion'],'uvVersion':tools['uvVersion'],
            'sdkWheel':SDK_NAME,'runtimeWheel':RUNTIME_NAME,
            'sdkWheelSha256':hashlib.sha256(sdk).hexdigest(),'runtimeWheelSha256':hashlib.sha256(runtime).hexdigest(),
            'sdkWheelSize':len(sdk),'runtimeWheelSize':len(runtime)}
        raw = (json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode()
        # Internal consistency only; the eventual consumer must obtain this SHA
        # from the independently admitted retained CI receipt, not from the ZIP.
        verifier.verify_producer_pair(
            receipt_raw=raw,trusted_receipt_sha256=hashlib.sha256(raw).hexdigest(),
            sdk_raw=sdk,runtime_raw=runtime)
        (self.root/'out/producer-receipt.json').write_bytes(raw)
        self.event(operation='producer-output',receiptSHA256=hashlib.sha256(raw).hexdigest(),
                   applicationImageBound=False,liveOpenShellAccepted=False)
        return receipt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--admission',type=Path,required=True)
    parser.add_argument('--admission-sha256',required=True)
    args=parser.parse_args()
    # Never read generic credentials or the shared task PAT: this producer is a
    # credential-free child of the separately reviewed Azure job/executor.
    if args.admission.name!='producer-admission.json' or not re.fullmatch(r'[a-f0-9]{64}',args.admission_sha256):
        raise ValueError('EXACT_PRODUCER_ADMISSION_INPUT_REQUIRED')
    raw=read_plain_file(args.admission)
    if hashlib.sha256(raw).hexdigest()!=args.admission_sha256:
        raise ValueError('UNTRUSTED_PRODUCER_ADMISSION')
    producer=Producer(_unique_json(raw))
    try:
        producer.execute()
    finally:
        producer.retire()


if __name__=='__main__':
    try: main()
    except Exception as error:
        reason=str(error) if re.fullmatch(r'[A-Z0-9_]{1,80}',str(error)) else type(error).__name__
        print('SDK producer refused: '+reason,file=sys.stderr)
        raise SystemExit(2)
