"""Check official source and npm channels without changing Production.

Candidate preparation requires an existing reviewed source contract. A
candidate build is not migration, runtime or security acceptance.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from upstream_source_diff import fetch, inspect_candidate
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
VERSION=re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?')


def select_candidate(event, baseline, latest, explicit):
    """Test checked-out code against its pin; discover releases separately."""
    if event in ('push', 'pull_request'):
        if explicit and explicit != baseline:
            raise ValueError('Source CI must qualify the checked-out Dockerfile pin')
        return baseline, 'checked-out-source-pin'
    return explicit or latest, 'explicit-version' if explicit else 'npm-latest'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--candidate',help='Explicit preview override; default tracks npm latest')
    ap.add_argument('--event', choices=('push', 'pull_request', 'schedule', 'workflow_dispatch'),
                    help='Source CI qualifies its Dockerfile pin; scheduled/manual discovery tracks latest')
    ap.add_argument('--prepare-candidate',action='store_true', help='Only permit an already reviewed version')
    ap.add_argument('--source-diff',type=Path,help='Persist data-only source comparison before build')
    args=ap.parse_args()
    if args.candidate and not VERSION.fullmatch(args.candidate):
        raise ValueError('Invalid candidate version')
    docker=ROOT/'Dockerfile';text=docker.read_text(encoding='utf-8')
    pins=re.findall(r'^ARG DSH_VERSION=(\S+)$',text,re.M)
    if len(pins)!=1 or not VERSION.fullmatch(pins[0]):raise ValueError('Expected one valid Dockerfile package pin')
    baseline=pins[0]
    channels=json.loads(fetch('https://registry.npmjs.org/-/package/@deepseek-ai/dsh/dist-tags', 2*1024*1024))
    refs=subprocess.check_output(['git','ls-remote','https://github.com/deepseek-ai/deepseek-harness.git',
                                   'refs/heads/master','refs/tags/dsh-v*'],text=True,timeout=40)
    master=next(line.split()[0] for line in refs.splitlines() if line.endswith('refs/heads/master'))
    candidate, selection=select_candidate(args.event, baseline, channels['latest'], args.candidate)
    if not VERSION.fullmatch(candidate):raise ValueError('Invalid candidate version')
    package=json.loads(fetch('https://registry.npmjs.org/@deepseek-ai/dsh/'+candidate, 2*1024*1024))
    if package['version']!=candidate:raise ValueError('Registry version mismatch')
    if package.get('name')!='@deepseek-ai/dsh':raise ValueError('Unexpected registry package identity')
    integrity=package.get('dist',{}).get('integrity','')
    if not re.fullmatch(r'sha512-[A-Za-z0-9+/]{86}==',integrity):raise ValueError('Missing or invalid published SHA512 integrity')
    record={'checkedAtUTC':datetime.now(timezone.utc).isoformat(),'officialRepository':'deepseek-ai/deepseek-harness',
        'officialMaster':master,'npmChannels':channels,'sourcePackagePin':baseline,'candidateVersion':candidate,
        'defaultChannelUpdateAvailable':channels['latest']!=baseline,'candidateChangeRequired':candidate!=baseline,
        'triggerEvent':args.event,'candidateSelection':selection,
        'candidateRegistryIntegrity':integrity,'candidateSourceGitHead':package.get('gitHead'),
        'candidateLicense':package.get('license'),'productionChanged':False,
        'automationPolicy':'Detect releases and source drift; qualify reviewed source; human-reviewed complete port PR required; no automatic writes, merge or deployment'}
    contract=json.loads((ROOT/'scripts/upstream_patch_contract.json').read_text(encoding='utf-8')) if args.source_diff or args.prepare_candidate else None
    if args.source_diff:
        try:
            comparison=inspect_candidate(package,contract)
        except Exception as error:  # Persist a blocked receipt for malformed public archive/metadata too.
            comparison={'schemaVersion':1,'candidateVersion':candidate,'buildAllowed':False,'status':'blocked-source-inspection-failed','errorType':type(error).__name__,'error':str(error)[:512],'nextAction':'Inspect public archive/metadata or limits, repair detection or reviewed port; do not bypass source gate','packageCodeExecuted':False}
        args.source_diff.parent.mkdir(parents=True,exist_ok=True)
        args.source_diff.write_text(json.dumps(comparison,indent=2)+'\n',encoding='utf-8')
        record['sourceComparison']=comparison['status']
        record['buildAllowed']=comparison['buildAllowed']
    if args.prepare_candidate:
        if candidate != contract.get('baselineVersion'):
            raise ValueError('Candidate pin requires a reviewed complete source port; pin-only upgrades are refused')
        docker.write_text(re.sub(r'^ARG DSH_VERSION=\S+$','ARG DSH_VERSION='+candidate,text,flags=re.M),encoding='utf-8')
        record['candidatePinPrepared']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record))


if __name__=='__main__':main()
