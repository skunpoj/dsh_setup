"""Hash-fenced temporary score tile budget; conversation limit is unchanged."""
import sys
if sys.flags.optimize or not __debug__:
    raise RuntimeError('Qualification helpers require unoptimized Python')
import ast,hashlib,sys
from pathlib import Path
EXPECTED='486900ed693af0573a941d6b6656ebc01ccb7ff1c44584e43ad3c0fb00a3c3a9'
ANCHOR='_TORCH_INDEXER_SCORE_BUDGET_BYTES = 1 << 30'
REPLACEMENT='_TORCH_INDEXER_SCORE_BUDGET_BYTES = 1 << 27'
def patch(source):
    if hashlib.sha256(source.encode()).hexdigest()!=EXPECTED or source.count(ANCHOR)!=1:
        raise ValueError('Unknown backend source; refuse overlay')
    result=source.replace(ANCHOR,REPLACEMENT,1);ast.parse(result);return result
if __name__=='__main__':
    src,dst=map(Path,sys.argv[1:]);assert not dst.exists(),'Preserve existing output'
    result=patch(src.read_text(encoding='utf-8')).encode('utf-8')
    assert hashlib.sha256(result).hexdigest()=='6a0202c92d0e05922a72e02129c9a982235edc8210fbe94f4fb4403ce1d41f29', 'Generated source differs; refuse before model startup'
    dst.write_bytes(result)
