"""Minimal OpenAI-compatible chat server on top of the DeepInfer offline engine.

DeepInfer ships offline inference only. This wraps one `LLM` per data-parallel rank
(attention DP + MoE EP, same layout as examples/benchmark.py) behind a FastAPI frontend
so request-replay benchmarks such as InferenceX AgentX (aiperf) can drive it.

    python serve/openai_server.py --model ~/models/DeepSeek-V4.1-Flash-1017 --dp 4 --port 8888

Limitations, by design of the open-source engine:
- No cross-request prefix cache: every request prefills its full prompt.

Output follows the OpenAI shape SGLang returns for DeepSeek-V4.1 (serve/dsml_output.py): reasoning in
`reasoning_content`, DSML tool calls in `tool_calls` with `finish_reason="tool_calls"`. A request picks thinking
mode with `chat_template_kwargs.thinking` (or `.enable_thinking`); otherwise `--thinking-mode` applies.

Images: OpenAI `image_url` (base64 data: URLs; http(s) only with --allow-image-url-fetch) and Anthropic `image` parts go
to the engine's multimodal processor (serve/image_inputs.py); `/v1/tokenize` counts each image's expanded tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import json
import multiprocessing as mp
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Module level so FastAPI can resolve the string annotation `request: Request`.
from fastapi import FastAPI, Request

if TYPE_CHECKING:
    from deepinfer._C.engine import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "examples"))
sys.path.insert(0, str(REPO_ROOT / "serve"))
from dsml_output import AssistantOutputParser  # noqa: E402
from rank_watchdog import RankWatchdog  # noqa: E402
from stop_sequences import StopMatcher, parse_stop  # noqa: E402
from structured_output import build_so_args  # noqa: E402
from prompt_tokenizer import PromptTokenizer  # noqa: E402
from image_inputs import ImageInputError, LoadedImage, check_part_types, expand_placeholders, load_images  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True, help="local HF checkpoint directory")
    p.add_argument("--served-model-name", default=None)
    p.add_argument("--dp", type=int, default=4, help="data-parallel ranks on this node (= EP size)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8888)
    p.add_argument("--max-model-len", type=int, default=1 << 20)
    p.add_argument(
        "--advertised-max-model-len",
        type=int,
        default=None,
        help="max_model_len reported by /v1/tokenize (default: --max-model-len). An upstream proxy that only accepts the "
        "SGLang backend's 1M value can be given 1048576 here; prompts above --max-model-len still get a 400",
    )
    p.add_argument("--max-num-seqs", type=int, default=128, help="per DP rank")
    p.add_argument("--max-num-batched-tokens", type=int, default=32768, help="prefill chunk per DP rank")
    p.add_argument("--gpu-memory-utilization", type=float, default=0.9)
    p.add_argument("--yoco-keep-tokens", type=int, default=140, help="0 disables decoder SWA bounded replay")
    p.add_argument("--thinking-mode", default="chat", choices=["chat", "thinking"])
    p.add_argument(
        "--reasoning-effort",
        default="high",
        help="default reasoning effort of thinking-mode prompts: low|high|max or an integer 1-100 (checkpoint encoding.py: "
        "50/75/100); a request overrides it with reasoning_effort or chat_template_kwargs.reasoning_effort",
    )
    p.add_argument("--log-interval-steps", type=int, default=200)
    p.add_argument(
        "--rank-heartbeat-timeout",
        type=float,
        default=20.0,
        help="seconds without a heartbeat from any engine rank (after all are ready) before the server fails open "
        "requests, kills the ranks and exits non-zero (see serve/rank_watchdog.py)",
    )
    p.add_argument("--hicache-size-gb", type=float, default=32, help="pinned host KV page pool per DP rank; 0 disables the prefix cache")
    p.add_argument("--hicache-state-slots", type=int, default=4096, help="host SWA state slots per DP rank")
    p.add_argument(
        "--routing",
        default="affinity",
        choices=["affinity", "least-loaded"],
        help="affinity: a conversation's turns go to one rank (needed for cache hits)",
    )
    p.add_argument(
        "--prefill-any-interval",
        type=int,
        default=30,
        help="DEEPINFER_PREFILL_ANY_ATTEMPT_INTERVAL: a rank with a waiting prompt gets a prefill step at most this "
        "many decode steps later even if other ranks are idle. A prompt step pauses decode on every rank, so a larger "
        "value gives faster decode and more throughput at the cost of TTFT. 30 favours throughput; use 2 for low TTFT",
    )
    p.add_argument(
        "--eplb-interval",
        type=int,
        default=0,
        help="DEEPINFER_EXPERT_REARRANGEMENT_STEP_INTERVAL: rearrange experts every N steps; 0 (default) disables EPLB. "
        "Each rearrangement stalls every rank (~0.3 s on B200/GB300), which under online traffic costs far more than "
        "the balance it buys",
    )
    p.add_argument(
        "--eplb-after-prefill",
        type=int,
        default=0,
        choices=[0, 1],
        help="DEEPINFER_REARRANGE_AFTER_PREFILL_IN_NORMAL_ENGINE: also rearrange after every prefill step (only with "
        "--eplb-interval > 0); with agentic traffic nearly every step batch contains a prefill",
    )
    p.add_argument(
        "--tokenizer-backend",
        default="auto",
        choices=["auto", "fastokens", "segment", "hf"],
        help="prompt tokenization (serve/prompt_tokenizer.py); auto = the first of fastokens (if installed), segment, hf "
        "that matches tokenizer.encode on startup probes. All produce tokenizer.encode's ids",
    )
    p.add_argument(
        "--tokenizer-verify-rate",
        type=float,
        default=0.005,
        help="fraction of prompts re-encoded with tokenizer.encode in the background; a mismatch switches to hf",
    )
    p.add_argument("--max-images-per-request", type=int, default=16, help="image content parts per request (serve/image_inputs.py)")
    p.add_argument("--max-image-bytes", type=int, default=20 << 20, help="encoded size limit per image")
    p.add_argument(
        "--allow-image-url-fetch",
        action="store_true",
        help="fetch http(s) image_url parts server-side (off: only inline base64 data: URLs; a fetch of client-chosen "
        "URLs from inside the cluster is an SSRF path)",
    )
    return p.parse_args()


# --------------------------------------------------------------------------- engine side


def worker_main(args: argparse.Namespace, dp_rank: int, in_q: mp.Queue, out_q: mp.Queue) -> None:
    """One DP rank: owns an engine and steps it in lockstep with the other ranks."""
    import ctypes
    import signal

    # Die with the frontend instead of lingering as an orphan that holds the GPU.
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG

    from _config import create_llm, setup_common_env

    if args.yoco_keep_tokens > 0:
        os.environ["DEEPINFER_YOCO_PREFILL_TRUNCATION_MODE"] = "compact"
        os.environ["DEEPINFER_YOCO_PREFILL_KEEP_TOKENS"] = str(args.yoco_keep_tokens)
        os.environ["DEEPINFER_PREFILL_STORE_EXTRA_STATE"] = "1"
    if args.hicache_size_gb > 0:
        # Keep more SWA history in the state ring so the prefix cache can store states at several
        # 128-boundaries behind the end of a prompt (see HostPrefixCache.state_lookback_blocks).
        os.environ.setdefault("DEEPINFER_PREFILL_STORE_EXTRA_SIZE", "512")
    os.environ.setdefault("DEEPINFER_PREFILL_ANY_ATTEMPT_INTERVAL", str(args.prefill_any_interval))
    if args.eplb_interval == 0:
        # The 32 redundant expert slots only pay off with EPLB rearrangement; without it they are fixed copies of
        # experts 0-31 and only add expert weight to read per rank (decode +4-5% without them on B200 and GB300).
        os.environ.setdefault("DEEPINFER_OVERRIDE_NUM_EXTRA_EXPERTS", "0")
    setup_common_env(model_name=args.model, sampler_force_topk=1024, set_override_experts=True, enable_eplb=False)
    if args.eplb_interval > 0:
        os.environ["DEEPINFER_EXPERT_REARRANGEMENT_STEP_INTERVAL"] = str(args.eplb_interval)
        os.environ["DEEPINFER_REARRANGE_AFTER_PREFILL_IN_NORMAL_ENGINE"] = str(args.eplb_after_prefill)

    llm = create_llm(
        args.model,
        dp_rank,
        ep_size=args.dp,
        env={"DEEPINFER_LOGGING_INTERVAL_STEP": str(args.log_interval_steps)},
        data_parallel_size=args.dp,
        max_num_seqs=args.max_num_seqs,
        max_num_batched_tokens=args.max_num_batched_tokens,
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        lookahead_tokens=min(1, int(os.getenv("DEEPINFER_USE_NEXTN_DECODE", "5"))),
    )

    import numpy as np

    from deepinfer._C.engine import RequestOutput  # pyright: ignore[reportMissingModuleSource]
    from deepinfer.sampling_params import SamplingParams

    engine = llm.llm_engine
    cache = None
    if args.hicache_size_gb > 0:
        try:
            from deepinfer.hicache import HostPrefixCache
        except ImportError:  # tree without the host prefix cache: serve without it
            print(f"[server] deepinfer.hicache not available, prefix cache disabled (rank {dp_rank})", flush=True)
        else:
            cache = HostPrefixCache(engine, size_bytes=int(args.hicache_size_gb * 2**30), num_state_slots=args.hicache_state_slots)
            engine.pe_do_save_kvcache = cache.on_prefill_step  # write-through at the end of every prefill
    out_q.put(("ready", dp_rank, None))

    def mm_data(images: list[tuple[bytes, tuple[int, int]]] | None):
        """The engine's multimodal input: one (encoded bytes, (width, height)) per image placeholder, in prompt order."""
        if engine.multi_modal_processor is None:
            if images:
                raise ValueError("this engine has no multimodal processor; image inputs are not supported")
            return None
        images = images or []
        return dict(image_bytes=[data for data, _ in images], image_sizes=[tuple(size) for _, size in images])

    def enqueue(rid: str, seq: Sequence, num_cached_tokens: int) -> None:
        # Same as LLMEngine.add_request's _enqueue: the processor must get the sequence's own multimodal dict
        # (overwrite_prompt wrote the text/image segments into it), plus the cached prefix length.
        engine.scheduler.add_sequence(seq)
        if engine.multi_modal_processor is not None:
            engine.multi_modal_processor.add(rid, seq.multi_modal_data, num_cached_tokens)

    pending = collections.deque()  # (rid, seq, prompt_ids, use_cache): created, waiting for a cache decision
    inflight = False
    last_stats = time.monotonic()
    last_hb = 0.0  # heartbeat for the frontend's rank watchdog, sent at least once a second, idle or not
    last_logged_lookups = 0
    while True:
        # Requests must be enqueued before the DP-wide has_unfinished_requests all-reduce,
        # so every rank takes the same step / flush / idle branch in the same iteration.
        while True:
            try:
                kind, rid, payload = in_q.get_nowait()
            except queue.Empty:
                break
            if kind == "add":
                try:
                    prompt_ids = np.asarray(payload["prompt_token_ids"], dtype=np.int32)
                    seq = engine.add_request(
                        user_id="0",
                        request_id=rid,
                        sampling_params=SamplingParams(**payload["sampling"]),
                        prompt_token_ids=prompt_ids,
                        multi_modal_data=mm_data(payload.get("images")),
                        enqueue=cache is None,
                    )
                    if cache is not None:
                        if seq is None:
                            out_q.put(("error", rid, "request dropped: invalid prompt tokens"))
                        else:
                            pending.append((rid, seq, prompt_ids, payload.get("use_cache", True)))
                except Exception as e:  # noqa: BLE001 - surface to the client, keep the rank alive
                    out_q.put(("error", rid, repr(e)))
            elif kind == "abort":
                if any(p[0] == rid for p in pending):
                    pending = collections.deque(p for p in pending if p[0] != rid)
                else:
                    engine.abort_request(rid)
                if cache is not None:
                    cache.forget(rid)

        # Cache decisions, in arrival order. A hit pre-allocates the sequence's blocks and fills them from the
        # host; if the GPU cannot allocate yet, wait (while something is running that will free memory).
        while pending:
            rid, seq, prompt_ids, use_cache = pending[0]
            hit = cache.try_resume(seq, rid, prompt_ids) if use_cache else 0
            if hit < 0 and (engine.scheduler.get_num_unfinished_seqs() > 0 or inflight):
                break
            pending.popleft()
            enqueue(rid, seq, max(hit, 0))
        if cache is not None:
            cache.poll()
            if time.monotonic() - last_stats > 5:
                last_stats = time.monotonic()
                st = cache.stats_dict()
                out_q.put(("stats", dp_rank, st))
                if st["lookups"] != last_logged_lookups:
                    last_logged_lookups = st["lookups"]
                    print(
                        f"[hicache rank {dp_rank}] lookups {st['lookups']} hits {st['hits']} "
                        f"token hit rate {st['hit_rate_tokens']:.1%} deferred {st['deferred']} stores {st['stores']} "
                        f"pages {st['pages_used']}/{st['pages_total']} states {st['states_used']}/{st['states_total']} "
                        f"evicted {st['evicted_pages']}",
                        flush=True,
                    )

        now = time.monotonic()
        if now - last_hb >= 1.0:
            out_q.put(("hb", dp_rank, now))
            last_hb = now

        if engine.has_unfinished_requests():
            outputs = engine.step()
            inflight = True
        elif inflight:
            outputs = engine.flush_inflight_reqs()
            inflight = False
        else:
            time.sleep(0.001)
            continue

        if len(outputs):
            # Pointers are recycled on the next step, so read the fields now.
            batch = [
                (
                    RequestOutput.get_request_id(p),
                    RequestOutput.get_token_id(p),
                    RequestOutput.get_finished(p),
                    RequestOutput.get_finish_reason(p),
                    RequestOutput.get_prompt_len(p),
                )
                for p in outputs
            ]
            if cache is not None:
                for rid, _, finished, _, _ in batch:
                    if finished:
                        cache.forget(rid)
            out_q.put(("tokens", None, batch))


# --------------------------------------------------------------------------- HTTP side


class IncrementalDetokenizer:
    """vLLM-style prefix/read offsets so each delta decodes only a short tail."""

    def __init__(self, tokenizer: Any) -> None:
        self.tok = tokenizer
        self.ids: list[int] = []
        self.num_tokens = 0
        self.prefix_offset = 0
        self.read_offset = 0

    def add(self, token_id: int) -> str:
        self.num_tokens += 1
        if token_id == self.tok.eos_token_id:
            return ""
        self.ids.append(token_id)
        prefix = self.tok.decode(self.ids[self.prefix_offset : self.read_offset], skip_special_tokens=False)
        full = self.tok.decode(self.ids[self.prefix_offset :], skip_special_tokens=False)
        if len(full) > len(prefix) and not full.endswith("�"):
            self.prefix_offset, self.read_offset = self.read_offset, len(self.ids)
            return full[len(prefix) :]
        return ""


class Frontend:
    def __init__(self, args: argparse.Namespace) -> None:
        from transformers import AutoTokenizer

        sys.path.insert(0, str(Path(args.model) / "encoding"))
        from encoding import encode_messages, parse_tool_calls  # the checkpoint's own prompt-format reference

        self.args = args
        self.model_name = args.served_model_name or args.model
        self.encode_messages = encode_messages
        self.parse_tool_calls = parse_tool_calls
        self.tokenizer = AutoTokenizer.from_pretrained(args.model)
        # Token ids of the end-of-thinking marker: structured output is delayed until they appear in thinking mode.
        self.think_end_token_ids = list(self.tokenizer.encode("</think>", add_special_tokens=False))
        print(f"[server] think_end_token_ids={self.think_end_token_ids}", flush=True)
        probe = [
            {"role": "system", "content": "sys", "tools": [{"type": "function", "function": {"name": "f", "parameters": {}}}]},
            {"role": "user", "content": "hi 你好 123"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"type": "function", "function": {"name": "f", "arguments": "{}"}}]},
            {"role": "tool", "content": "  out\n"},
        ]
        try:
            probes = [encode_messages(probe, thinking_mode=args.thinking_mode)]
        except Exception:  # noqa: BLE001 - the probe only adds coverage
            probes = []
        # getattr: frontends built on this one with their own argument parser (serve/pd_server.py) get the defaults
        backend, verify_rate = getattr(args, "tokenizer_backend", "auto"), getattr(args, "tokenizer_verify_rate", 0.005)
        self.prompt_tokenizer = PromptTokenizer(self.tokenizer, backend, verify_rate, extra_probes=probes)
        print(f"[server] {self.prompt_tokenizer.describe()}", flush=True)
        self.image_token_id, self._image_layout = self._load_image_geometry(args.model)
        ctx = mp.get_context("spawn")
        self.out_q: mp.Queue = ctx.Queue()
        self.in_qs: list[mp.Queue] = [ctx.Queue() for _ in range(args.dp)]
        # Not daemonic: the engine forks its own helper processes (as examples/_launch.py allows).
        self.procs = [ctx.Process(target=worker_main, args=(args, r, self.in_qs[r], self.out_q), daemon=False) for r in range(args.dp)]
        self.load = [0] * args.dp
        self.owner: dict[str, int] = {}
        self.streams: dict[str, asyncio.Queue] = {}
        self.ready = 0
        self.watchdog = RankWatchdog(args.dp, timeout_s=getattr(args, "rank_heartbeat_timeout", 20.0))
        self.stats = dict(requests=0, finished=0, aborted=0, errors=0, prompt_tokens=0, completion_tokens=0, encode_fallbacks=0)
        self.cache_stats: dict[int, dict] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        for p in self.procs:
            p.start()

    def dispatch_forever(self) -> None:
        """Thread: fan engine outputs out to the per-request asyncio queues."""
        while True:
            try:
                kind, rid, payload = self.out_q.get(timeout=1.0)
            except queue.Empty:
                self._check_ranks()
                continue
            if kind == "hb":
                self.watchdog.beat(rid)
                self._check_ranks()
                continue
            if kind == "ready":
                self.ready += 1
                print(f"[server] DP rank {rid} ready ({self.ready}/{self.args.dp})", flush=True)
                if self.ready == self.args.dp:
                    self.watchdog.ready()
            elif kind == "error":
                self.loop.call_soon_threadsafe(self._deliver, rid, ("error", payload))
            elif kind == "stats":
                self.cache_stats[rid] = payload
            else:
                self.loop.call_soon_threadsafe(self._deliver_batch, payload)

    def _check_ranks(self) -> None:
        """Dead or hung rank: fail open requests, kill every rank (the survivors spin in NCCL otherwise), exit non-zero."""
        reason = self.watchdog.check([p.is_alive() for p in self.procs])
        if reason is None:
            return
        print(f"[server] {reason}; failing open requests and exiting", flush=True)
        for rid in list(self.streams):
            self.loop.call_soon_threadsafe(self._deliver, rid, ("error", reason))
        for p in self.procs:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2)  # let the error deliveries reach the clients
        os._exit(3)

    def _deliver(self, rid: str, item: tuple) -> None:
        q = self.streams.get(rid)
        if q is not None:
            q.put_nowait(item)

    def _deliver_batch(self, batch: list[tuple]) -> None:
        for rid, token_id, finished, reason, prompt_len in batch:
            q = self.streams.get(rid)
            if q is not None:
                q.put_nowait(("token", token_id, finished, reason, prompt_len))

    def _load_image_geometry(self, model: str) -> tuple[int | None, Any]:
        """(image placeholder id, image -> token count) from the checkpoint's config, the same geometry the ranks'
        multimodal processor uses; (None, None) for a checkpoint without image input."""
        try:
            from deepinfer.hugging_face.processor import load_processor_config
            from deepinfer.ve.processor.image_processor import compute_image_layout

            cfg = load_processor_config(model)
        except Exception as e:  # noqa: BLE001 - text-only checkpoint or tree: image parts get a 400
            print(f"[server] image input disabled: {type(e).__name__}: {e}", flush=True)
            return None, None
        image_token_id = cfg["image_token_id"]
        placeholder_ids = self.tokenizer.encode("<｜deepseek_image｜>", add_special_tokens=False)
        if placeholder_ids != [image_token_id]:
            print(f"[server] image input disabled: placeholder encodes to {placeholder_ids}, config says {image_token_id}", flush=True)
            return None, None

        def num_tokens(width: int, height: int) -> int:
            return compute_image_layout(
                width,
                height,
                patch_size=cfg["patch_size"],
                downsample_ratio=cfg["downsample_ratio"],
                max_n_token=cfg["max_image_tokens"],
                min_pixels=cfg["min_pixels"],
                max_wh_ratio=cfg["max_wh_ratio"],
            ).num_tokens

        print(f"[server] image input enabled: placeholder id {image_token_id}", flush=True)
        return image_token_id, num_tokens

    def thinking_mode(self, body: dict) -> str:
        kwargs = body.get("chat_template_kwargs") or {}
        for key in ("thinking", "enable_thinking"):
            if key in kwargs:
                return "thinking" if kwargs[key] else "chat"
        return self.args.thinking_mode

    @staticmethod
    def _parse_reasoning_effort(value):
        """low|high|max or 1-100 (bool is not a number here); anything else is None so the next source is used."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if 1 <= value <= 100 else None
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("low", "high", "max"):
                return text
            if text.isdigit() and 1 <= int(text) <= 100:
                return int(text)
        return None

    def reasoning_effort(self, body: dict):
        """Effort for the "Reasoning Effort: N" prefix (rendered in thinking mode only). A request value (chat_template_kwargs.reasoning_effort, then top-level reasoning_effort) wins over --reasoning-effort; an invalid value falls through to the next source, and None lets the checkpoint encoder use its own default (high)."""
        kwargs = body.get("chat_template_kwargs") or {}
        for value in (kwargs.get("reasoning_effort"), body.get("reasoning_effort"), getattr(self.args, "reasoning_effort", "high")):
            parsed = self._parse_reasoning_effort(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _messages(body: dict) -> list[dict]:
        messages = [dict(m) for m in body["messages"]]
        if body.get("tools"):
            if not messages or messages[0].get("role") != "system":
                messages.insert(0, {"role": "system", "content": ""})
            messages[0]["tools"] = body["tools"]
        return messages

    def render_request(self, body: dict) -> tuple[list[int], str, list[LoadedImage], list[int]]:
        """-> (prompt ids with one placeholder per image, thinking mode, images in prompt order, the ids as the engine
        runs them: placeholders expanded to each image's token count). Raises ImageInputError for a client error."""
        if not check_part_types(body["messages"]):
            ids, mode = self.render_prompt(body)
            return ids, mode, [], ids
        if self.image_token_id is None:
            raise ImageInputError("image inputs are not supported by this backend; send text only")
        mode = self.thinking_mode(body)
        try:
            # No text fallback here: dropping the images would answer about content the model never saw.
            prompt, media = self.encode_messages(
                self._messages(body), thinking_mode=mode, reasoning_effort=self.reasoning_effort(body), return_multi_modal_data=True
            )
        except ValueError as e:
            raise ImageInputError(str(e)[:300]) from None
        a = self.args
        images = load_images(
            media["images"],
            max_images=getattr(a, "max_images_per_request", 16),
            max_bytes=getattr(a, "max_image_bytes", 20 << 20),
            allow_fetch=getattr(a, "allow_image_url_fetch", False),
        )
        ids = self.prompt_tokenizer.encode(prompt)
        engine_ids = expand_placeholders(ids, self.image_token_id, [self._image_layout(im.width, im.height) for im in images])
        return ids, mode, images, engine_ids

    def render_prompt(self, body: dict) -> tuple[list[int], str]:
        """-> (prompt ids, thinking mode the prompt was rendered in). Text parts only; see render_request."""
        mode = self.thinking_mode(body)
        messages = self._messages(body)
        try:
            prompt = self.encode_messages(messages, thinking_mode=mode, reasoning_effort=self.reasoning_effort(body))
        except Exception:  # noqa: BLE001 - trace messages the reference encoder rejects
            # Keep the request (and its prompt length) instead of failing the benchmark.
            self.stats["encode_fallbacks"] += 1
            parts = ["<｜begin▁of▁sentence｜>"]
            for m in messages:
                content = m.get("content") or ""
                if isinstance(content, list):
                    content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
                if m.get("tool_calls"):
                    content += json.dumps(m["tool_calls"], ensure_ascii=False)
                tag = {"user": "<｜User｜>", "assistant": "<｜Assistant｜>", "tool": "<｜User｜>"}.get(m.get("role"), "")
                parts.append(tag + content)
            if body.get("tools"):
                parts.insert(1, json.dumps(body["tools"], ensure_ascii=False))
            prompt = "".join(parts) + "<｜Assistant｜></think>"
            mode = "chat"  # the fallback closes the reasoning block itself
        return self.prompt_tokenizer.encode(prompt), mode

    @staticmethod
    def affinity_key(body: dict) -> bytes | None:
        """Stable per-conversation key: the first user message (AgentX's cache-bust marker lives there and is
        constant across a trajectory's turns, and forked subagents inherit it)."""
        for m in body.get("messages", []):
            if m.get("role") == "user":
                content = m.get("content") or ""
                if isinstance(content, list):
                    content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
                return hashlib.sha1(content[:4096].encode("utf-8", "ignore")).digest()
        return None

    def submit(
        self,
        prompt_ids: list[int],
        sampling: dict,
        key: bytes | None = None,
        use_cache: bool = True,
        images: list[LoadedImage] | None = None,
    ) -> tuple[str, asyncio.Queue]:
        rid = uuid.uuid4().hex
        if self.args.routing == "affinity" and key is not None:
            rank = int.from_bytes(key[:4], "little") % self.args.dp
        else:
            rank = min(range(self.args.dp), key=lambda r: self.load[r])
        self.load[rank] += 1
        self.owner[rid] = rank
        q: asyncio.Queue = asyncio.Queue()
        self.streams[rid] = q
        self.stats["requests"] += 1
        payload = {"prompt_token_ids": prompt_ids, "sampling": sampling, "use_cache": use_cache}
        if images:
            payload["images"] = [(im.data, (im.width, im.height)) for im in images]
        self.in_qs[rank].put(("add", rid, payload))
        return rid, q

    def release(self, rid: str, aborted: bool) -> None:
        rank = self.owner.pop(rid, None)
        self.streams.pop(rid, None)
        if rank is None:
            return
        self.load[rank] -= 1
        if aborted:
            self.stats["aborted"] += 1
            self.in_qs[rank].put(("abort", rid, None))
        else:
            self.stats["finished"] += 1


def _with_content(message: dict, content_parts: list[str], stops: list[str]) -> dict:
    """Non-streaming message with the stop-filtered content (the parser's own content is unfiltered)."""
    if stops:
        content = "".join(content_parts)
        message["content"] = content if content or not message.get("tool_calls") else None
    return message


def build_app(fe: Frontend) -> FastAPI:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

    app = FastAPI()

    @app.on_event("startup")
    async def _startup() -> None:
        fe.loop = asyncio.get_running_loop()
        threading.Thread(target=fe.dispatch_forever, daemon=True).start()

    @app.get("/health")
    async def health():
        if fe.watchdog.failure:
            return JSONResponse({"status": "failed", "reason": fe.watchdog.failure}, status_code=503)
        ok = fe.ready == fe.args.dp
        return JSONResponse({"status": "ok" if ok else "loading", "ready_ranks": fe.ready}, status_code=200 if ok else 503)

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": fe.model_name, "object": "model", "owned_by": "deepinfer"}]}

    # Not at /metrics: aiperf scrapes that path automatically and InferenceX's aggregator
    # rejects metric families it has no backend adapter for.
    # SGLang-native endpoints that an upstream final-wire proxy calls around every chat request.
    @app.post("/v1/tokenize")
    async def tokenize(request: Request):
        """Chat request -> the exact prompt ids this server would run (same rendering as /v1/chat/completions)."""
        body = await request.json()
        if not isinstance(body.get("messages"), list) or not body["messages"]:
            return JSONResponse({"detail": "messages required"}, status_code=400)
        try:
            # With images, count the tokens the engine prefills (each image expanded), so the proxy's budget is right.
            _, _, _, engine_ids = await asyncio.to_thread(fe.render_request, body)
        except ImageInputError as e:
            return JSONResponse({"detail": str(e)}, status_code=400)
        advertised = fe.args.advertised_max_model_len or fe.args.max_model_len
        return {"count": len(engine_ids), "tokens": engine_ids, "max_model_len": advertised}

    @app.post("/generate")
    async def generate(request: Request):
        """Prefix-cache warm-up probe. There is no cross-request prefix cache here, so warming is a no-op: report the
        prompt length with cached_tokens 0 immediately, and the real chat request prefills the whole prompt."""
        body = await request.json()
        ids = body.get("input_ids")
        if not isinstance(ids, list):
            return JSONResponse({"detail": "input_ids required"}, status_code=400)
        return {"text": "", "meta_info": {"prompt_tokens": len(ids), "cached_tokens": 0, "completion_tokens": 0,
                                          "id": body.get("rid"), "finish_reason": {"type": "length", "length": 0}}}

    @app.post("/open_session")
    async def open_session(request: Request):
        body = await request.json()
        return body.get("session_id")

    @app.post("/close_session")
    async def close_session(request: Request):
        await request.json()
        return None

    @app.post("/abort_request")
    async def abort_request(request: Request):
        """The proxy aborts by its own rid; requests here are released when the client stream closes, so ack only."""
        await request.json()
        return {"success": True}

    @app.get("/deepinfer/metrics")
    async def metrics():
        lines = [f"deepinfer:{k}_total {v}" for k, v in fe.stats.items()]
        lines += [f'deepinfer:num_requests_running{{dp_rank="{r}"}} {n}' for r, n in enumerate(fe.load)]
        for r, st in sorted(fe.cache_stats.items()):
            lines += [f'deepinfer_hicache:{k}{{dp_rank="{r}"}} {v}' for k, v in st.items()]
        pt = fe.prompt_tokenizer
        lines += [f'deepinfer_tokenizer:{k}{{backend="{pt.name}"}} {v}' for k, v in pt.metrics().items()]
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        if fe.watchdog.failure:
            return JSONResponse({"error": {"message": fe.watchdog.failure}}, status_code=503)
        if fe.ready != fe.args.dp:
            return JSONResponse({"error": {"message": "engine loading"}}, status_code=503)
        body = await request.json()
        try:
            # Image parts go to the engine's multimodal processor; other non-text parts (audio, files) get a 400.
            prompt_ids, mode, images, engine_ids = await asyncio.to_thread(fe.render_request, body)
        except ImageInputError as e:
            return JSONResponse({"error": {"message": str(e), "type": "invalid_request_error"}}, status_code=400)
        prompt_len = len(engine_ids)  # the length the engine prefills
        max_tokens = body.get("max_completion_tokens") or body.get("max_tokens") or 4096
        if prompt_len + 1 > fe.args.max_model_len:
            return JSONResponse({"error": {"message": f"prompt has {prompt_len} tokens > max_model_len"}}, status_code=400)
        max_tokens = max(1, min(int(max_tokens), fe.args.max_model_len - prompt_len))
        sampling = dict(
            temperature=float(body.get("temperature", 1.0)),
            top_p=float(body.get("top_p", 1.0)),
            ignore_eos=bool(body.get("ignore_eos", False)),
            max_tokens=max_tokens,
        )
        if body.get("seed") is not None:
            sampling["seq_seed"] = int(body["seed"])
        try:
            stop = StopMatcher(parse_stop(body.get("stop")))  # applied to content text; the engine has no stop strings
            # response_format → engine structured output (xgrammar); delayed past </think> in thinking mode
            so_args = build_so_args(body, thinking=mode == "thinking", think_end_token_ids=fe.think_end_token_ids)
        except ValueError as e:
            return JSONResponse({"error": {"message": str(e)}}, status_code=400)
        if so_args is not None:
            sampling["so_args"] = so_args
        fe.stats["prompt_tokens"] += prompt_len
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        # Non-standard request field: "prefix_cache": false bypasses the host prefix cache lookup (A/B checks).
        # Image prompts skip it too: its key is the token ids, and every image's tokens are the same placeholder ids.
        use_cache = bool(body.get("prefix_cache", True)) and not images
        rid, q = fe.submit(prompt_ids, sampling, fe.affinity_key(body), use_cache=use_cache, images=images)
        created = int(time.time())
        cid = f"chatcmpl-{rid}"
        detok = IncrementalDetokenizer(fe.tokenizer)
        parser = AssistantOutputParser(mode == "thinking", fe.parse_tool_calls)
        stopped_early = False

        def filter_content(deltas: list[dict]):
            """Pass parser deltas through the stop matcher; only `content` is filtered. Stops yielding once a stop hits."""
            for delta in deltas:
                if stop.stopped:
                    return
                if "content" in delta:
                    text = stop.feed(delta["content"])
                    if text:
                        yield {"content": text}
                else:
                    yield delta

        def chunk(delta: dict, finish: str | None = None, usage: dict | None = None) -> str:
            obj = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": fe.model_name,
                "choices": [] if usage else [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            if usage:
                obj["usage"] = usage
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        async def tokens():
            """Yield (text_delta, finish_reason) until the request finishes."""
            while True:
                item = await q.get()
                if item[0] == "error":
                    raise RuntimeError(item[1])
                _, token_id, finished, reason, _ = item
                text = detok.add(token_id)
                fe.stats["completion_tokens"] += 1
                if finished:
                    yield text, ("length" if detok.num_tokens >= max_tokens else "stop")
                    return
                yield text, None

        usage = lambda: {
            "prompt_tokens": prompt_len,
            "completion_tokens": detok.num_tokens,  # noqa: E731
            "total_tokens": prompt_len + detok.num_tokens,
        }

        if body.get("stream"):

            async def sse():
                nonlocal stopped_early
                done = False
                try:
                    yield chunk({"role": "assistant", "content": ""})
                    async for text, finish in tokens():  # noqa: B007  (the last finish reason is reported below)
                        for delta in filter_content(parser.feed(text)):
                            yield chunk(delta)
                        if stop.stopped:
                            stopped_early = True  # a stop string matched: finish now and cancel the engine request
                            yield chunk({}, "stop")
                            break
                        if finish:
                            tail, tool_calls, override = parser.finish()
                            for delta in filter_content(tail):
                                yield chunk(delta)
                            flushed = stop.flush()
                            if flushed:
                                yield chunk({"content": flushed})
                            if tool_calls:
                                yield chunk({"tool_calls": tool_calls})
                            yield chunk({}, override if override and finish == "stop" else finish)
                    done = True
                    if include_usage:
                        yield chunk({}, usage=usage())
                    yield "data: [DONE]\n\n"
                finally:
                    fe.release(rid, aborted=not done or stopped_early)

            return StreamingResponse(sse(), media_type="text/event-stream")

        done = False
        try:
            finish = None
            content_parts: list[str] = []
            async for text, finish in tokens():  # noqa: B007  (the last finish reason is reported below)
                content_parts += [d["content"] for d in filter_content(parser.feed(text)) if "content" in d]
                if stop.stopped:
                    stopped_early = True
                    finish = "stop"
                    break
            done = True
        finally:
            fe.release(rid, aborted=not done or stopped_early)
        if stopped_early:
            tool_calls, override = [], None
        else:
            tail, tool_calls, override = parser.finish()
            content_parts += [d["content"] for d in filter_content(tail) if "content" in d]
            content_parts.append(stop.flush())
        if override and finish == "stop":
            finish = override
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": fe.model_name,
            "choices": [{"index": 0, "message": _with_content(parser.message(tool_calls), content_parts, stop.stops), "finish_reason": finish}],
            "usage": usage(),
        }

    return app


def main() -> None:
    args = parse_args()
    args.model = str(Path(args.model).expanduser().resolve())
    os.environ.setdefault("WORLD_SIZE", "1")
    os.environ.setdefault("RANK", "0")
    fe = Frontend(args)
    fe.start()

    import uvicorn

    uvicorn.run(build_app(fe), host=args.host, port=args.port, log_level="warning", timeout_keep_alive=900)


if __name__ == "__main__":
    main()
