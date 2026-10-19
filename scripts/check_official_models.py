"""Track public DeepSeek model revisions; generate metadata-only review patches.

Never contacts inference, uses credentials, or changes the managed model catalog.
"""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://api-docs.deepseek.com/quick_start/pricing/'
CHANGELOG = 'https://api-docs.deepseek.com/updates/'
MAX_BYTES = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Official documentation redirects require review')


def fetch_document(url):
    if url not in (SOURCE, CHANGELOG):
        raise ValueError('Only fixed official DeepSeek documentation URLs allowed')
    with urllib.request.build_opener(NoRedirect).open(url, timeout=20) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('Official document size exceeds limit')
    return body.decode('utf-8')


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = None; self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        elif tag in ('td', 'th') and self.row is not None: self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row); self.row = None


def parse_models(pricing, changelog, reviewed=()):
    parser = Tables(); parser.feed(pricing)
    aliases = []; versions = []
    for row in parser.rows:
        if not row: continue
        key = row[0].strip().upper()
        if key == 'MODEL':
            if aliases: raise ValueError('Ambiguous official model table')
            for cell in row[1:]:
                found = re.findall(r'\bdeepseek-[a-z0-9][a-z0-9.-]*\b', cell)
                if len(found) != 1: raise ValueError('Unrecognized official model identifier')
                aliases.append(found[0])
        if key == 'MODEL VERSION':
            if versions: raise ValueError('Ambiguous official version row')
            versions = row[1:]
    if not aliases or len(aliases) != len(versions) or len(set(aliases)) != len(aliases):
        raise ValueError('Official model/version table missing or inconsistent')
    result = []
    for alias, version in zip(aliases, versions):
        if not re.fullmatch(r'DeepSeek-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*', version):
            raise ValueError('Unrecognized official model revision')
        # Corroborate the published revision in the independent official changelog.
        if version not in changelog and (alias, version) not in reviewed:
            raise ValueError('Model revision lacks official changelog corroboration')
        result.append({'apiModel': alias, 'officialRevision': version})
    return sorted(result, key=lambda row: row['apiModel'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / 'config/official-deepseek-models.json'
    try:
        old = json.loads(baseline.read_text(encoding='utf-8'))
        reviewed = {(row['apiModel'], row['officialRevision']) for row in old['models']}
        pricing, changelog = fetch_document(SOURCE), fetch_document(CHANGELOG)
        observed = {'schemaVersion': 1, 'source': SOURCE, 'changelog': CHANGELOG,
                    'models': parse_models(pricing, changelog, reviewed)}
        before = baseline.read_text(encoding='utf-8'); after = json.dumps(observed, indent=2) + '\n'
        patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                      fromfile='a/config/official-deepseek-models.json', tofile='b/config/official-deepseek-models.json')) if old != observed else ''
        (args.output_dir / 'official-model-update.patch').write_text(patch, encoding='utf-8')
        (args.output_dir / 'official-model-observed.json').write_text(after, encoding='utf-8')
        receipt = {'status': 'update-review-required' if patch else 'unchanged',
                   'checkedAtUTC': datetime.now(timezone.utc).isoformat(),
                   'observed': observed, 'pricingSHA256': hashlib.sha256(pricing.encode()).hexdigest(),
                   'changelogSHA256': hashlib.sha256(changelog.encode()).hexdigest(),
                   'patchGenerated': bool(patch), 'runtimeModelChanged': False,
                   'internalBackendRevisionVerified': False, 'inferenceRequested': False,
                   'nextAction': 'Review metadata patch; independently qualify backend availability and revision before any runtime model change'}
    except Exception as error:
        receipt = {'status': 'blocked-official-model-inspection', 'errorType': type(error).__name__,
                   'error': str(error)[:300], 'runtimeModelChanged': False, 'inferenceRequested': False}
        (args.output_dir / 'official-models.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
        raise
    (args.output_dir / 'official-models.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__': main()
