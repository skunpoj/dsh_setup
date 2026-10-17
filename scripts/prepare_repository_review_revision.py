"""Prepare a controlled citation revision against the unchanged frozen corpus.

The answer key and original model response are never added to model input.
No deployment mutation or inference is performed by this preparation step.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from prepare_repository_accuracy_test import render_sources


REVISION_RULES = '''
OUTPUT CONTRACT AND SOURCE DISCIPLINE — apply these rules before submitting:
1. Return exactly the same JSON schema requested above, with all 15 answers and report_markdown. In answer.value use ONLY the requested canonical value: bare decimal digits for integers, bare decimal for ratios, lowercase true/false for Boolean answers, minutes:seconds for time (for example 03:07), the exact identifier for a name, or accepted/rejected. Do not append units, formulas, explanations or parentheses to value. Put explanations in the report.
2. For each answer select the CURRENT DSH file explicitly named in the question. For a numeric constant cite its DEFINITION, including the actual literal, not only a use of the variable. A different document repeating the same fact does not satisfy a question naming README. Cite the exact line containing the requested definition/setting, using at most 4 lines where possible and never more than 12.
3. A quote is a contiguous verbatim substring of the cited source lines, 8–160 characters. Select only the relevant fragment; do not rewrite syntax, normalize whitespace, repair punctuation, add ellipses or copy a long surrounding paragraph. Check the quote against the source before returning JSON.
4. Every material narrative claim must have a narrow supporting citation, maximum 12 lines each. Use multiple separate narrow citations when necessary; do not expand a citation to cover a whole section. Keep the narrative 1400–1800 words, not including the answers. Use at least eight distinct source blocks. Prefer current executable definitions and actual test assertions; comments are descriptions, not executed assertions.
5. Classify claims explicitly in prose: frozen implementation/configuration, recorded test observation, historical checkpoint, or recommendation. CURRENT means the frozen repository version; it does NOT establish fresh deployed behavior. Do not claim this review changed or tested Production. Source absence cannot prove a negative (including absence of an approved SLA). Do not assert an exclusive architecture or resource-sharing statement unless the cited source establishes it.
6. Treat historical and current admission behavior separately; do not infer that a current guard existed at an older checkpoint. Separate bootstrap defaults/templates from private user-routing behavior. Inspect the relevant routing implementation before describing topology. Distinguish container host RAM/resource limits from GPU memory, KV cache and temporary attention workspace; cite the actual resource field for memory quantities.
7. A NetworkPolicy excerpt establishes its declared rules, not the complete effective egress boundary: policies can combine additively. Do not infer all effective traffic is blocked from one policy excerpt. Distinguish declared network controls from recorded runtime network tests. Explain the limits of that evidence, without inventing a new test or closure.
8. Do not present throughput samples as guarantees, source review as live acceptance, or one long request as proof that two maximum-length requests fit. Preserve uncertainty; where support is insufficient say that the supplied evidence does not establish the claim. Avoid unsupported universal words such as only/all/always/never.
9. Before final output audit each answer's canonical value, CURRENT requested path, supporting definition line, exact quote length and range. Audit each narrative citation for entailment, not just an existing line number. If a conclusion cannot be supported, remove it or state it as a recommendation/unknown. Do not describe this self-check as independent verification.
'''

GROUNDED_NARRATIVE_RULES = '''
NARRATIVE REGRESSION CONTRACT — source support must be correct in YOUR output:
The previous generated draft confused mount-list assertions with profile restoration, and cited candidate construction for a later concurrent-edit check. Do not repeat those substitutions. Retrieve the actual implementation branch for each claim, not merely a nearby function or plausible comment.
Extend the JSON object with claim_checks: [{"id":"ROLLBACK_HASH","claim":"one narrow source-backed statement","citation":{"source_id":"S0001","start_line":1,"end_line":3,"quote":"exact source fragment"}}]. Return exactly these seven unique IDs: ROLLBACK_HASH, MOUNT_PRESERVATION, CONCURRENT_EDIT_REFUSAL, SIDECAR_INSERTION, TOKENIZER_CALL, TRANSPORT_SCOPE, CACHE_PROBE_ABORT. Each claim must describe only what its cited lines establish. Quote 8–100 exact contiguous characters, range at most 12 lines.
ROLLBACK_HASH must cite the restore branch's saved-profile hash verification AND restored-byte equality, not the separate candidate volume assertions. MOUNT_PRESERVATION must cite the candidate assertions comparing volumes and mounts. CONCURRENT_EDIT_REFUSAL must cite the later deployment readback/comparison/refusal, not candidate validation. SIDECAR_INSERTION must cite the actual container-list append, not only the sidecar object declaration. TOKENIZER_CALL must cite the HTTP request/invocation, not only validation of returned IDs. TRANSPORT_SCOPE must describe the test fixture accurately and include both managed-origin timeout assertions and its listed unrelated-origin cases; do not call this a new live test. CACHE_PROBE_ABORT must cite the timeout plus acknowledged-abort conversion to CacheProbeMiss, not merely the catch.
In report_markdown use the same evidence consistently. If describing different mechanisms in one sentence, attach separate citations to each clause. Do not copy a claim from this instruction as evidence. Do not cite a comment as an executed assertion. For sidecar identity and insertion, cite definition and append separately. For HTTP invocation, returned-ID validation and dispatch refusal, cite each separate branch. Treat a recorded diagnosis as a recorded diagnosis, not a causal proof from a failed-trial row. Do not claim an absent SLA, exclusive sharing, guaranteed handover or guaranteed restoration under every failure mode.
Keep the six-section narrative 1,400–1,800 words by a counter that includes headings and citation IDs. Aim at 1,500–1,650, approximately 230 prose words per section plus citations. Provide substantive explanation of execution/default alignment, admission/ordinary concurrency, cold and conditional cached latency, memory, compaction, and a recommended verification/rollback workflow. Use at least eight source blocks. Keep every answer quotation under 100 characters and all values canonical. An incomplete claim ledger, overbroad range or unsupported statement is a failure: correct it BEFORE returning. Do not claim your self-audit is independent verification.
The entire response, including claim_checks, must fit the existing output allowance. No tools, no external calls, no invented test outcomes. Return only the complete JSON. The held-out answer key and previous responses are not provided.
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--grounded-narrative', action='store_true')
    a = ap.parse_args()
    spec = json.loads((a.baseline/'reconstruction-specification.json').read_text(encoding='utf-8'))
    blocks = json.loads((a.baseline/'selected-sources.json').read_text(encoding='utf-8'))
    instructions = spec['instructions'] + REVISION_RULES
    if a.grounded_narrative: instructions += GROUNDED_NARRATIVE_RULES
    # New provenance prefix prevents reuse of the previous review's initial prefix.
    prefix = 'Controlled repository-review revision 2. Frozen sources unchanged; stronger citation contract.\n'
    if a.grounded_narrative:
        prefix = 'Source-grounded narrative regression run 3. Preserve actual implementation-to-claim alignment.\n'
    questions = spec['questionsJSON']
    prompt = render_sources(blocks, instructions, questions, prefix)
    a.output.mkdir(parents=True, exist_ok=False)
    for name in ['selected-sources.json', 'answer-key.json', 'questions.json']:
        shutil.copyfile(a.baseline/name, a.output/name)
    spec.update(instructions=instructions, promptPrefix=prefix,
                promptSHA256=hashlib.sha256(prompt.encode()).hexdigest())
    spec['comparisonPolicy'] = 'Same source blocks and held-out answers; revised instructions only. Previous model output and answer key excluded from prompt.'
    for name, content in [('prompt.txt', prompt), ('instructions.txt', instructions),
                          ('reconstruction-specification.json', json.dumps(spec, indent=2))]:
        (a.output/name).write_text(content, encoding='utf-8')
    print(json.dumps({'sources': len(blocks), 'promptSHA256': spec['promptSHA256'],
                      'promptBytes': len(prompt.encode())}))


if __name__ == '__main__':
    main()
