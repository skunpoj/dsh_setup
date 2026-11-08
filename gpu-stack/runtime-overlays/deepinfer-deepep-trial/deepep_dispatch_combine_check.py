"""P-3: DeepEP dispatch + combine CORRECTNESS check for the iommu=pt window (replaces the unwritten Cursor deliverable).

  GPU run (4 GPUs, in the DeepEP pod BEFORE the model loads; needs the pod's python with deep_ep + torch):
      torchrun --standalone --nproc_per_node=4 deepep_dispatch_combine_check.py [--tokens 64] [--topk 8] [--rounds 3]
  Checker self-test (no GPU, needs only numpy; proves the checks can PASS and can FAIL):
      python -I deepep_dispatch_combine_check.py --selftest

What it proves (silent corruption was the original failure mode, so every check is exact, not statistical):
  D1 every rank receives exactly the multiset of token rows that the other ranks sent to experts owned by that rank
     (row keys compared as sorted exact values; any dropped, duplicated or corrupted row fails);
  D2 the global count of received rows equals the sum over tokens of distinct destination ranks;
  C1 combine with an identity expert returns, for every original token, (number of distinct destination ranks) * x
     (exact, integers kept below 256 so bf16 is lossless);
  R  the whole dispatch+combine sequence is repeated --rounds times and must be identical every time.
ASSUMPTIONS to re-check on the first GPU run (the checker reports them, it does not hide them): experts are placed
contiguously (rank r owns experts [r*E/R, (r+1)*E/R)); combine sums one copy per distinct destination rank without applying
topk_weights; E=384, hidden=5120 as in deepinfer/sm90_qualification/native_communication_cap.py. Topk default 8: set the
model's real num_experts_per_tok with --topk. bf16 only; the FP8 dispatch path is NOT covered here.
Exit code 0 = PASS, 1 = FAIL, 2 = could not run.
"""
import argparse
import json
import sys
import time

import numpy as np

E, H = 384, 5120


def make_inputs(rank, R, T, topk, seed):
    rng = np.random.default_rng(seed * 1000 + rank)
    ids = rank * T + np.arange(T)
    cols = np.arange(H)
    x = ((ids[:, None] * 7 + cols[None, :]) % 60 + 1).astype(np.float32)   # integers 1..60: exact in bf16
    idx = np.stack([rng.choice(E, size=topk, replace=False) for _ in range(T)]).astype(np.int64)
    return x, idx


def row_key(x):
    w = (np.arange(x.shape[1], dtype=np.float64) + 1.0)
    return (x.astype(np.float64) * w[None, :]).sum(axis=1)


def dest_ranks(idx, R):
    return idx // (E // R)


def expected(all_x, all_idx, R):
    """Per receiving rank: sorted exact row keys; per source rank: expected combine multiplier per token."""
    recv = {r: [] for r in range(R)}
    mult = {}
    for s in range(R):
        d = dest_ranks(all_idx[s], R)
        mult[s] = np.array([len(set(row.tolist())) for row in d], dtype=np.float32)
        keys = row_key(all_x[s])
        for t in range(d.shape[0]):
            for r in set(d[t].tolist()):
                recv[r].append(keys[t])
    return {r: np.sort(np.array(v, dtype=np.float64)) for r, v in recv.items()}, mult


def check(rank, recv_x, comb_x, all_x, all_idx, R):
    exp_recv, mult = expected(all_x, all_idx, R)
    got = np.sort(row_key(recv_x))
    out = {"rank": rank, "recv_rows": int(len(got)), "expected_rows": int(len(exp_recv[rank]))}
    d1 = len(got) == len(exp_recv[rank]) and np.array_equal(got, exp_recv[rank])
    want = all_x[rank] * mult[rank][:, None]
    c1 = comb_x.shape == want.shape and bool(np.array_equal(comb_x.astype(np.float32), want))
    out.update({"D1_dispatch_multiset_exact": bool(d1), "C1_combine_exact": c1,
                "combine_bad_tokens": int((comb_x.astype(np.float32) != want).any(axis=1).sum()) if comb_x.shape == want.shape else -1})
    return out


def selftest():
    R, T, topk = 4, 16, 8
    all_x, all_idx = {}, {}
    for r in range(R):
        all_x[r], all_idx[r] = make_inputs(r, R, T, topk, seed=1)

    def perfect(r):
        recv = []
        for s in range(R):
            d = dest_ranks(all_idx[s], R)
            for t in range(T):
                if r in set(d[t].tolist()):
                    recv.append(all_x[s][t])
        mult = np.array([len(set(row.tolist())) for row in dest_ranks(all_idx[r], R)], dtype=np.float32)
        return np.stack(recv), all_x[r] * mult[:, None]

    ok = all(all(v for k, v in check(r, *perfect(r), all_x, all_idx, R).items() if k.endswith("exact")) for r in range(R))
    rx, cx = perfect(0)
    rx_bad = rx.copy(); rx_bad[3, 100] += 1.0                  # one corrupted element
    cx_bad = cx.copy(); cx_bad[5, 7] += 1.0
    rx_drop = rx[:-1]                                           # one dropped row
    bad1 = check(0, rx_bad, cx, all_x, all_idx, R)["D1_dispatch_multiset_exact"]
    bad2 = check(0, rx, cx_bad, all_x, all_idx, R)["C1_combine_exact"]
    bad3 = check(0, rx_drop, cx, all_x, all_idx, R)["D1_dispatch_multiset_exact"]
    res = {"perfect_passes": ok, "corrupt_dispatch_detected": not bad1, "corrupt_combine_detected": not bad2, "dropped_row_detected": not bad3}
    print(json.dumps(res))
    return 0 if all(res.values()) else 1


def stage(msg):
    import os
    print('STAGE pid=%s %s' % (os.getpid(), msg), flush=True)


def gpu_main(a):
    stage('import torch')
    import torch
    import torch.distributed as dist
    stage('import deep_ep')
    import deep_ep
    from deep_ep import EPBuffer
    stage('init_process_group')
    dist.init_process_group("nccl")
    stage('process group ready')
    rank, R = dist.get_rank(), dist.get_world_size()
    torch.cuda.set_device(rank % torch.cuda.device_count())
    if R != 4:
        print(json.dumps({"verdict": "ERROR", "why": f"world size {R} != 4"})) if rank == 0 else None
        return 2
    T, topk = a.tokens, a.topk
    xs, idxs = zip(*[make_inputs(r, R, T, topk, seed=a.seed) for r in range(R)])
    all_x = {r: xs[r] for r in range(R)}
    all_idx = {r: idxs[r] for r in range(R)}
    x = torch.from_numpy(all_x[rank]).cuda().to(torch.bfloat16)
    idx = torch.from_numpy(all_idx[rank]).cuda()
    w = torch.full((T, topk), 1.0 / topk, dtype=torch.float32, device="cuda")
    t0 = time.time()
    stage('EPBuffer constructor')
    buf = EPBuffer(group=dist.group.WORLD, num_max_tokens_per_rank=T, hidden=H, num_topk=topk,
                   use_fp8_dispatch=False, allow_hybrid_mode=True, explicitly_destroy=True)
    results, ref = [], None
    for rd in range(a.rounds):
        stage('dispatch round %d' % rd)
        recv_x, recv_idx, recv_w, handle, ev = buf.dispatch(x, topk_idx=idx, topk_weights=w, num_experts=E)
        torch.cuda.synchronize()
        recv_cpu = recv_x.float().cpu().numpy()
        stage('combine round %d' % rd)
        comb, _, _ = buf.combine(recv_x, handle)       # identity expert
        torch.cuda.synchronize()
        comb_cpu = comb.float().cpu().numpy()
        r = check(rank, recv_cpu, comb_cpu, all_x, all_idx, R)
        sig = (row_key(recv_cpu).sum(), float(comb_cpu.astype(np.float64).sum()))
        r["round"] = rd
        r["repeatable"] = (ref is None) or (sig == ref)
        ref = ref or sig
        results.append(r)
    buf.destroy()
    ok = all(r["D1_dispatch_multiset_exact"] and r["C1_combine_exact"] and r["repeatable"] for r in results)
    gathered = [None] * R
    dist.all_gather_object(gathered, {"rank": rank, "ok": ok, "rounds": results})
    if rank == 0:
        total_recv = sum(g["rounds"][0]["recv_rows"] for g in gathered)
        d2 = total_recv == sum(int(expected(all_x, all_idx, R)[1][s].sum()) for s in range(R))
        verdict = "PASS" if all(g["ok"] for g in gathered) and d2 else "FAIL"
        print(json.dumps({"verdict": verdict, "D2_global_count_exact": d2, "tokens": T, "topk": topk, "rounds": a.rounds,
                          "seconds": round(time.time() - t0, 1), "deep_ep": getattr(deep_ep, "__version__", None),
                          "per_rank": gathered}, indent=1))
        return 0 if verdict == "PASS" else 1
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--tokens", type=int, default=64)
    p.add_argument("--topk", type=int, default=8)
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args()
    sys.exit(selftest() if a.selftest else gpu_main(a))
