"""Phase A speed matrix, direct to the DeepInfer engine in-pod (read-only, no keys).

Each request records per-chunk timestamps for reasoning and visible text separately, so every
metric in SPEED_METHOD_REVIEW_20261030.md comes from the same run:
  TTFT  first token of any kind; TTFV first visible text token
  D     (completion_tokens - 1) / (t_last_token - t_first_token)
  E     completion_tokens / (t_last_token - t_request)
  L     (completion_tokens - 1) / (t_last_visible - t_first_visible)   [19 Oct legacy formula]
  Aggregate = sum(completion_tokens) / cohort wall time
Output: one RAW json line per request and one COHORT line per cell, on stdout.
"""
import json, statistics, sys, threading, time, urllib.request

URL = (sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000") + "/v1/chat/completions"
MODEL = sys.argv[3] if len(sys.argv) > 3 else "deepseek-v4.1-flash"
PROMPTS = {
    "W1": ("Write a detailed essay about the history of tea, with many sections.", 512, True),
    "W3": ("List the integers from 1 through 40, separated by commas.", 2048, False),
    "W4": ("Explain, in your own words, how a central bank sets interest rates and why.", 512, False),
}
WHICH = sys.argv[1] if len(sys.argv) > 1 else "short"
NOTHINK = len(sys.argv) > 4 and sys.argv[4] == "nothink"
WORKLOADS = ("W3", "W4") if NOTHINK else ("W1", "W3", "W4")


def request(messages, max_tokens, ignore_eos):
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "stream": True,
            "stream_options": {"include_usage": True}, "temperature": 0}
    if ignore_eos:
        body["ignore_eos"] = True
    if NOTHINK:
        body["chat_template_kwargs"] = {"thinking": False, "enable_thinking": False}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); first_any = first_vis = last_any = last_vis = None
    vis_chunks = rea_chunks = 0; usage = {}; err = None; text = []
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                d = json.loads(line[5:]); now = time.time()
                if d.get("usage"):
                    usage = d["usage"]
                for c in d.get("choices", []):
                    delta = c.get("delta") or {}
                    rea = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    vis = delta.get("content") or ""
                    if rea or vis:
                        first_any = first_any or now; last_any = now
                    if rea:
                        rea_chunks += 1
                    if vis:
                        first_vis = first_vis or now; last_vis = now; vis_chunks += 1; text.append(vis)
    except Exception as e:
        err = type(e).__name__ + ": " + str(e)[:160]
    n = usage.get("completion_tokens", 0)
    det = usage.get("completion_tokens_details") or {}
    pdet = usage.get("prompt_tokens_details") or {}
    rec = {"t_request": t0, "ttft": (first_any - t0) if first_any else None,
           "ttfv": (first_vis - t0) if first_vis else None,
           "completion_tokens": n, "reasoning_tokens": det.get("reasoning_tokens"),
           "prompt_tokens": usage.get("prompt_tokens"), "cached_tokens": pdet.get("cached_tokens"),
           "reasoning_chunks": rea_chunks, "visible_chunks": vis_chunks, "visible_chars": len("".join(text)),
           "D": (n - 1) / (last_any - first_any) if first_any and last_any and last_any > first_any and n > 1 else None,
           "E": n / (last_any - t0) if last_any else None,
           "L": (n - 1) / (last_vis - first_vis) if first_vis and last_vis and last_vis > first_vis and n > 1 else None,
           "t_end": last_any or time.time(), "err": err, "text_head": "".join(text)[:80]}
    return rec


def cohort(wl, clients, rep):
    prompt, mx, ign = PROMPTS[wl]
    out = [None] * clients
    def w(i):
        out[i] = request([{"role": "user", "content": prompt + ("" if i == 0 else f" (variant {i})")}], mx, ign)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(clients)]
    [t.start() for t in ts]; [t.join() for t in ts]
    for i, r in enumerate(out):
        print("RAW " + json.dumps({"wl": wl, "clients": clients, "rep": rep, "i": i, **r}, ensure_ascii=False), flush=True)
    wall = max(r["t_end"] for r in out) - min(r["t_request"] for r in out)
    med = lambda k: statistics.median([r[k] for r in out if r[k] is not None]) if any(r[k] is not None for r in out) else None
    c = {"wl": wl, "clients": clients, "rep": rep, "aggregate": sum(r["completion_tokens"] for r in out) / wall,
         "D_med": med("D"), "E_med": med("E"), "L_med": med("L"), "ttft_med": med("ttft"), "ttfv_med": med("ttfv"),
         "tokens_med": med("completion_tokens"), "reasoning_med": med("reasoning_tokens"),
         "errors": sum(1 for r in out if r["err"])}
    print("COHORT " + json.dumps(c), flush=True)


if WHICH == "short":
    print("START " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), flush=True)
    for wl in WORKLOADS:
        for clients in (1, 2, 4, 8, 16):
            for rep in (1, 2, 3):
                cohort(wl, clients, rep)
    print("END " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), flush=True)
else:
    # W5: long context with a needle, cold then a cached continuation over the same prefix.
    print("START " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), flush=True)
    sentence = "The quick brown fox jumps over the lazy dog near the river bank today. "
    probe = request([{"role": "user", "content": sentence * 100 + "Reply OK."}], 8, False)
    per = (probe["prompt_tokens"] or 1500) / 100.0
    for target in ((1_000_000,) if WHICH == "long1m" else (128_000, 500_000, 1_000_000)):
        reps = int(target / per)
        half = reps // 2
        doc = sentence * half + "Remember this: the secret code is 7391. " + sentence * (reps - half)
        for kind, question in (("cold", "What is the secret code mentioned in the text? Answer with the number only."),
                               ("continuation", "Repeat the secret code from the text, then say DONE.")):
            r = request([{"role": "user", "content": doc + "\n\n" + question}], 32, False)
            ok = "7391" in (r["text_head"] or "")
            print("RAW " + json.dumps({"wl": "W5", "target": target, "kind": kind, "needle_ok": ok, **r}, ensure_ascii=False), flush=True)
    print("END " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), flush=True)
