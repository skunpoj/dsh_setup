"""Fail closed unless both mechanical checks and source review are complete.

This does not automate semantic entailment. A reviewer must inspect the actual
model output and cited sources, and bind the review to that output's hash.
"""
import argparse
import hashlib
import json
from pathlib import Path


def assess(result, mechanical, review):
    digest = hashlib.sha256(result.get('assistantText', '').encode()).hexdigest()
    findings = review.get('findings')
    conditions = {
        'mechanicalChecksPassed': mechanical.get('mechanicalAcceptancePassed') is True,
        'requestedWordRangeMet': mechanical.get('requestedWordRangeMet') is True,
        'revisionQuoteLimitMet': bool(mechanical.get('answers')) and all(
            type(c.get('quoteCharacters')) is int and 8 <= c['quoteCharacters'] <= 160
            for c in mechanical.get('answers', [])),
        'reviewBoundToActualOutput': review.get('assistantTextSHA256') == digest,
        'sourceReviewCompleted': review.get('completed') is True,
        'noUnresolvedSourceFindings': isinstance(findings, list) and not findings,
        'allMaterialClaimsReviewed': review.get('allMaterialClaimsReviewed') is True,
        'priorDefectsIndividuallyReviewed': set(review.get('priorFindingChecks', {})) ==
            {'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7'} and
            all(v.get('resolved') is True for v in review.get('priorFindingChecks', {}).values()),
    }
    return {'accepted': all(conditions.values()), 'conditions': conditions,
            'assistantTextSHA256': digest,
            'scope': 'One frozen-source task. Mechanical citation checks plus recorded source review; not general accuracy or operational/security certification.'}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--directory', type=Path, required=True)
    a = ap.parse_args(); p = a.directory
    load = lambda n: json.loads((p/n).read_text(encoding='utf-8'))
    review = load('manual-review.json') if (p/'manual-review.json').exists() else {}
    value = assess(load('long-result.json'), load('accuracy-evaluation.json'), review)
    (p/'revision-acceptance.json').write_text(json.dumps(value, indent=2), encoding='utf-8')
    print(json.dumps(value))


if __name__ == '__main__': main()
