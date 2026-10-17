"""Preserve the pinned scheduler's single chunked-request invariant.

V2 reserves prefill space for short requests. The pinned PrefillAdder accepts
has_chunked_req but otherwise can create a second chunked request from that
reserved space. Defer that branch; complete, fitting short prefills still run.
"""
import ast
import hashlib
import sys
from pathlib import Path

EXPECTED_SHA256 = '0e45c0bd4648998fb9dbf3d903380521bd7911941ce96b501e89c1b395861d9d'
ANCHOR = '''            else:
                # Make sure at least one page is available
                trunc_len = chunk_tokens_limit // self.page_size * self.page_size
'''
REPLACEMENT = '''            else:
                # LOCAL_SINGLE_CHUNK_OWNER_V3
                # The interactive reservation must not create a second
                # chunked_req while a resumed long prefill owns that slot.
                # Return through upstream rejection/cleanup handling.
                if has_chunked_req:
                    return AddReqResult.OTHER
                # Make sure at least one page is available
                trunc_len = chunk_tokens_limit // self.page_size * self.page_size
'''


def patch(original):
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Pinned PrefillAdder source changed; refusing chunk guard')
    text = original.decode()
    if text.count(ANCHOR) != 1:
        raise ValueError('Chunk-admission anchor is not unique')
    result = text.replace(ANCHOR, REPLACEMENT)
    ast.parse(result)
    return result


if __name__ == '__main__':
    source, destination = map(Path, sys.argv[1:])
    destination.write_text(patch(source.read_bytes()))
