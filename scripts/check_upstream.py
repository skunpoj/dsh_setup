"""Check official source and npm channels without changing Production.

Optional candidate preparation changes only the Dockerfile package pin. A
candidate build is not migration, runtime or security acceptance.
"""
import argparse
import json
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
VERSION=re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--candidate',help='Explicit preview override; default tracks npm latest')
    ap.add_argument('--prepare-candidate',action='store_true')
    args=ap.parse_args()
    if args.candidate and not VERSION.fullmatch(args.candidate):
        raise ValueError('Invalid candidate version')
    docker=ROOT/'Dockerfile';text=docker.read_text(encoding='utf-8')
    pins=re.findall(r'^ARG DSH_VERSION=(\S+)$',text,re.M)
    if len(pins)!=1 or not VERSION.fullmatch(pins[0]):raise ValueError('Expected one valid Dockerfile package pin')
    baseline=pins[0]
    with urllib.request.urlopen('https://registry.npmjs.org/-/package/@deepseek-ai/dsh/dist-tags',timeout=25) as response:
        channels=json.load(response)
    refs=subprocess.check_output(['git','ls-remote','https://github.com/deepseek-ai/deepseek-harness.git',
                                   'refs/heads/master','refs/tags/dsh-v*'],text=True,timeout=40)
    master=next(line.split()[0] for line in refs.splitlines() if line.endswith('refs/heads/master'))
    candidate=args.candidate or channels['latest']
    if not VERSION.fullmatch(candidate):raise ValueError('Invalid candidate version')
    with urllib.request.urlopen('https://registry.npmjs.org/@deepseek-ai/dsh/'+candidate,timeout=25) as response:
        package=json.load(response)
    if package['version']!=candidate:raise ValueError('Registry version mismatch')
    if package.get('name')!='@deepseek-ai/dsh':raise ValueError('Unexpected registry package identity')
    integrity=package.get('dist',{}).get('integrity','')
    if not re.fullmatch(r'sha512-[A-Za-z0-9+/]{86}==',integrity):raise ValueError('Missing or invalid published SHA512 integrity')
    record={'checkedAtUTC':datetime.now(timezone.utc).isoformat(),'officialRepository':'deepseek-ai/deepseek-harness',
        'officialMaster':master,'npmChannels':channels,'sourcePackagePin':baseline,'candidateVersion':candidate,
        'defaultChannelUpdateAvailable':channels['latest']!=baseline,'candidateChangeRequired':candidate!=baseline,
        'candidateRegistryIntegrity':integrity,'candidateSourceGitHead':package.get('gitHead'),
        'candidateLicense':package.get('license'),'productionChanged':False,
        'automationPolicy':'Detect releases, test candidate, propose package-pin PR; no auto-merge or Production deployment'}
    if args.prepare_candidate:
        docker.write_text(re.sub(r'^ARG DSH_VERSION=\S+$','ARG DSH_VERSION='+candidate,text,flags=re.M),encoding='utf-8')
        record['candidatePinPrepared']=True
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record))


if __name__=='__main__':main()
