"""Narrow, fail-closed overlay for the pinned SGLang DSV4 image.

Reserve part of the existing chunk budget for small uncached input tails. This
does not increase the total chunk budget, park requests or alter KV ownership.
"""
import ast
import hashlib
import sys
from pathlib import Path

EXPECTED_SHA256 = 'a27879971d17033955847d79b2e6ebc5604da419fe6ffee43c5c107479ffc97e'
ANCHOR = '''        if self.chunked_req is not None:
            self.chunked_req.init_next_round_input()
            self.chunked_req = adder.add_chunked_req(self.chunked_req)
'''
REPLACEMENT = '''        # DSH_INTERACTIVE_PREFILL_RESERVATION_V2
        # Keep a lane for <=512 uncached input tokens. A long resumed chunk
        # otherwise consumes the entire budget before the waiting queue runs.
        # All KV/SWA admission checks below remain the upstream implementation.
        interactive_reserve = 0
        if (
            self.chunked_req is not None
            and self.waiting_queue
            and adder.rem_chunk_tokens is not None
            and adder.rem_chunk_tokens >= 2 * self.page_size
        ):
            def interactive_tail(req):
                # FCFS leaves this counter unset for the DSV4 cache, which
                # does not advertise fast prefix matching. Classify once;
                # upstream admission refreshes the match before allocation.
                if not getattr(req, "_bot_interactive_classified", False):
                    from sglang.srt.managers.schedule_policy import match_prefix_for_req
                    match_prefix_for_req(self.tree_cache, req, include_req=True)
                    req._bot_interactive_classified = True
                return max(1, len(req.origin_input_ids) + len(req.output_ids)
                           - getattr(req, "num_matched_prefix_tokens", 0))

            interactive = [req for req in self.waiting_queue
                           if interactive_tail(req) <= 512]
            if interactive:
                # Stable partition: preserve FCFS within each lane. Long work
                # always retains at least one page of prefill progress.
                selected = set(interactive)
                self.waiting_queue = interactive + [
                    req for req in self.waiting_queue if req not in selected]
                interactive_reserve = min(
                    512,
                    ((adder.rem_chunk_tokens // 2) // self.page_size)
                    * self.page_size,
                )
                adder.rem_chunk_tokens -= interactive_reserve

        if self.chunked_req is not None:
            self.chunked_req.init_next_round_input()
            self.chunked_req = adder.add_chunked_req(self.chunked_req)
        adder.rem_chunk_tokens = (
            adder.rem_chunk_tokens + interactive_reserve
            if adder.rem_chunk_tokens is not None else None
        )
'''


def patch(original):
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA256:
        raise ValueError('SGLang scheduler differs from reviewed image; refusing overlay')
    source = original.decode()
    if source.count(ANCHOR) != 1:
        raise ValueError('Expected scheduler insertion point is not unique')
    result = source.replace(ANCHOR, REPLACEMENT)
    ast.parse(result)
    return result


if __name__ == '__main__':
    source, destination = map(Path, sys.argv[1:])
    destination.write_text(patch(source.read_bytes()))
