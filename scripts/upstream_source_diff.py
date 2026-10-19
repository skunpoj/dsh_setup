"""Bounded data-only npm archive inspection; never installs or executes packages."""
from concurrent.futures import ThreadPoolExecutor
import base64
import gzip
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import tarfile
import time
import urllib.parse
import urllib.request

MAX_DOWNLOAD = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_MEMBERS = 12000
MAX_FILE = 8 * 1024 * 1024
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?')


def validate_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'registry.npmjs.org' or p.username or p.password or p.fragment or p.query:
        raise ValueError('Only public HTTPS registry.npmjs.org URLs are allowed')
    if not p.path.startswith(('/@deepseek-ai/', '/-/package/@deepseek-ai/')):
        raise ValueError('Unexpected registry package path')
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Registry redirects are refused')


def fetch(url, limit=MAX_DOWNLOAD):
    validate_url(url)
    deadline = time.monotonic() + 45
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        chunks=[]; size=0
        while True:
            if time.monotonic() > deadline:
                raise ValueError('Registry download deadline exceeded')
            chunk=response.read(min(65536, limit + 1 - size))
            if not chunk: break
            size += len(chunk)
            if size > limit: raise ValueError('Registry download exceeds size limit')
            chunks.append(chunk)
        return b''.join(chunks)


def metadata(name, version):
    if not re.fullmatch(r'@deepseek-ai/dsh(?:-[a-z0-9-]+)?', name) or not VERSION.fullmatch(version):
        raise ValueError('Unsafe package identity/version')
    value=json.loads(fetch('https://registry.npmjs.org/'+name+'/'+version, 2*1024*1024))
    if value.get('name') != name or value.get('version') != version:
        raise ValueError('Registry package identity/version mismatch')
    return value


def archive_files(blob, integrity, wanted):
    if not re.fullmatch(r'sha512-[A-Za-z0-9+/]{86}==', integrity or ''):
        raise ValueError('Missing or invalid SHA512 integrity')
    if base64.b64encode(hashlib.sha512(blob).digest()).decode() != integrity[7:]:
        raise ValueError('Archive SHA512 integrity mismatch')
    # Bound the entire decompressed tar, including PAX/long-name headers that
    # tarfile consumes before yielding a member to the validation loop.
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as compressed:
        expanded=compressed.read(MAX_EXPANDED+1)
    if len(expanded)>MAX_EXPANDED: raise ValueError('Archive expanded size limit exceeded')
    found={}; seen=set(); total=0
    with tarfile.open(fileobj=io.BytesIO(expanded), mode='r:') as archive:
        for index, member in enumerate(archive):
            if index >= MAX_MEMBERS: raise ValueError('Archive member limit exceeded')
            parts=PurePosixPath(member.name).parts
            if '\\' in member.name or member.name.startswith('/') or '..' in parts or not parts or parts[0] != 'package' or ':' in member.name:
                raise ValueError('Unsafe archive path')
            if member.name in seen: raise ValueError('Duplicate archive path')
            seen.add(member.name)
            if not member.isdir() and not member.isfile(): raise ValueError('Archive links/special files refused')
            total += member.size
            if total > MAX_EXPANDED or member.size > MAX_FILE: raise ValueError('Archive expanded size limit exceeded')
            key='/'.join(parts[1:])
            if member.isfile() and key in wanted:
                found[key]=archive.extractfile(member).read(MAX_FILE+1)
    return found


def inspect_candidate(package, contract):
    """Compare only reviewed targets; byte equality is not semantic acceptance."""
    deadline=time.monotonic()+180
    rootdist=package.get('dist',{})
    rootfiles=archive_files(fetch(validate_url(rootdist.get('tarball',''))),rootdist.get('integrity'),{'package.json'})
    rootidentity=json.loads(rootfiles.get('package.json',b'{}'))
    if rootidentity.get('name') != '@deepseek-ai/dsh' or rootidentity.get('version') != package['version']:
        raise ValueError('Root archive package identity/version mismatch')
    if any(rootidentity.get(field,{}) != package.get(field,{}) for field in ('dependencies','optionalDependencies','peerDependencies')):
        raise ValueError('Root archive dependency metadata mismatch')
    grouped={}
    for target in contract['targets']:
        module, relative=target['path'].split('/',1)
        if '..' in PurePosixPath(relative).parts or '\\' in relative or relative.startswith('/'):
            raise ValueError('Unsafe contract target')
        grouped.setdefault(module, []).append((relative,target))
    rows=[]; packages=[]
    # Modules are normally transitive through dsh-base, not root dependencies.
    # Resolve exact official dependency declarations as data, without npm install.
    dependencies={}; cache={}; queue=[(package,0)]; visited=set()
    wanted_names={'@deepseek-ai/'+module for module in grouped}
    while queue and not wanted_names.issubset(dependencies):
        if time.monotonic()>deadline: raise ValueError('Source inspection deadline exceeded')
        parent,depth=queue.pop(0)
        if depth > 8: raise ValueError('Dependency graph depth limit exceeded')
        pending=[]
        declared={}
        for field in ('peerDependencies','dependencies','optionalDependencies'):
            declared.update(parent.get(field,{}))
        for name,version in declared.items():
            if not name.startswith('@deepseek-ai/dsh'): continue
            if name in wanted_names:
                if name in dependencies and dependencies[name] != version:
                    raise ValueError('Ambiguous official target dependency versions')
                dependencies[name]=version
            if isinstance(version,str) and VERSION.fullmatch(version):
                pending.append((name,version))
        if wanted_names.issubset(dependencies): break
        batch=[]
        for name,version in pending:
            if time.monotonic()>deadline: raise ValueError('Source inspection deadline exceeded')
            key=(name,version)
            if key in visited: continue
            visited.add(key);batch.append(key)
            if len(visited)>256: raise ValueError('Dependency graph package limit exceeded; unresolved targets: '+','.join(sorted(wanted_names-set(dependencies))))
        with ThreadPoolExecutor(max_workers=8) as pool:
            infos=list(pool.map(lambda key:metadata(*key),batch))
        for key,info in zip(batch,infos):
            cache[key]=info;queue.append((info,depth+1))
        missing=wanted_names-set(dependencies)
        queue.sort(key=lambda item:-sum(len(missing.intersection(item[0].get(field,{}))) for field in ('dependencies','optionalDependencies','peerDependencies')))
    for module, targets in grouped.items():
        if time.monotonic()>deadline: raise ValueError('Source inspection deadline exceeded')
        name='@deepseek-ai/'+module
        version=dependencies.get(name)
        if not version or not VERSION.fullmatch(version):
            rows.extend({'path':t['path'],'status':'missing-package' if not version else 'unresolved-version','declaredVersion':version} for _,t in targets)
            continue
        info=cache.get((name,version)) or metadata(name,version)
        dist=info.get('dist',{}); url=validate_url(dist.get('tarball',''))
        files=archive_files(fetch(url),dist.get('integrity'),{p for p,_ in targets}|{'package.json'})
        identity=json.loads(files.get('package.json',b'{}'))
        if identity.get('name') != name or identity.get('version') != version: raise ValueError('Archive package identity/version mismatch')
        packages.append({'name':name,'version':version,'integrity':dist['integrity']})
        for relative,target in targets:
            actual=hashlib.sha256(files[relative]).hexdigest() if relative in files else None
            contract_matches=(not target.get('packageVersion') or version==target['packageVersion']) and (not target.get('registryIntegrity') or dist['integrity']==target['registryIntegrity'])
            rows.append({'path':target['path'],'status':'missing' if actual is None else 'changed' if actual!=target['sha256'] else 'changed-package-contract' if not contract_matches else 'compatible','expectedSha256':target['sha256'],'actualSha256':actual,'packageVersion':version})
    reviewed=package['version']==contract.get('baselineVersion')
    allowed=reviewed and bool(rows) and all(row['status']=='compatible' for row in rows)
    return {'schemaVersion':1,'reviewedVersion':contract.get('baselineVersion'),'candidateVersion':package['version'],'reviewedCandidate':reviewed,'buildAllowed':allowed,'status':'reviewed-source-compatible' if allowed else 'blocked-source-review-required','targets':rows,'packages':packages,'nextAction':'Qualify checked-out reviewed port' if allowed else 'Review changed/missing paths, port overlays and tests, update reviewed contracts in a human-reviewed PR; never approve hashes automatically','packageCodeExecuted':False}
