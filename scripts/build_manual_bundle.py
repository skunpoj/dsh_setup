"""Build a public documentation allowlist; never include workspace or auth data."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'docs'
PUBLIC_SUFFIXES = {'.html', '.md', '.json', '.png', '.svg', '.txt', '.vtt', '.mp4', '.pdf', '.pptx'}
# Publication holds override every traversal path, including previously served links.
UNPUBLISHED_DOCUMENTS = frozenset({'sdk-qualification-composition/verify_mounts_redesign.md'})
INTERNAL_RUNBOOK_STEMS = frozenset(['credential_operations', 'dsh_setup_and_stress_test_guide', 'enterprise_root_ca_setup', 'infra_admin_p2p_note_20261030', 'install', 'installation_walkthrough', 'operations_and_troubleshooting_manual', 'sdk-qualification-composition/d11_d13_openshell_proposal', 'sdk-qualification-composition/p0_design_openshell_lane', 'sdk-qualification-composition/p3_runner_readme', 'sdk-qualification-composition/verify_mounts_redesign'])

MAX_FILE_BYTES = 64 * 1024 * 1024


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {'href', 'src'} and value:
                self.links.append(value)


def validate_entrypoints(entrypoints):
    """An explicit public selection replaces, rather than expands, private defaults."""
    if not isinstance(entrypoints, list) or not 1 <= len(entrypoints) <= 500:
        raise ValueError('Entrypoints must be a nonempty list of at most 500 public paths')
    for name in entrypoints:
        if not isinstance(name, str) or not name or '\\' in name or ':' in name or any(ord(c) < 32 for c in name):
            raise ValueError('Entrypoints must be canonical relative public paths')
        url = urlsplit(name)
        path = PurePosixPath(name)
        if (url.scheme or url.netloc or url.query or url.fragment or path.is_absolute()
                or '..' in path.parts or path.as_posix() != name
                or path.suffix not in PUBLIC_SUFFIXES):
            raise ValueError('Entrypoints must be canonical relative public paths')
    if len(set(entrypoints)) != len(entrypoints):
        raise ValueError('Entrypoints must be unique')
    return list(entrypoints)


def build(output, git_ref=None, entrypoints=None):
    selected = validate_entrypoints(entrypoints) if entrypoints is not None else None
    if output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Documentation output must stay outside the read-only docs input')
    commit = None
    if git_ref is not None:
        commit = subprocess.check_output(['git', 'rev-parse', '--verify', '--end-of-options',
                                          git_ref+'^{commit}'], cwd=ROOT.parent).decode().strip()
        if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
            raise ValueError('A complete Git commit is required')
    output.mkdir(parents=True, exist_ok=False)
    pending = [
        'DSH_USER_MANUAL.html', 'DSH_GUIDED_TOUR.html', 'DSH_PLATFORM_GUIDE.html',
        'DSH_SECURITY_ENVIRONMENT_AND_FEATURES.html',
        'MANAGED_CLIENT_SUPPORT.html',
    ]
    # Keep existing optional top-level/manual assets explicit when the selected
    # source edition contains them. Link traversal adds dependencies, but an
    # index revision must not silently retire a current guide, source record,
    # image or captioned video. Minimal test fixtures need not define optional
    # production assets.
    retained = [
        'COURSE_GUIDE.md', 'DSH_CURRENT_GUIDE.md', 'DSH_CURRENT_GUIDE.source.json',
        'presentations/guarding-the-value-stream/Guarding_the_Value_Stream.pdf',
        'presentations/guarding-the-value-stream/Guarding_the_Value_Stream.pptx',
        'presentations/guarding-the-value-stream/Guarding_the_Value_Stream_Story.pdf',
        'BANKING_AGENT_REVIEW.html', 'FEATURE_CONTROL_TRACEABILITY.html',
        'DSH_SECURITY_ARCHITECTURE_AND_CONTROLS.html',
        'DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md',
        'DSH_SECURITY_ENVIRONMENT_AND_FEATURES.md', 'MANAGED_CLIENT_SUPPORT.md',
        'SHARED_PLATFORM_GUIDE.md', 'THREE_RISK_CONTROLS.md',
        'USER_CREDENTIAL_MANAGEMENT.md', 'images/platform/self-service-packages.png',
        'videos/credential-management-fola-transcript.txt',
        'videos/credential-management-fola.mp4', 'videos/credential-management-fola.vtt',
        'brand/logo.png', 'brand/multiharness-light.svg', 'brand/multiharness-dark.svg', 'brand/seal-light.png', 'brand/seal-dark.png',
    ]
    if selected is not None:
        pending = selected
        retained = []
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
        if name.casefold().startswith('internal-runbooks/') or name.casefold() in UNPUBLISHED_DOCUMENTS or str(Path(name).with_suffix('')).replace('\\', '/').casefold() in INTERNAL_RUNBOOK_STEMS:
            raise ValueError('Documentation publication hold: ' + name)
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
    parser.add_argument('--entrypoints-json', type=Path, help='Explicit reviewed public root list; replaces default and retained roots')
    args=parser.parse_args()
    entrypoints = json.loads(args.entrypoints_json.read_text(encoding='utf-8')) if args.entrypoints_json else None
    print(json.dumps(build(args.output, args.git_ref, entrypoints)))
