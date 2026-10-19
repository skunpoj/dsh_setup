"""Build a public documentation allowlist; never include workspace or auth data."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'docs'


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {'href', 'src'} and value:
                self.links.append(value)


def build(output):
    output.mkdir(parents=True, exist_ok=False)
    pending = ['DSH_USER_MANUAL.html', 'DSH_GUIDED_TOUR.html', 'DSH_PLATFORM_GUIDE.html', 'DSH_SECURITY_ENVIRONMENT_AND_FEATURES.html',
               'DSH_SETUP_AND_STRESS_TEST_GUIDE.html', 'MANAGED_CLIENT_SUPPORT.html']
    entries = {}
    total = 0
    while pending:
        name = pending.pop()
        if name in entries:
            continue
        source = (ROOT / name).resolve()
        if not source.is_relative_to(ROOT.resolve()) or not source.is_file():
            raise ValueError('Documentation dependency is missing or outside docs: ' + name)
        if source.suffix not in {'.html', '.md', '.json', '.png', '.svg'}:
            continue
        content = source.read_bytes()
        total += len(content)
        if len(content) > 8*1024*1024 or total > 128*1024*1024:
            raise ValueError('Documentation bundle exceeds its bounded size')
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        entries[name] = {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        if source.suffix == '.html':
            parser = Links()
            parser.feed(content.decode('utf-8'))
            for link in parser.links:
                url = urlsplit(link)
                if url.scheme or url.netloc or not url.path or url.path.startswith('/'):
                    continue
                child = (source.parent / unquote(url.path)).resolve()
                if child.is_relative_to(ROOT.resolve()) and child.suffix in {'.html', '.md', '.json', '.png', '.svg'}:
                    pending.append(child.relative_to(ROOT.resolve()).as_posix())
    manifest = {'files': entries, 'bytes': total}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    return {'files': len(entries), 'bytes': total}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().output)))
