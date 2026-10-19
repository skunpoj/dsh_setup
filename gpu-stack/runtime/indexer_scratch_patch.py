"""Hash-fenced inference-only indexer scratch reuse. Private candidate."""
import sys
if sys.flags.optimize or not __debug__:
    raise RuntimeError('Qualification helpers require unoptimized Python')
import ast,hashlib,sys
from pathlib import Path
SOURCE_SHA256='b56eca87c3706edc9dd4db0f64431b87d52864495765bc3a85af6dbde21e2a5a'
ANCHOR='        s = (s.relu() * weights.unsqueeze(-1)).sum(dim=1)\n        return s.float()\n'
REPLACEMENT='        # Reuse only the newly-owned inference score tensor; preserve\n        # mixed-dtype promotion and autograd semantics on the reference path.\n        if not s.requires_grad and not weights.requires_grad and weights.dtype == s.dtype:\n            s.relu_()\n            s.mul_(weights.unsqueeze(-1))\n            s = s.sum(dim=1)\n        else:\n            s = (s.relu() * weights.unsqueeze(-1)).sum(dim=1)\n        return s.float()\n'

def patch(source):
    if hashlib.sha256(source.encode()).hexdigest()!=SOURCE_SHA256:
        raise ValueError('Unqualified indexer source; re-review required')
    if source.count(ANCHOR)!=1:
        raise ValueError('Indexer target changed; refuse patch')
    result=source.replace(ANCHOR,REPLACEMENT,1)
    ast.parse(result)
    return result

if __name__=='__main__':
    original,output=map(Path,sys.argv[1:])
    if output.exists():raise ValueError('Refuse replacing an existing overlay')
    result=patch(original.read_text(encoding='utf-8'))
    output.write_bytes(result.encode('utf-8'))
    print('Qualified indexer scratch-reuse overlay prepared')
