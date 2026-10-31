"""Check a public source tree for common disclosures; never print matching values.

This is a pattern guard, not a proof of secrecy or a video/audio review.
"""
import argparse, hashlib, io, re, zipfile
from pathlib import Path

PATTERNS = {
    'access-token': r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|sk-[a-f0-9]{40,}|kubeconfig-u-[A-Za-z0-9]+:',
    'private-key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'personal-path': r'[A-Za-z]:[/\\]Users[/\\](?!Public\b)[^/\\\s]+|/home/(?!developer\b|dsh\b)[A-Za-z0-9_.-]+/',
    'credential-in-url': r'://[^\s/:]+:[^\s/@]+@',
    'organization-host': r'\b(?:[A-Za-z0-9_-]+\.)*' + 'bot' + r'\.or\.th\b|\b' + 'dso' + r'reg[A-Za-z0-9_.-]*\b',
}
# Exact existing public binary: complete embedded keys were compared with
# Mbed TLS v2.28.9 library/certs.c. These are public TLS self-test fixtures.
# A changed binary must be reviewed again; this exception is digest-bound.
PUBLIC_TTYD_SHA256 = '8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55'
MAX_MEMBER = 8 * 1024 * 1024
MAX_ARCHIVE = 32 * 1024 * 1024

def scan_bytes(name, data):
    findings = []
    text = data.decode('utf-8', errors='replace')
    for kind, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text, re.IGNORECASE if kind == 'organization-host' else 0):
            if kind == 'private-key' and name == 'vendor/ttyd' and hashlib.sha256(data).hexdigest() == PUBLIC_TTYD_SHA256:
                continue
            # Exact deliberately invalid URL used by the public renderer test.
            if kind == 'credential-in-url' and name == 'gpu-stack/tests/test_portable.py':
                if text[match.start():].startswith(''.join(['://', 'user', ':', 'password', '@', 'gpu.example.internal'])):
                    continue
            findings.append((name, kind, text.count('\n', 0, match.start()) + 1))
    return findings

def scan(root):
    findings = []
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root)
        if any(part in {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv'} for part in rel.parts):
            continue
        if p.is_symlink():
            findings.append((str(rel), 'unreviewed-symlink', 0)); continue
        if not p.is_file():
            continue
        name = rel.as_posix()
        data = p.read_bytes()
        findings.extend(scan_bytes(name, data))
        if p.suffix.lower() in {'.zip', '.docx', '.pptx', '.xlsx'}:
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    total = 0
                    for item in archive.infolist():
                        if item.is_dir(): continue
                        total += item.file_size
                        if item.file_size > MAX_MEMBER or total > MAX_ARCHIVE:
                            findings.append((name, 'archive-review-required', 0)); break
                        findings.extend(scan_bytes(name + '!' + item.filename, archive.read(item)))
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                findings.append((name, 'unreadable-archive', 0))
    return findings

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, nargs='?', default=Path.cwd())
    findings = scan(parser.parse_args().root)
    for name, kind, line in findings:
        print(f'{name}:{line}: {kind}')
    if findings: raise SystemExit(1)
    print('Public-source pattern guard passed; history, video/audio and semantic review are separate.')
