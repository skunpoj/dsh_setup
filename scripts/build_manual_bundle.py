"""Build a public documentation allowlist; never include workspace or auth data."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'docs'
PUBLIC_SUFFIXES = {'.html', '.md', '.json', '.png', '.svg', '.txt', '.vtt', '.mp4', '.pdf', '.pptx'}
MAX_FILE_BYTES = 64 * 1024 * 1024


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {'href', 'src'} and value:
                self.links.append(value)


def build(output, git_ref=None):
    commit = None
    if git_ref is not None:
        commit = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options',
                                          git_ref+'^{commit}'], cwd=ROOT.parent).decode().strip()
        if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
            raise ValueError('A complete Git commit is required')
    output.mkdir(parents=True, exist_ok=False)
    pending = [
        'DSH_USER_MANUAL.html', 'DSH_GUIDED_TOUR.html', 'DSH_PLATFORM_GUIDE.html',
        'DSH_SECURITY_ENVIRONMENT_AND_FEATURES.html', 'DSH_SETUP_AND_STRESS_TEST_GUIDE.html',
        'MANAGED_CLIENT_SUPPORT.html',
    ]
    # Keep existing optional top-level/manual assets explicit when the selected
    # source edition contains them. Link traversal adds dependencies, but an
    # index revision must not silently retire a current guide, source record,
    # image or captioned video. Minimal test fixtures need not define optional
    # production assets.
    retained = [
        'COURSE_GUIDE.md', 'DSH_CURRENT_GUIDE.md', 'DSH_CURRENT_GUIDE.source.json',
        'DSH_SECURITY_ARCHITECTURE_AND_CONTROLS.html',
        'DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md',
        'DSH_SECURITY_ENVIRONMENT_AND_FEATURES.md', 'MANAGED_CLIENT_SUPPORT.md',
        'SHARED_PLATFORM_GUIDE.md', 'THREE_RISK_CONTROLS.md',
        'USER_CREDENTIAL_MANAGEMENT.md', 'images/platform/self-service-packages.png',
        'videos/credential-management-fola-transcript.txt',
        'videos/credential-management-fola.mp4', 'videos/credential-management-fola.vtt',
        'brand/logo.png',
    ]
    for name in retained:
        if commit:
            present = subprocess.run(
                ['git', 'cat-file', '-e', commit+':./docs/'+name], cwd=ROOT.parent,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode == 0
        else:
            present = (ROOT / name).is_file()
        if present:
            pending.append(name)
    entries = {}
    total = 0
    while pending:
        name = pending.pop()
        if name in entries:
            continue
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT.resolve()) or not source.is_file():
            raise ValueError('Documentation dependency is missing or outside docs: ' + name)
        if source.suffix not in PUBLIC_SUFFIXES:
            continue
        # Git blobs avoid Windows checkout/archive newline conversion. A
        # publication must identify the exact committed bytes, not a text-mode
        # subprocess or an independently modified working copy.
        # ':./docs/' is relative to cwd, so this works at any repository depth.
        content = (subprocess.check_output(['git', 'show', commit+':./docs/'+name], cwd=ROOT.parent)
                   if commit else source.read_bytes())
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > 128*1024*1024:
            raise ValueError('Documentation bundle exceeds its bounded size')
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries[name] = {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        if source.suffix == '.html':
            parser = Links()
            parser.feed(content.decode('utf-8'))
            for link in parser.links:
                url = urlsplit(link)
                if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
                    continue
                child = (source.parent / unquote(url.path)).resolve()
                if child.is_relative_to(ROOT.resolve()) and child.suffix in PUBLIC_SUFFIXES:
                    pending.append(child.relative_to(ROOT.resolve()).as_posix())
    manifest = {'files': entries, 'bytes': total}
    if commit:
        manifest['sourceCommit'] = commit
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return {'files': len(entries), 'bytes': total}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--git-ref', help='Publish exact committed blobs, avoiding checkout newline conversion')
    args=parser.parse_args()
    print(json.dumps(build(args.output, args.git_ref)))
