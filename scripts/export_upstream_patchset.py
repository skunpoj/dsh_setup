"""Export reviewable upstream diffs from verified pristine and patched package trees.

The runtime configurator remains the application engine. This artifact records
exact upstream/local differences; it never downloads, installs or deploys code.
"""
import argparse, difflib, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(data):return hashlib.sha256(data).hexdigest()
def export(contract,pristine,patched,output):
    pieces=[];rows=[]
    for e in contract['targets']:
        rel=Path(e['path'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe patch path')
        original=(pristine/'node_modules/@deepseek-ai'/rel).read_bytes()
        result=(patched/'node_modules/@deepseek-ai'/rel).read_bytes()
        if digest(original)!=e['sha256']:raise ValueError('Unreviewed upstream input: '+e['path'])
        if original==result:raise ValueError('Expected mutation was skipped: '+e['path'])
        name='node_modules/@deepseek-ai/'+e['path']
        pieces.extend(difflib.unified_diff(original.decode().splitlines(keepends=True),result.decode().splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name))
        rows.append({'path':e['path'],'upstreamSHA256':digest(original),'patchedSHA256':digest(result)})
    output.mkdir(parents=True,exist_ok=True)
    data=''.join(pieces).encode();(output/'compatibility.patch').write_bytes(data)
    record={'baselineVersion':contract['baselineVersion'],'patchSHA256':digest(data),'targets':rows,'configuratorSHA256':digest((ROOT/'scripts/configure_models.js').read_bytes()),'purpose':'Review artifact, normalized dsh.example.com host; generated from official integrity-verified package targets. Runtime application uses guarded configure_models.js, not this example-host diff.'}
    (output/'manifest.json').write_bytes((json.dumps(record,indent=2)+'\n').encode());return record
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pristine',type=Path,required=True);p.add_argument('--patched',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=export(json.loads((ROOT/'scripts/upstream_patch_contract.json').read_text()),a.pristine,a.patched,a.output)
    print(json.dumps({'patchTargets':len(result['targets']),'patchSHA256':result['patchSHA256']}))
