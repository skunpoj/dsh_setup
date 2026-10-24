"""Produce a candidate pin patch as evidence, without applying or approving it."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?')


def propose(docker, detection, comparison):
    candidate = detection['candidateVersion']
    if not VERSION.fullmatch(candidate): raise ValueError('Invalid candidate version')
    pins = re.findall(r'^ARG DSH_VERSION=(\S+)$', docker, re.M)
    if len(pins) != 1 or pins[0] != detection['sourcePackagePin']:
        raise ValueError('Detection source pin does not match current Dockerfile')
    if comparison['candidateVersion'] != candidate:
        raise ValueError('Comparison belongs to a different candidate')
    after = re.sub(r'^ARG DSH_VERSION=\S+$', 'ARG DSH_VERSION='+candidate, docker, flags=re.M)
    patch = ''.join(difflib.unified_diff(docker.splitlines(True), after.splitlines(True),
                                       fromfile='a/Dockerfile', tofile='b/Dockerfile'))
    return patch, {'candidateVersion': candidate, 'sourcePin': pins[0], 'patchGenerated': bool(patch),
                   'buildAllowed': comparison.get('buildAllowed') is True,
                   'applied': False, 'contractsChanged': False, 'deploymentPerformed': False,
                   'dockerfileSHA256': hashlib.sha256(docker.encode()).hexdigest(),
                   'status': 'source-port-review-required' if patch else 'unchanged',
                   'nextAction': 'Candidate patch is incomplete until source contracts, SDK and tests are reviewed; never apply a pin-only patch as release approval'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--detection', type=Path, required=True); ap.add_argument('--comparison', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True); args=ap.parse_args()
    patch, receipt=propose((ROOT/'Dockerfile').read_text(encoding='utf-8'),
                          json.loads(args.detection.read_text(encoding='utf-8')),
                          json.loads(args.comparison.read_text(encoding='utf-8')))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'release-candidate.patch').write_text(patch, encoding='utf-8')
    (args.output_dir/'release-proposal.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__': main()
