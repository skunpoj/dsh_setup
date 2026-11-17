from documentation_requirements import public_projection_html
"""Generate the OWASP-first security pages of the DSH library from docs/security-data/*.json.

Inputs (single source of truth):
  docs/security-data/features.json          the 80-feature matrix with its tags (asi_primary, asi_all, risk, layer, cia, control_type)
  Private operator register inputs are excluded from this public generator.
  docs/security-data/dq-agent-safety.source.html   the DQ agent safety layers page, unmodified
Outputs (docs/): SECURITY_BY_OWASP.html, FEATURE_MATRIX_BY_OWASP.html, AGENT_SAFETY_LAYERS.html,
                 Private assessment generation is excluded from this public source.
Deterministic and stdlib only; `--check` verifies the committed pages equal the generated ones.
The tags are drafts for owner review; the pages say so. Nothing here certifies OWASP compliance.
"""
import argparse
import collections
import html
import json
from pathlib import Path
import sys

DOCS = Path(__file__).resolve().parents[1] / 'docs'
DATA = DOCS / 'security-data'

ASI = {
    'ASI01': ('Agent Goal Hijack', 'Execution and network containment limit consequences; no explicit goal-integrity/injection test matrix.'),
    'ASI02': ('Tool Misuse and Exploitation', 'Restricted workloads and existing service permissions; no complete tool/argument approval assessment.'),
    'ASI03': ('Identity and Privilege Abuse', 'Private identities, routes and mounts; remote entitlements and identity lifecycle remain separately owned.'),
    'ASI04': ('Agentic Supply Chain Vulnerabilities', 'Pinned dependency transfer, offline validation and review of source builds/hooks; no full agent/MCP provenance assessment.'),
    'ASI05': ('Unexpected Code Execution', 'Non-root execution, limited mounts/capabilities and restricted egress constrain execution; they do not prevent all hostile code in writable scope.'),
    'ASI06': ('Memory and Context Poisoning', 'Private history isolation is described; persisted malicious context, provenance and safe reset are not explicitly assessed.'),
    'ASI07': ('Insecure Inter-Agent Communication', 'User routing does not establish authenticated agent messages, replay protection or delegated authority.'),
    'ASI08': ('Cascading Failures', 'Resource admission and local limits; downstream failure propagation, circuit breaking and end-to-end recovery remain workflow-specific.'),
    'ASI09': ('Human-Agent Trust Exploitation', 'Explicit sharing and handling responsibilities; misleading output and meaningful human review require workflow tests.'),
    'ASI10': ('Rogue Agents', 'Runtime restrictions limit blast radius; autonomous scope drift, detection and containment need explicit tests.'),
}
RISK = {'1': 'Risk 1 - external leakage', '2': 'Risk 2 - damage or excessive access', '3': 'Risk 3 - result exposure'}
LAYER = {'G': 'Guardrails', 'V': 'Verification', 'S': 'Sandbox',
         'Guardrails': 'Guardrails', 'Verification': 'Verification', 'Sandbox': 'Sandbox'}
CIA = {'C': 'Confidentiality', 'I': 'Integrity', 'A': 'Availability'}
LAYER_CLASS = {'Guardrails': 'g', 'Verification': 'v', 'Sandbox': 's'}

NAV = ('<nav><a href="index.html">Library index</a><a href="SECURITY_BY_OWASP.html">Security by OWASP</a>'
       '<a href="FEATURE_MATRIX_BY_OWASP.html">Feature matrix by OWASP</a><a href="AGENT_SAFETY_LAYERS.html">Safety layers</a>'
       '<a href="THREE_RISK_CONTROLS.html">Three risk controls</a>'
       '<a href="GOVERNED_HARNESS_COMPARISON_PHASE_A.html">Full 80-feature comparison</a></nav>')

CSS = """:root{--bg:#edf2f7;--surface:#fff;--fg:#193047;--muted:#52667a;--line:#bacbd8;--accent:#075985;--g:#2552c9;--gs:#e8edfb;--v:#1f7a4a;--vs:#e3f3ea;--s:#a35a00;--ss:#fbf0df;--stop:#b42318}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#12161d;--surface:#1a2029;--fg:#e3e8f0;--muted:#98a3b5;--line:#3a4453;--accent:#8ec5e8;--g:#8aa8ff;--gs:#1d2740;--v:#6fd39d;--vs:#17301f;--s:#f0b062;--ss:#33281a;--stop:#ff8a7a}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,'Segoe UI',sans-serif}main{max-width:1400px;margin:0 auto;padding:24px 16px 64px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;padding:10px 14px;background:var(--surface);border:1px solid var(--line);border-radius:8px;margin-bottom:20px}
a{color:var(--accent);overflow-wrap:anywhere}h1{margin:.2em 0}h2{margin-top:2em;border-top:1px solid var(--line);padding-top:.8em}h3{margin-bottom:.2em}
.lede{color:var(--muted);max-width:80ch}.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:14px 0}
.note{border-left:4px solid var(--stop);background:var(--surface);padding:10px 14px;margin:14px 0}
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--surface)}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line)}th{background:var(--bg);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.pill{display:inline-block;font:12px/1 ui-monospace,Consolas,monospace;padding:4px 7px;border-radius:3px;margin:0 4px 4px 0;white-space:nowrap}
.pill.g{color:var(--g);background:var(--gs)}.pill.v{color:var(--v);background:var(--vs)}.pill.s{color:var(--s);background:var(--ss)}
.pill.x{border:1px solid var(--line);color:var(--muted)}td.num{text-align:right;font-variant-numeric:tabular-nums}
.heat0{color:var(--muted)}.heat1{background:var(--gs)}.heat2{background:var(--vs)}.heat3{background:var(--ss)}
svg{max-width:100%;height:auto;color:var(--fg)}svg text{fill:currentColor;font-family:system-ui,'Segoe UI',sans-serif}
code{background:var(--bg);padding:1px 5px;border-radius:3px}small{color:var(--muted)}tr.grp td{background:var(--bg);font-weight:600}
"""

STATUS_NOTE = ('Evidence status comes from the full comparison: 63 features are "Designed but not verified", 14 are "Future roadmap", '
               '3 have "A2A source reviewed" status. A tag in this view is a draft grouping for review; it is not an OWASP certification, '
               'and no claim of OWASP compliance is made.')


def esc(s):
    return html.escape(str(s), quote=True)


def load():
    features = json.loads((DATA / 'features.json').read_text(encoding='utf-8'))
    register = {}  # Private assessment payload is not an input to public generation.
    return features, register


def page(title, body, lede=''):
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style></head><body><main>%s<h1>%s</h1>%s%s</main></body></html>\n'
            % (esc(title), CSS, NAV, esc(title), ('<p class="lede">%s</p>' % lede) if lede else '', body))


def layer_pill(layer):
    return '<span class="pill %s">%s</span>' % (LAYER_CLASS.get(layer, 'x'), esc(layer or '-'))


def feature_row(f, with_status=True):
    cells = ['<td class="num">%d</td>' % f['n'], '<td>%s</td>' % esc(f['feature']),
             '<td>%s</td>' % esc(f['risk'] and f['risk']), '<td>%s</td>' % layer_pill(f['layer']),
             '<td>%s</td>' % esc(f['cia']), '<td>%s</td>' % esc(f['control_type'])]
    if with_status:
        cells.append('<td>%s</td>' % esc(f['evidence_status']))
    return '<tr>%s</tr>' % ''.join(cells)


def counts(feats):
    primary = collections.Counter(f['asi_primary'] for f in feats if f['kind'] == 'feature')
    tagged = collections.Counter(a for f in feats if f['kind'] == 'feature' for a in f['asi_all'])
    grid = collections.Counter((f['asi_primary'], f['layer']) for f in feats if f['kind'] == 'feature')
    risks = collections.Counter((f['asi_primary'], f['risk']) for f in feats if f['kind'] == 'feature')
    return primary, tagged, grid, risks


def flow_svg():
    """DSH call path through the three layers (generic; see AGENT_SAFETY_LAYERS for the DQ original)."""
    def box(x, y, w, h, title, lines, cls):
        stroke = {'g': 'var(--g)', 'v': 'var(--v)', 's': 'var(--s)'}[cls]
        fill = {'g': 'var(--gs)', 'v': 'var(--vs)', 's': 'var(--ss)'}[cls]
        out = '<rect x="%d" y="%d" width="%d" height="%d" rx="6" fill="%s" stroke="%s" stroke-width="1.5"/>' % (x, y, w, h, fill, stroke)
        out += '<text x="%d" y="%d" font-size="13" font-weight="600">%s</text>' % (x + 10, y + 22, esc(title))
        for i, line in enumerate(lines):
            out += '<text x="%d" y="%d" font-size="11.5">%s</text>' % (x + 10, y + 42 + 17 * i, esc(line))
        return out
    parts = ['<svg viewBox="0 0 1100 330" role="img" aria-label="A request crosses guardrails, verification and sandbox before it reaches data or the outside; the result returns through ownership and masking checks.">',
             '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>',
             '<rect x="10" y="110" width="150" height="110" rx="6" fill="var(--surface)" stroke="currentColor" stroke-width="1.5"/>',
             '<text x="22" y="136" font-size="13" font-weight="600">User / agent</text><text x="22" y="156" font-size="11.5">request, tool call,</text><text x="22" y="173" font-size="11.5">code to run</text>',
             box(200, 90, 230, 150, 'GUARDRAILS (policy)', ['sign-in and owner binding', 'role and tool policy', 'human approval, budgets', 'ordered fallbacks'], 'g'),
             box(470, 90, 230, 150, 'VERIFICATION (checks)', ['argument and path checks', 'tool and package vetting', 'replay / duplicate guard', 'structured errors'], 'v'),
             box(740, 90, 230, 150, 'SANDBOX (isolation)', ['per-user workspace', 'No Internet segment', 'CPU / memory / time quotas', 'scoped, read-only mounts'], 's'),
             '<line x1="160" y1="165" x2="198" y2="165" stroke="currentColor" stroke-width="1.5" marker-end="url(#a)"/>',
             '<line x1="430" y1="165" x2="468" y2="165" stroke="currentColor" stroke-width="1.5" marker-end="url(#a)"/>',
             '<line x1="700" y1="165" x2="738" y2="165" stroke="currentColor" stroke-width="1.5" marker-end="url(#a)"/>',
             '<rect x="1000" y="110" width="95" height="110" rx="6" fill="var(--surface)" stroke="currentColor" stroke-width="1.5"/>',
             '<text x="1010" y="140" font-size="12.5" font-weight="600">Data and</text><text x="1010" y="158" font-size="12.5" font-weight="600">services</text><text x="1010" y="180" font-size="11">own rights</text>',
             '<line x1="970" y1="165" x2="998" y2="165" stroke="currentColor" stroke-width="1.5" marker-end="url(#a)"/>',
             '<path d="M1047,222 V285 H85 V222" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url(#a)"/>',
             '<text x="330" y="305" font-size="12">result returns: owner-bound routing, audience policy, masking, audit record</text>',
             '<path d="M315,92 V30 H85 V108" fill="none" stroke="var(--stop)" stroke-width="1.5" stroke-dasharray="4 3" marker-end="url(#a)"/>',
             '<text x="100" y="22" font-size="12" fill="var(--stop)" style="fill:var(--stop)">denied / needs approval / stopped</text>',
             '</svg>']
    return ''.join(parts)


def build_overview(features):
    feats = features['features']
    primary, tagged, grid, risks = counts(feats)
    total = sum(1 for f in feats if f['kind'] == 'feature')
    status = collections.Counter(f['evidence_status'] for f in feats)
    body = ['<p class="note"><strong>Reading note.</strong> ' + esc(STATUS_NOTE) + '</p>',
            '<div class="card"><strong>Design principle: flag, pause, human in the loop.</strong> When a request, a result or an agent action is suspicious or exceeds policy, the platform flags it and pauses it for a person to decide; no AI agent decides or signs off on its own control. '
            'Acceptance tests for goal hijack (ASI01), tool misuse (ASI02), inter-agent communication (ASI07) and human-agent trust (ASI09) are run and signed off by named human owners; an AI session may prepare test scripts but does not accept results. <small>(Owner instruction of 10 Nov 2026; the same pattern as the approval gate in <a href="AGENT_SAFETY_LAYERS.html">the DQ safety layers</a>.)</small></div>']
    body.append('<h2>How the frames fit</h2><div class="tbl"><table><thead><tr><th>Frame</th><th>Question</th><th>Source</th><th>Use here</th></tr></thead><tbody>'
                '<tr><td><strong>OWASP ASI01-ASI10</strong></td><td>What can go wrong with an agent?</td><td>OWASP Top 10 for Agentic Applications 2026</td><td>Primary grouping of the 80 features</td></tr>'
                '<tr><td><strong>Risk objectives</strong></td><td>Which outcome is protected?</td><td>External leakage, damage or excessive access, result exposure</td><td>Original risk-objective IDs are retained separately from enforcement layers</td></tr><tr><td><strong>Three control layers</strong></td><td>Where is authority controlled?</td><td><a href="THREE_RISK_CONTROLS.html">Policy/human; harness/deterministic; infrastructure/resource</a></td><td>Workbook J/K/L; audit spans all layers in M</td></tr>'
                '<tr><td><strong>Three layers</strong></td><td>Where in the call path is it enforced?</td><td><a href="AGENT_SAFETY_LAYERS.html">DQ agent safety layers</a></td><td>Tag: Guardrails, Verification or Sandbox</td></tr>'
                '<tr><td><strong>C/I/A and four control types</strong></td><td>Which property, and who enforces it?</td><td>Tool-and-risk assessment</td><td>Tags: confidentiality, integrity, availability; policy/human, harness/deterministic, infrastructure/resource, audit/evidence</td></tr>'
                '</tbody></table></div>')
    body.append('<h2>One request through the layers</h2><div class="card">' + flow_svg() +
                '<p><small>The harness and the infrastructure enforce; model instructions do not. Every stop point returns a denial, a hint or a fallback to the agent, never a silent success.</small></p></div>')
    body.append('<h2>Coverage grid: primary OWASP risk by layer</h2><p class="lede">Each cell counts the features whose primary risk is the row and whose enforcement layer is the column ('
                + str(total) + ' features; the 4 evidence rows are separate). Features can carry several OWASP tags; the last column counts every feature tagged with the risk.</p>')
    rows = []
    for key in sorted(ASI):
        cells = ''.join('<td class="num %s">%d</td>' % ('heat0' if not grid[(key, l)] else 'heat' + {'Guardrails': '1', 'Verification': '2', 'Sandbox': '3'}[l], grid[(key, l)])
                        for l in ('Guardrails', 'Verification', 'Sandbox'))
        rc = ''.join('<td class="num">%d</td>' % risks[(key, r)] for r in '123')
        rows.append('<tr><td><a href="#%s">%s %s</a></td>%s<td class="num"><strong>%d</strong></td>%s<td class="num">%d</td></tr>'
                    % (key.lower(), key, esc(ASI[key][0]), cells, primary[key], rc, tagged[key]))
    body.append('<div class="tbl"><table><thead><tr><th>OWASP risk</th><th>Guardrails</th><th>Verification</th><th>Sandbox</th><th>Primary</th><th>Risk 1</th><th>Risk 2</th><th>Risk 3</th><th>Tagged (all)</th></tr></thead><tbody>'
                + ''.join(rows) + '</tbody></table></div>')
    thin = [k for k in sorted(ASI) if primary[k] <= 3]
    body.append('<p class="note"><strong>Where the feature list is thin.</strong> ' + ', '.join('%s (%d primary)' % (k, primary[k]) for k in thin) +
                '. These match the residual items in the OWASP crosswalk ("no explicit test matrix") and are the first candidates for the proposed additions in the <a href="FEATURE_MATRIX_BY_OWASP.html#proposed">matrix</a>.</p>')
    ev = [f for f in feats if f['kind'] == 'evidence']
    for key in sorted(ASI):
        mine = [f for f in feats if f['kind'] == 'feature' and f['asi_primary'] == key]
        also = [f for f in feats if f['kind'] == 'feature' and key in f['asi_all'] and f['asi_primary'] != key]
        st = collections.Counter(f['evidence_status'][:24] for f in mine)
        body.append('<h2 id="%s">%s - %s</h2><p>%s</p>' % (key.lower(), key, esc(ASI[key][0]), esc(ASI[key][1])))
        if mine:
            body.append('<p><small>%d primary feature(s); status: %s</small></p>' % (len(mine), '; '.join('%s %d' % (k, v) for k, v in st.most_common())))
            body.append('<div class="tbl"><table><thead><tr><th>#</th><th>Feature</th><th>Risk</th><th>Layer</th><th>C/I/A</th><th>Control type</th><th>Evidence status</th></tr></thead><tbody>'
                        + ''.join(feature_row(f) for f in mine) + '</tbody></table></div>')
        else:
            body.append('<p>No feature has this as its primary risk.</p>')
        if also:
            body.append('<p><small>Also tagged %s: %s</small></p>' % (key, ', '.join('#%d %s' % (f['n'], esc(f['feature'])) for f in also)))
    body.append('<h2 id="evidence">Evidence and status rows (apply to every risk)</h2><div class="tbl"><table><thead><tr><th>#</th><th>Row</th><th>Evidence status</th></tr></thead><tbody>'
                + ''.join('<tr><td class="num">%d</td><td>%s</td><td>%s</td></tr>' % (f['n'], esc(f['feature']), esc(f['evidence_status'])) for f in ev) + '</tbody></table></div>')
    body.append('<h2>Status counts</h2><p>' + '; '.join('%s: %d' % (esc(k), v) for k, v in status.most_common()) + '.</p>')
    body.append('<p><small>Source: OWASP GenAI Security Project, Top 10 for Agentic Applications 2026 (December 2025). Risk names are attributed to OWASP; the DSH mapping is our analysis, not an OWASP endorsement.</small></p>')
    return page('Security by OWASP: the DSH controls grouped by the ten agentic risks', ''.join(body),
                'The OWASP Top 10 for Agentic Applications is the primary grouping of the 80 DSH features. Each feature also carries its DSH risk, its enforcement layer and its confidentiality/integrity/availability property.')


# On-prem AI analysis architecture draft (user-supplied PPTX, 10 slides, "draft for review", not deployed). Generic control
# principles only, mapped by DSH to OWASP categories (inferred); product-specific identity, directory and storage details are not reproduced.
PPTX_NAME = 'On_prem_AI_analysis_architecture_draft.pptx'
PPTX_SHA256 = '27cd3a8a0008da8186b1e8018872291cad164a6586045e8ff935a1385ca335db'
PPTX = {
    'ASI01': [(2, 'Policy judges purpose and exceptions; independently enforced permissions bound the effect even if the model follows malicious text.'),
              (6, 'Prompt labelling reduces confusion but cannot guarantee obedience; access controls, not document wording, prevent privilege expansion.')],
    'ASI02': [(1, 'Model proposes, tools execute: a trusted dispatcher validates every tool request.'),
              (3, 'SQL checks are defence in depth; the source is SELECT only at the endpoint, writes go only to explicitly scoped scratch.'),
              (7, 'Typed operation ID, fixed executable and validated arguments; not a free-form shell.'),
              (8, 'Typed Git operations, not arbitrary flags.')],
    'ASI03': [(1, 'Separate authority, not merely tool names; the session fixes project and identity, never a model-supplied field.'),
              (4, 'An elevated profile requires exact approval; no database or repository credentials in the code runtime.'),
              (5, 'OS identity, not a password in the call; read-only inputs, writable scratch with a quota.'),
              (9, 'Delegated credentials may reach workers; effective identities must be verified.')],
    'ASI04': [(4, 'Package installation is a separate, human-maintained image lifecycle.'),
              (8, 'Trusted scanning must not depend on repository-controlled hooks; restrict external helpers and configuration.'),
              (10, 'The DevOps connector stays off until network and authentication are agreed; read-only first; no remote-write credential.')],
    'ASI05': [(4, 'Code is arbitrary execution, not a safe DSL: isolated runtime, no privileged mode, default-deny egress, resource limits, descendants terminated.'),
              (5, 'Python faces the same hard limits as any other access route.'),
              (9, 'Cluster code needs cluster controls; submission is a separate trust boundary.')],
    'ASI06': [(6, 'Optional local retrieval is read-only; ingest is separate; project scope comes from the session; sources stay independently exportable.'),
              (5, 'Retained outputs need a protected publish and versioning path.')],
    'ASI07': [(1, 'Multi-agent orchestration uses the same authorization gate; agent-to-agent delegation must not broaden authority.')],
    'ASI08': [(2, 'Hard timeouts, quotas and concurrency limits; cancellation must actually stop child processes and underlying work.'),
              (9, 'Queue limits, caps and cancellation for cluster submission.')],
    'ASI09': [(2, 'An expensive request can route to a human; approval permits only an allowed operation or profile, never a forbidden capability.'),
              (4, 'Reproducible wrong code remains wrong: human scientific review is still required.')],
    'ASI10': [(2, 'Audit spans every layer (user, project and run ID, actual arguments, approval, identity, result); records are protected from agent writes.'),
              (1, 'The model never receives operating-system, database or repository credentials.')],
}


def build_matrix(features):
    feats = features['features']
    # Current documentary review is separate from historical tags and runtime evidence.
    body = ['<p><a href="FEATURE_OWASP_REVIEW.html">12 Nov row-by-row OWASP / two-reference / three-control review</a>. The review explains each row; it does not create operational acceptance.</p>',
            '<p class="note"><strong>Recorded primary OWASP groupings retained; current operational acceptance remains separate.</strong> The historical documentary grouping is retained; this source revision does not add owner acceptance or passing operational tests. The status of every feature is shown in its evidence column; see the <a href="#legend">evidence status legend</a>. The complete 19-column comparison stays in the <a href="GOVERNED_HARNESS_COMPARISON_PHASE_A.html">full comparison</a>; the same data is in <a href="security-data/features.json">security-data/features.json</a>.</p>']
    body.append('<p>Current reference alignment: <a href="ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html">original on-prem architecture draft and two foundation diagrams</a>; <a href="THREE_RISK_CONTROLS.html">private workbook J/K/L control layers and M cross-layer audit</a>. The workbook payload stays private. Leakage, damage and result containment are risk objectives, separate from the policy/human, harness/deterministic and infrastructure/resource enforcement layers. The 76 primary-category rows plus four ALL rows retain every stable feature ID, original runtime comparison and evidence state.</p>')
    # Count each original row once by primary category; secondary mappings overlap.
    assert len(feats) == 80 and sorted(f['n'] for f in feats) == list(range(1, 81))
    assert all(f['asi_primary'] in ASI or (f['kind'] == 'evidence' and f['asi_primary'] == 'ALL') for f in feats)
    body.append('<h2 id="category-summary">Ten OWASP categories</h2><p>Taxonomy: <a href="https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/">OWASP Top 10 for Agentic Applications 2026</a>. Primary assignments count each of the 76 control or roadmap rows once. Four cross-cutting evidence rows apply to all ten categories. Secondary mappings overlap and are not additional features. A category assigns a feature to an OWASP risk; the evidence column says whether its control is verified.</p>')
    summary = []
    RT = (('sdk_standalone', 'DSH Python SDK alone'), ('claude_standalone', 'Claude Code alone'), ('deepagents_standalone', 'Deep Agents alone'))
    def refs(fs):
        return ', '.join('<a href="#feature-%d">#%d</a>' % (f['n'], f['n']) for f in fs) or 'None mapped'
    def standalone_cell(primary, rt):
        # Group the owner-reviewed standalone statements; the first sentence names who supplies the control.
        groups = {}
        for f in primary:
            t = f['runtimes'][rt]
            t = t.split('outside the Multiharness: ', 1)[-1]
            lead = t.split(' Application owner supplies', 1)[0].split(' Administrator supplies', 1)[0].strip()
            groups.setdefault(lead, []).append(f)
        owner = primary[0]['runtimes'][rt].split('outside the Multiharness: ', 1)[-1] if primary else ''
        tail = ''
        for marker in (' Application owner supplies', ' Administrator supplies'):
            if marker in owner:
                tail = marker.strip() + owner.split(marker, 1)[1]
        items = ''.join('<li>%s <small>(%d: %s)</small></li>' % (esc(k), len(v), ', '.join('#%d' % f['n'] for f in v))
                        for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1])))
        return ('<td><small>Outside the multiharness the product has no DSH gateway, so each row below is something the deployer must supply. '
                'Responsibility statements from the full comparison, not a capability test of the product.</small>'
                '<details><summary>%d rows: %d distinct statements</summary><ul>%s</ul><small>%s</small></details></td>'
                % (len(primary), len(groups), items, esc(tail))) if primary else '<td><small>No primary rows in this category: not assessed.</small></td>'
    def pptx_cell(key):
        items = PPTX.get(key, [])
        if not items:
            return '<td><small>No slide maps to this category: not assessed.</small></td>'
        return ('<td><small>Design draft from the on-prem analysis architecture deck: not deployed, not verified. The mapping to this category is DSH inference.</small>'
                '<details><summary>%d slide statement(s)</summary><ul>%s</ul></details></td>'
                % (len(items), ''.join('<li><small>Slide %d.</small> %s</li>' % (n, esc(t)) for n, t in items)))
    for key in sorted(ASI):
        primary = [f for f in feats if f['kind'] == 'feature' and f['asi_primary'] == key]
        secondary = [f for f in feats if f['kind'] == 'feature' and key in f['asi_all'] and f['asi_primary'] != key]
        byrisk = {x: [f for f in primary if f['risk'] == x] for x in '123'}
        st = collections.Counter(f['evidence_status'] for f in primary)
        common = collections.Counter(f['common'] for f in primary)
        mh_items = ''.join('<li>%s <small>(%d)</small></li>' % (esc(k), v) for k, v in common.most_common(3))
        mh = ('<td><small>The DSH gateway, controllers and sandbox put the control in front of the runtime, so these rows are designed as platform controls. '
              'Evidence status, not a pass: %s.</small><details><summary>Top controls (%d of %d distinct)</summary><ul>%s</ul></details></td>'
              % (esc('; '.join('%s %d' % (k, v) for k, v in st.most_common())), min(3, len(common)), len(common), mh_items)) if primary else '<td><small>No primary rows: not assessed.</small></td>'
        risk_cell = '<br>'.join('<strong>%s:</strong> %s' % (esc(RISK[x]), refs(byrisk[x]) if byrisk[x] else 'none') for x in '123')
        summary.append('<tr><th><a href="#%s">%s &mdash; %s</a><br><small>%s</small></th>'
                       '<td>%s<br><small>Features whose single primary category is %s. Each is counted here once; the numbers link to the matrix rows below.</small></td>'
                       '<td>%s<br><small>Tagged %s in the original comparison but counted under another primary category. Not extra features.</small></td>'
                       '<td>%s<br><small>The primary rows grouped by the risk objective they support: leakage, damage or excessive access, result exposure.</small></td>%s%s</tr>'
                       % (key.lower(), key, esc(ASI[key][0]), esc(ASI[key][1]), refs(primary), key, refs(secondary), key, risk_cell, mh,
                          ''.join(standalone_cell(primary, rt) for rt, _ in RT) + pptx_cell(key)))
    body.append('<p class="note"><strong>How to read the comparison columns.</strong> The first four columns list the feature rows by number. The next four compare, for each OWASP category, the multiharness (our gateway, controllers and sandbox) with each of the DSH Python SDK, Claude Code and Deep Agents used alone, outside the multiharness. The standalone cells restate what the full comparison says the deployer must supply; they say nothing about what the product can or cannot do. The last column adds the on-prem AI analysis architecture draft (%s, 10 slides, sha256 %s): a design draft marked for review and not deployed, shown as generic control principles only. No cell is an OWASP certification or a verified result.</p>' % (PPTX_NAME, PPTX_SHA256))
    body.append('<div class="tbl"><table><caption>OWASP category coverage and feature crosswalk</caption><thead><tr><th>OWASP category</th><th>Primary feature IDs</th><th>Secondary feature IDs</th><th>Three risk objectives (primary rows)</th><th>Multiharness itself</th>' + ''.join('<th>%s <small>(outside the multiharness)</small></th>' % n for _, n in RT) + '<th>On-prem analysis architecture draft <small>(PPTX, 10 slides)</small></th></tr></thead><tbody>' + ''.join(summary) + '</tbody></table></div>')
    meaning = {'Designed': 'The control is designed in the source; no runtime test has yet proven it.',
               'Future': 'Planned for a later release; not built.',
               'A2A': 'The agent-to-agent source was reviewed; the deployed behaviour is not yet tested.'}
    stc = collections.Counter(f['evidence_status'] for f in feats)
    body.append('<h2 id="legend">Evidence status legend</h2><div class="tbl"><table><thead><tr><th>Evidence status</th><th>Rows</th><th>Meaning</th></tr></thead><tbody>'
                + ''.join('<tr><td>%s</td><td class="num">%d</td><td>%s</td></tr>' % (esc(k), v, esc(next((m for w, m in meaning.items() if k.startswith(w)), 'See the full comparison.')))
                          for k, v in stc.most_common()) + '</tbody></table></div>')
    body.append('<p><a href="#evidence">Cross-cutting evidence: #63–66</a> · <a href="FEATURE_CONTROL_TRACEABILITY.html">Source, test and acceptance-evidence gaps</a>. Stable feature numbers preserve the full comparison. Rows #67–80 remain roadmap items; no source or runtime status is upgraded by recategorisation.</p><h2>Complete matrix by primary OWASP category</h2>')
    rows = []
    for key in sorted(ASI):
        mine = [f for f in feats if f['kind'] == 'feature' and f['asi_primary'] == key]
        rows.append('<tr class="grp"><td colspan="11" id="%s">%s - %s (%d primary)</td></tr>' % (key.lower(), key, esc(ASI[key][0]), len(mine)))
        for f in mine:
            also = ', '.join(a for a in f['asi_all'] if a != key)
            rows.append('<tr id="feature-%d"><td class="num">%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                        % (f['n'], f['n'], esc(f['feature']), esc(key + (('; also ' + also) if also else '')), esc(f['risk']), layer_pill(f['layer']), esc(f['cia']), esc(f['control_type']),
                           esc(f['evidence_status']), esc(f['common']), esc(f['limitation']), esc(f['recommended'])))
    rows.append('<tr class="grp"><td colspan="11" id="evidence">Evidence and status rows (all risks)</td></tr>')
    for f in feats:
        if f['kind'] == 'evidence':
            rows.append('<tr id="feature-%d"><td class="num">%d</td><td>%s</td><td>ASI01-ASI10</td><td></td><td></td><td></td><td></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                        % (f['n'], f['n'], esc(f['feature']), esc(f['evidence_status']), esc(f['common']), esc(f['limitation']), esc(f['recommended'])))
    body.append('<div class="tbl"><table><thead><tr><th>#</th><th>Feature</th><th>OWASP primary and secondary</th><th>Risk</th><th>Layer</th><th>C/I/A</th><th>Control type</th><th>Evidence status</th><th>Multiharness common control</th><th>Limitation or gap</th><th>Recommended control</th></tr></thead><tbody>'
                + ''.join(rows) + '</tbody></table></div>')
    prop = features.get('proposed', [])
    if not prop:
        body.append('<h2 id="proposed">Proposed additions</h2><p>This stable historical anchor is retained. The current source declares no additional proposals outside the 80; rows 67–80 retain their original roadmap status.</p>')
    if prop:
        body.append('<h2 id="proposed">Proposed additions (not yet part of the 80)</h2><p class="lede">Candidates that fill the thin OWASP rows. They are proposals for owner review and have no evidence yet.</p>'
                    '<div class="tbl"><table><thead><tr><th>Candidate</th><th>Primary risk</th><th>Also</th><th>Risk</th><th>Layer</th><th>Why</th></tr></thead><tbody>'
                    + ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                              % (esc(p['name']), esc(p['asi_primary']), esc(', '.join(p.get('asi_also', []))), esc(p['risk']), layer_pill(p['layer']), esc(p['why'])) for p in prop)
                    + '</tbody></table></div>')
    body.append('<p><small>OWASP Agentic Top 10 mapping by DSH. Not an OWASP certification.</small></p>')
    return page('Feature matrix by OWASP risk', ''.join(body),
                'The 80 DSH features, grouped by their primary OWASP agentic risk, with the DSH risk, the enforcement layer, the confidentiality/integrity/availability property and the control type.').replace('<style>', '<style>body{overflow-wrap:anywhere}.tbl{max-width:100%;min-width:0}', 1).replace('<div class="tbl">', '<div class="tbl" tabindex="0" role="region" aria-label="Scrollable feature comparison">')


def build_layers():
    # Preserve the existing public reference; do not load a private DQ source fixture.
    return (DOCS / 'AGENT_SAFETY_LAYERS.html').read_text(encoding='utf-8')


SCOPE = [
    ('Impala/Hive', 'Conditional', 'Not a DSH platform tool. DSH never grants datalake rights from a login; it applies only when a pilot adds a data connector that runs under the user\'s own authorisation.', '7, 8, 15-17 and a connector row (proposed)'),
    ('Spark job submission', 'Conditional', 'Only where a submitted job runs on another platform; that platform keeps its own outbound and data controls (THREE_RISK_CONTROLS).', '29, 48-51 (proposed: constrained job interface)'),
    ('On-prem vector retrieval', 'Conditional', 'DSH has an optional CPU embedding service; retrieval content must be treated as untrusted data and scoped per project.', '32, 33 (proposed: untrusted retrieved content)'),
    ('Project workspace', 'In scope', 'The per-user and per-environment workspace is the core DSH boundary.', '9-14'),
    ('Restricted OS/shell', 'In scope', 'Terminals and command execution exist in DSH workspaces.', '27, 28, 30'),
    ('Local Python analytics', 'In scope', 'Jupyter and code execution run inside the workspace.', '25, 29, 48-51'),
    ('Local Git', 'In scope', 'Git is used in workspaces; history rewriting should stay gated (proposed addition).', '13, 15-17 (proposed: git history gate)'),
    ('Azure DevOps connector', 'Conditional', 'DSH documents a corporate git bootstrap; an agent-side Azure DevOps connector is not described in the DSH docs [UNKNOWN]. Treat as conditional and start read-only.', '15-17, 22, 31'),
    ('Human approval gate', 'In scope', 'Administrator policy and approval exist as a design item.', '53 (proposed: approval bound to the exact action)'),
    ('Predefined execution profiles', 'In scope', 'Resource budgets are RKE2 requests and limits.', '48-51'),
    ('Timeout and process-tree termination', 'In scope', 'Cancellation, timeout and descendant control are matrix rows.', '30, 41-44'),
    ('Tool-call / retry budget', 'In scope', 'Not in the 80 today; loops and retries are a cascading-failure risk.', 'proposed addition'),
    ('Default-deny agent egress', 'In scope', 'The No Internet default and DNS/proxy controls.', '21-24'),
    ('Project filesystem boundary', 'In scope', 'Task roots, mounts and path checks.', '12-14'),
    ('Credential isolation', 'In scope', 'Scoped secrets, no persistence.', '15-17'),
    ('Vetted immutable analysis environment', 'In scope', 'Curated offline repository and pinned images.', '25, 55-57'),
    ('Tamper-resistant execution', 'In scope', 'Logging, attribution and model-call evidence.', '38-40'),
    ('Reproducible analysis record', 'In scope', 'Evidence required for acceptance; reproducibility of an analysis is not a listed feature.', '66 (proposed addition)'),
    ('Human-mediated external data import', 'In scope', 'Offline operation and curated bundles are the DSH counterpart.', '23, 58 (proposed addition)'),
]

PROPOSED = [
    {'name': 'Per-run limit on tool calls and retries', 'asi_primary': 'ASI08', 'asi_also': ['ASI10'], 'risk': '2', 'layer': 'Guardrails',
     'why': 'Loops and repeated retries of a failing or expensive operation; the DQ design caps steps, queries and time per run.'},
    {'name': 'Approval bound to the exact action', 'asi_primary': 'ASI09', 'asi_also': ['ASI02'], 'risk': '2', 'layer': 'Guardrails',
     'why': 'A vague or session-wide approval can authorise a changed operation; an approval should cover one tool, target and code or diff and expire on change.'},
    {'name': 'Tool argument allow-list and single-statement rule', 'asi_primary': 'ASI02', 'asi_also': ['ASI01'], 'risk': '2', 'layer': 'Verification',
     'why': 'Generic command or query strings let a prompt-injected agent run write or multi-step actions; connectors should expose narrow, validated operations.'},
    {'name': 'Retrieved content treated as untrusted data', 'asi_primary': 'ASI06', 'asi_also': ['ASI01'], 'risk': '3', 'layer': 'Verification',
     'why': 'Documents, repository text and retrieved chunks can carry instructions; they should be data, with source references for review.'},
    {'name': 'Connector scope and destination allow-list', 'asi_primary': 'ASI02', 'asi_also': ['ASI03', 'ASI04'], 'risk': '1', 'layer': 'Sandbox',
     'why': 'A network-enabled connector should reach only its own endpoints with a least-privilege token that the model never sees.'},
    {'name': 'Git history and destructive-operation gate', 'asi_primary': 'ASI02', 'asi_also': ['ASI10'], 'risk': '2', 'layer': 'Guardrails',
     'why': 'Hard reset, clean, rebase, hook or config changes and deleting branches should need confirmation or be denied.'},
    {'name': 'Rerunnable analysis: code, inputs, environment and outputs are recorded', 'asi_primary': 'ASI09', 'asi_also': ['ASI06'], 'risk': '3', 'layer': 'Verification',
     'why': 'A plausible narrative should be tied to the executed code, inputs, environment version and outputs so an analyst can rerun it.'},
    {'name': 'Human-reviewed import of external data', 'asi_primary': 'ASI06', 'asi_also': ['ASI04'], 'risk': '1', 'layer': 'Guardrails',
     'why': 'External data should enter through a deliberate human step with source and scope recorded, not through an agent-side fetch.'},
]


COMPARE = [
    ('Identity and login', 'Project account (@bot) for the workstation and Hadoop directories; how login works is an open question.',
     'AD/LDAP sign-in at the gateway; server-side user-to-environment assignment; a Kerberos principal is a separate, user-owned identity.',
     'BOT: an analyst workstation harness. DSH: a multi-user web platform on Kubernetes, so identity must be bound server-side per user and environment.'),
    ('Data access', 'Impala/Hive over JDBC under Ranger and project accounts; optional Spark.',
     'No built-in datalake connector; a DSH login does not grant database or datalake rights; connected services keep their own permissions.',
     'DSH is the harness, not the data platform. A pilot that adds a connector inherits the BOT controls (read-only SQL allow-list, Ranger, query timeouts).'),
    ('Isolation unit', 'Every service or tool in its own container; only the Azure DevOps connector may reach the network.',
     'One restricted non-root workspace per user and environment (RKE2 pod pair), plus shared platform services.',
     'BOT isolates per tool; DSH isolates per user and environment. Both rely on OS and container limits, not on model instructions.'),
    ('Network', 'No capability to reach the internet; only an allow-listed connector destination.',
     'No Internet is the default environment; a separate Internet environment prepares packages; model fallback to external providers is disabled.',
     'Same intent. DSH adds a deliberate, separate Internet environment because users prepare dependencies.'),
    ('Approval and autonomy', 'Analyst approves consequential or intensive operations; approval is bound to the exact action; retry and tool-call budget.',
     'Administrator policy control and review responsibilities are listed; budgets are RKE2 limits; a per-run tool-call budget and exact-action approval are not listed features.',
     'Gap: both are proposed additions to the 80 (see the feature matrix).'),
    ('Software and packages', 'Vetted immutable environment; the agent cannot install packages.',
     'Curated offline repository and a privileged gate; self-service pinned wheels after an administrator grants Internet access.',
     'Same control, different workflow: DSH lets users request pinned wheels through a reviewed path.'),
    ('Audit and evidence', 'Tamper-resistant execution log; reproducible analysis record.',
     'Logging, audit attribution and model-call evidence are features; the reproducible analysis record is not.',
     'Gap: the reproducible analysis record is a proposed addition.'),
]


def build_register(_register):
    raise ValueError('PRIVATE_ASSESSMENT_EXCLUDED_FROM_PUBLIC_SOURCE')


def build_withdrawn():
    """A neutral stub served at the old register path: a published path must stay in every later generation, its content need not."""
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Page withdrawn</title></head><body><main><h1>Page withdrawn</h1><p>This page\'s content is not published.</p>'
            '<p><a href="index.html">Back to the library index</a></p></main></body></html>\n')


PRIVATE_FULL = None  # Private assessment targets are authority-only; generation already refuses them.


def generate():
    features, register = load()
    features = dict(features)
    features['proposed'] = PROPOSED
    return {
        'SECURITY_BY_OWASP.html': build_overview(features),
        'FEATURE_MATRIX_BY_OWASP.html': build_matrix(features),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail when the committed pages differ from the generated ones')
    args = parser.parse_args(argv)
    pages = generate()
    bad = []
    for name, text in pages.items():
        path = DOCS / name
        data = public_projection_html(text, path).encode('utf-8')
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                bad.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print('wrote', name, len(data))
    if bad:
        print('OUT OF DATE:', ', '.join(bad))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
