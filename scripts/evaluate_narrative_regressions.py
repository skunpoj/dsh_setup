"""Check known narrative/citation substitutions in an unedited DSH response.

Exact branch/quote checks are regressions, not automatic semantic entailment.
The complete generated narrative still requires separate source review.
"""
import argparse
import json
from pathlib import Path
import re

CASES = {
    'ROLLBACK_HASH': ('scripts/promote_1m_runtimes.py', ['assert hashlib.sha256(original).hexdigest()', 'tmp.write_bytes(original)', 'assert profile.read_bytes()==original']),
    'MOUNT_PRESERVATION': ('scripts/promote_1m_runtimes.py', ["assert pod['volumes']==", "assert c['volumeMounts']=="]),
    'CONCURRENT_EDIT_REFUSAL': ('scripts/promote_1m_proxy.py', ["current = json.loads(kube('get', 'deploy', 'litellm'", "if current['spec'] != original['spec']:", "raise RuntimeError('Gateway changed after plan"]),
    'SIDECAR_INSERTION': ('scripts/promote_1m_proxy.py', ["pod['containers'].append(sidecar)"]),
    'TOKENIZER_CALL': ('scripts/long_context_callbacks.py', ['req = urllib.request.Request(TOKENIZER', ').open(req, timeout=120)']),
    'TRANSPORT_SCOPE': ('tests/test_managed_inference_transport.js', ["createManagedDispatcher(base,'http://litellm", 'assert.equal(seen[0][0].headersTimeout,3600000)', "for(const origin of ['https://github.com'", "assert.equal(seen.at(-1)[0],options)"]),
    'CACHE_PROBE_ABORT': ('scripts/long_context_callbacks.py', ['if isinstance(error, TimeoutError):', 'if aborted:', "raise CacheProbeMiss('Cold prefix probe cancelled')"]),
}


def evaluate(response, blocks):
    sources = {b['id']: b for b in blocks}
    claims = response.get('claim_checks', [])
    ids = [c.get('id') for c in claims]
    indexed = {c.get('id'): c for c in claims}
    narrative = []
    for sid, start, end in re.findall(r'\[(S\d+):L(\d+)(?:-L(\d+))?\]', response.get('report_markdown', '')):
        narrative.append((sid, int(start), int(end or start)))
    checks = []
    for case, (path, needles) in CASES.items():
        source = next(b for b in blocks if b['repo'] == 'DSH' and b['current'] and b['path'] == path)
        lines = source['content'].splitlines()
        # The rollback hash assertion also appears in backup reuse: choose the
        # occurrence inside the explicit restore branch, not the first match.
        floor = next(i for i, line in enumerate(lines, 1) if 'if restore:' in line) if case == 'ROLLBACK_HASH' else 1
        required = [next(i for i, line in enumerate(lines, 1) if i >= floor and needle in line) for needle in needles]
        claim = indexed.get(case, {}); citation = claim.get('citation') or {}
        start, end = citation.get('start_line'), citation.get('end_line')
        bounded = (citation.get('source_id') == source['id'] and type(start) is int and type(end) is int and
                   1 <= start <= end <= len(lines) and end-start < 12)
        quote = citation.get('quote', '')
        quote_ok = bounded and isinstance(quote, str) and 8 <= len(quote) <= 100 and quote in '\n'.join(lines[start-1:end])
        supported = bounded and all(start <= line <= end for line in required)
        covered = all(any(sid == source['id'] and lo <= line <= hi and hi-lo < 12 for sid, lo, hi in narrative) for line in required)
        checks.append({'id': case, 'sourceId': source['id'], 'requiredLines': required,
                       'exactShortQuote': bool(quote_ok), 'actualBranchCited': bool(supported),
                       'actualBranchCoveredInNarrative': covered, 'passed': bool(quote_ok and supported and covered)})
    return {'passed': set(ids) == set(CASES) and len(ids) == len(set(ids)) == len(CASES) and all(c['passed'] for c in checks),
            'checks': checks, 'limitations': 'Known source-branch substitutions only. Passing does not establish every narrative claim or general model accuracy.'}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--directory', type=Path, required=True)
    a = ap.parse_args(); p = a.directory
    result = evaluate(json.loads((p/'model-response.json').read_text(encoding='utf-8')),
                      json.loads((p/'selected-sources.json').read_text(encoding='utf-8')))
    (p/'narrative-regression-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__': main()
