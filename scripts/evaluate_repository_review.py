"""Check answers and citations against a frozen, locally retained source corpus.

Mechanical checks do not certify narrative entailment or general model quality.
"""
import argparse
import json
from pathlib import Path
import re


def evaluate(result, key, blocks):
    raw = result.get('assistantText', '').strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
    report = json.loads(raw)
    sources = {b['id']: b for b in blocks}
    answers = report.get('answers', [])
    ids = [a.get('id') for a in answers]
    indexed = {a.get('id'): a for a in answers}
    checks = []
    for expected in key:
        answer = indexed.get(expected['id'], {})
        citation = answer.get('citation') or {}
        source = sources.get(citation.get('source_id'))
        start, end = citation.get('start_line'), citation.get('end_line')
        bounded = bool(source and type(start) is int and type(end) is int and
            1 <= start <= end <= len(source['content'].splitlines()) and end-start < 12)
        quote = citation.get('quote', '')
        cited = '\n'.join(source['content'].splitlines()[start-1:end]) if bounded else ''
        quote_ok = isinstance(quote, str) and 8 <= len(quote) <= 200 and quote in cited
        expected_source = citation.get('source_id') == expected['sourceId']
        support = bounded and expected_source and start <= expected['supportLine'] <= end
        value = str(answer.get('value', '')).strip().lower().replace(',', '')
        correct = value == expected['expectedValue'].lower().replace(',', '')
        checks.append({'id': expected['id'], 'value': answer.get('value'),
            'expectedValue': expected['expectedValue'], 'correct': correct,
            'citationRangeValid': bounded, 'quoteExact': quote_ok,
            'quoteCharacters': len(quote) if isinstance(quote, str) else None,
            'correctCurrentSourceAndSupportingLine': support,
            'passed': bool(correct and support and quote_ok)})
    text = report.get('report_markdown', '')
    malformed = [token for token in re.findall(r'\[S\d+:[^\]]*\]', text)
                 if not re.fullmatch(r'\[S\d+:L\d+(?:-L\d+)?\]', token)]
    citations = []
    for source_id, start, end in re.findall(r'\[(S\d+):L(\d+)(?:-L(\d+))?\]', text):
        source = sources.get(source_id); start, end = int(start), int(end or start)
        valid = bool(source and 1 <= start <= end <= len(source['content'].splitlines()) and end-start < 12)
        citations.append({'sourceId': source_id, 'start': start, 'end': end, 'rangeValid': valid})
    words = len(re.findall(r"\b[\w'-]+\b", text))
    distinct = len({c['sourceId'] for c in citations if c['rangeValid']})
    distinct_paths = len({(sources[c['sourceId']]['repo'], sources[c['sourceId']]['path'])
        for c in citations if c['rangeValid']})
    usage = result.get('lastUsage') or {}
    passed = (len(ids) == len(set(ids)) == len(key) and all(c['passed'] for c in checks)
        and words >= 1000 and distinct >= 8 and bool(citations) and not malformed and all(c['rangeValid'] for c in citations)
        and usage.get('inputTokens', 0) >= 950000 and usage.get('outputTokens', 0) >= 2000
        and result.get('persistedPromptMatches') is True and result.get('status') == 'completed')
    return {'mechanicalAcceptancePassed': passed, 'answers': checks,
        'correctValues': sum(c['correct'] for c in checks),
        'supportedAnswerCitations': sum(c['passed'] for c in checks),
        'questionCount': len(key), 'reportWords': words, 'reportCitations': citations,
        'distinctReportSources': distinct, 'usage': usage,
        'distinctReportPaths': distinct_paths, 'requestedWordRangeMet': 1400 <= words <= 1800,
        'malformedReportCitations': malformed,
        'limitations': 'Report citation ranges are mechanically checked; narrative entailment and operational conclusions require separate human/source review. This is one task-specific sample, not general accuracy.'}, report


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--directory', type=Path, required=True)
    a = ap.parse_args(); p = a.directory
    result = json.loads((p/'long-result.json').read_text(encoding='utf-8'))
    checks, report = evaluate(result, json.loads((p/'answer-key.json').read_text()),
        json.loads((p/'selected-sources.json').read_text()))
    (p/'accuracy-evaluation.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    (p/'model-review.md').write_text(report['report_markdown'], encoding='utf-8')
    (p/'model-response.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: checks[k] for k in ['mechanicalAcceptancePassed', 'correctValues',
        'supportedAnswerCitations', 'questionCount', 'reportWords', 'distinctReportSources', 'usage']}))


if __name__ == '__main__': main()
