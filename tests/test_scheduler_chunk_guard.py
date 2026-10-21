"""Execute the actual pinned PrefillAdder method with lightweight fake pools.

This checks admission decisions, not GPU/KV correctness or live scheduling.
Pass the original schedule_policy.py exported from the pinned image.
"""
import ast
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from scheduler_chunk_guard_patch import patch


def method(source):
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'PrefillAdder')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'add_one_req')
    fn.returns = None
    for arg in fn.args.args:
        arg.annotation = None
    module = ast.Module(body=[fn], type_ignores=[])
    scope = {'CLIP_MAX_NEW_TOKENS': 4096, 'AddReqResult': NS(OTHER='OTHER', NO_TOKEN='NO_TOKEN')}
    exec(compile(ast.fix_missing_locations(module), '<pinned PrefillAdder>', 'exec'), scope)
    return scope['add_one_req']


def execute(fn, tail, active):
    noop = lambda *a, **kw: None
    adder = NS(dsa_prefill_cp_in_seq_split=False, prefill_max_requests=None,
        tree_cache=NS(disable=False), page_size=64, can_run_list=[],
        rem_total_tokens=1048576, rem_chunk_tokens=512, rem_input_tokens=2048,
        is_hybrid_swa=False, prefill_delayer_single_pass=None, dllm_config=None,
        _mamba_gap_budget_for_req=lambda r: 0,
        ceil_paged_tokens=lambda n: ((n+63)//64)*64,
        _lock_node=lambda n: nullcontext(), _check_prefill_tile_budget=lambda n: None,
        _req_inc_lock_ref=noop, _update_prefill_budget=noop,
        _account_prefill_cache_admission=noop, budget_state=lambda: 'CONTINUE', new_chunked_req=None)
    req = NS(sampling_params=NS(ignore_eos=False, max_new_tokens=32), output_ids=[],
        full_untruncated_fill_ids=[0]*tail, prefix_indices=[], host_hit_length=0,
        last_node=None, needs_host_load_back=lambda: False, set_extend_range=noop,
        retracted_stain=False)
    result = fn(adder, req, active, None)
    return {'result': result, 'admitted': len(adder.can_run_list),
            'createdSecondChunk': active and adder.new_chunked_req is not None,
            'createdChunk': adder.new_chunked_req is not None}


def main():
    original = Path(sys.argv[1]).read_bytes()
    guarded = patch(original)
    before, after = method(original.decode()), method(guarded)
    rows = {'originalLongWithActive': execute(before, 2048, True),
            'guardedLongWithActive': execute(after, 2048, True),
            'guardedShortWithActive': execute(after, 64, True),
            'guardedLongWithoutActive': execute(after, 2048, False)}
    assert rows['originalLongWithActive']['createdSecondChunk']
    assert rows['guardedLongWithActive'] == {'result': 'OTHER', 'admitted': 0,
        'createdSecondChunk': False, 'createdChunk': False}
    assert rows['guardedShortWithActive']['admitted'] == 1
    assert not rows['guardedShortWithActive']['createdChunk']
    assert rows['guardedLongWithoutActive']['createdChunk']
    try:
        patch(original+b'\n')
        raise AssertionError('Changed source was accepted')
    except ValueError:
        pass
    print(json.dumps({'passed': True, 'cases': rows, 'changedSourceRejected': True}))


if __name__ == '__main__':
    main()
