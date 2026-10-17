"""Prepare source excerpts for actual narrative review; does not score entailment."""
import argparse
import json
from pathlib import Path
import re


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--directory', type=Path, required=True)
    a = ap.parse_args(); p = a.directory
    report = json.loads((p/'model-response.json').read_text(encoding='utf-8'))
    sources = {b['id']: b for b in json.loads((p/'selected-sources.json').read_text(encoding='utf-8'))}
    text = report['report_markdown']; entries = []
    for match in re.finditer(r'\[(S\d+):L(\d+)(?:-L(\d+))?\]', text):
        sid, start, end = match.groups(); start, end = int(start), int(end or start)
        source = sources.get(sid)
        lines = source['content'].splitlines() if source else []
        entries.append({'citation': match.group(0),
            'precedingText': text[max(0, text.rfind('\n\n', 0, match.start())):match.end()].strip(),
            'path': source['path'] if source else None,
            'revision': source['revision'] if source else None,
            'current': source['current'] if source else None,
            'sourceLines': '\n'.join(f'L{i}: {line}' for i, line in enumerate(lines, 1) if start <= i <= end),
            'reviewStatus': 'not reviewed'})
    (p/'report-citation-excerpts.json').write_text(json.dumps(entries, indent=2), encoding='utf-8')
    print(json.dumps({'citations': len(entries), 'status': 'Awaiting source review; existing lines do not establish entailment.'}))


if __name__ == '__main__': main()
