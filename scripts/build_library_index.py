"""Generate docs/index.html: the central DSH documentation library index, covering every documentation page of docs/.

Organisation: the three risk controls and OWASP first, then architecture and diagrams, use cases, features, agents (A2A),
inference and capacity, operations, records, and a complete A-Z table of every page with its served status.
The historical curated index is retained as source data; the landing page uses current control and capability navigation.
Pages that carry internal hostnames or operations detail and were never part of the served manual stay "repository only"
(listed, not linked) until their owner decides; see HELD. Deterministic, stdlib only; `--check` verifies the committed index.
"""
import argparse
import base64
import hashlib
import json
import html
import importlib.util
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
DATA = DOCS / 'security-data'
spec = importlib.util.spec_from_file_location('build_security_pages', ROOT / 'scripts/build_security_pages.py')
sec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sec)

EXCLUDE_DIRS = ('context-evidence/', 'security-data/', 'internal-runbooks/')
# Private pages are NEVER linked or served, even when an earlier generation served them (the manual route is public).
PRIVATE = {'TOOLS_AND_RISKS_REGISTER': 'private assessment draft, not served (the manual is public)', 'OPERATIONS_AND_TROUBLESHOOTING_MANUAL': 'Legacy mixed manual contains cluster rolling restart, failure recovery and privileged maintenance procedures; end-user workflows have dedicated user guides. Existing C8 denial retained.', 'sdk-qualification-composition/P3_RUNNER_README': 'Disposable operator namespace/quota/Job/admission/observation/cleanup qualification runner procedure. Existing C8 denial retained.', 'INSTALL': 'Complete Kubernetes installation procedure with build/render/apply/rollout commands and cluster prerequisites.', 'INSTALLATION_WALKTHROUGH': 'Operator installation sequence: existing PVC/Secret inputs, server dry-run/diff, supporting controls, private workload startup, manual publication and rollback.', 'ENTERPRISE_ROOT_CA_SETUP': 'Enterprise trust/SSL-inspection operator procedure extracting CA, creating ConfigMaps and rolling out cluster configuration.', 'CREDENTIAL_OPERATIONS': 'Privileged credential-service deployment plus DPAPI custody/unseal, encrypted snapshot/restore and disposable cluster acceptance; distinct from end-user Credentials UI.', 'DSH_SETUP_AND_STRESS_TEST_GUIDE': 'Generated HTML counterpart of the explicitly operator setup/stress guide; public bundle mandatory seed currently exposes its embedded procedures.', 'INFRA_ADMIN_P2P_NOTE_20261030': 'Infrastructure-admin coordination/change plan with operational GPU/network alternatives and privileged command appendices, not an ordinary workspace-use lesson.', 'sdk-qualification-composition/D11_D13_OPENSHELL_PROPOSAL': 'Existing internal qualification lease/policy/rollback-owner protocol proposal; not classified by architecture keywords.', 'sdk-qualification-composition/P0_DESIGN_OPENSHELL_LANE': 'Existing internal Kubernetes qualification design, service-account/admission and Job sequence; preserve internal source/history.', 'sdk-qualification-composition/VERIFY_MOUNTS_REDESIGN': 'Existing unreviewed security redesign draft; preserve explicit publication hold, not a runtime PASS.'}
PUBLICATION_HOLDS = {
    'sdk-qualification-composition/VERIFY_MOUNTS_REDESIGN': 'unreviewed OpenShell security design draft; not approved for public publication',
}
A2A_STATUS = "A2A handoff (Claude Code to Deep Agents via the broker and per-task guard) was re-verified live on 10 Nov 2026; the governed qualification track, the DSH Python SDK, approval cases and chat delegation remain being qualified."  # exact wording ordered by the owner (USER-RULE-A2A-J6-DEMO-WORDING); never say the feature is operational
LIVE_RELEASE = 'documentation-20261144'  # immutable allowlist reference only; not a live served-body receipt


def live_members():
    # Public repository membership only: not served/live acceptance. No private release artifact.
    return {p.relative_to(DOCS).as_posix() for p in DOCS.rglob('*') if p.is_file()}
# Never linked from the served library until the owner decides: internal hostnames or operations detail (reviewed 10 Nov 2026).
HELD = {
    'DYNAMIC_APP_GATEWAY': 'internal hostnames and gateway operations detail',
    'REGISTRY_DELIVERY_AND_RKE2': 'internal registry and cluster hostnames',
    'OPERATIONS_AND_TROUBLESHOOTING_MANUAL': 'internal hostnames and operator procedures',
    'FIRST_COME_WORKSPACES': 'internal hostnames (a sanitised copy is in the public repository)',
    'ADMIN_DASHBOARD': 'internal hostnames',
    'END_TO_END_1M_ROLLOUT_20261016': 'internal hostnames in a rollout record',
    'MANAGED_CLAUDE_AND_TRUEFORGE': 'internal hostnames and managed-client settings',
    'RDT_CONTROL_CLOSURE_PROGRESS_20261015': 'internal hostnames in a progress record',
    'SECONDARY_REGISTRY_STATUS_20261024': 'internal hostnames in a status record',
    'SECONDARY_REGISTRY': 'registry credential procedures',
    'sdk-wheel-0.2.2a2/SDK_WHEEL_ADMISSION_NOTE_0.2.2a2': 'internal hostnames in an admission note',
    'DA_WORKSPACE_DESIGN_REVIEW_20261015': 'internal hostnames in a design review',
    'FLEXIBLE_DEPLOYMENT': 'internal addresses and credential procedures',
    'media/main-test-status-video': 'internal hostnames',
    'sdk-qualification-composition/D11_D13_OPENSHELL_PROPOSAL': 'cluster-operations material for the qualification run',
    'sdk-qualification-composition/P0_DESIGN_OPENSHELL_LANE': 'cluster-operations material for the qualification run',
    'sdk-qualification-composition/P3_RUNNER_README': 'cluster-operations material for the qualification run',
    'sdk-qualification-composition/VERIFY_MOUNTS_REDESIGN': 'unreviewed draft security design for the OpenShell lane (cluster-operations detail)',
    'DSH_CODE_VIDEO_INDEX': 'links to video and review files that are not in the repository',
    'REGISTRY_INDEX_CURRENT': 'links to video and review files that are not in the repository',
}
# (category key, title, filename-pattern list); first match wins, order matters.
CATEGORIES = [
    ('risks', 'The three risk controls, OWASP and safety layers', [
        r'^THREE_RISK', r'SECURITY', r'OWASP', r'AGENT_SAFETY', r'TOOLS_AND_RISKS', r'PER_USER_ISOLATION', r'FEATURE_MATRIX', r'COMPARISON_PHASE_A', r'RDT_PILOT', r'^FEATURE_CONTROL_TRACEABILITY$', r'^LIBRARY_CURRENT_STATE$']),
    ('architecture', 'Architecture, system design and diagrams', [
        r'ARCHITECTURE', r'^HARNESS_TERMINOLOGY$', r'GOVERNED_HARNESS_(READING|EXECUTIVE|ROADMAP)', r'PLATFORM_GUIDE', r'SHARED_PLATFORM', r'INGRESS', r'GATEWAY', r'REGISTRY',
        r'RKE2', r'DNS', r'FOUR_', r'DIAGRAM', r'INFRA_ADMIN']),
    ('usecases', 'Use cases, scenarios, courses and guided tours', [
        r'SCENARIO', r'COURSE', r'TOUR', r'WALKTHROUGH', r'CURRENT_GUIDE', r'USE_CASE', r'EXERCISE', r'EXPERIENCE', r'VIDEO', r'^PRESENTATION_EDITION$']),
    ('agents', 'Agents, A2A and managed clients', [
        r'A2A', r'AGENT', r'RUNTIME_COMPARISON', r'MANAGED_', r'CLIENT', r'TRUEFORGE', r'KILO', r'CLAUDE', r'DEEP', r'^BANKING_']),
    ('inference', 'Inference, GPU, capacity and speed', [
        r'CAPACITY', r'SPEED', r'GPU', r'LLM_', r'SCHEDULING', r'CONTEXT_OPTIM', r'1M', r'ONE_M']),
    ('features', 'Features and user and administrator guides', [
        r'USER_MANUAL', r'USER_', r'ADMIN', r'APP_', r'SELF_SERVICE', r'SIGNUP', r'CREDENTIAL', r'PACKAGES', r'TERMINAL', r'NOTEBOOK', r'LDAP', r'SETUP']),
    ('operations', 'Operations, deployment and upstream', [
        r'OPERATIONS', r'DEPLOY', r'UPSTREAM', r'PUBLICATION', r'LIVE_', r'ROLLOUT', r'CORPORATE', r'ENTERPRISE', r'LEGACY', r'ACCEPTANCE', r'CITATION', r'PATCH']),
]
RECORDS = ('records', 'Engineering records, reviews and archive')
CAT_TITLE = {k: t for k, t, _ in CATEGORIES}
CAT_TITLE[RECORDS[0]] = RECORDS[1]
ORDER = [k for k, _, _ in CATEGORIES] + [RECORDS[0]]


def esc(s):
    return html.escape(s, quote=True)


def title_of(path):
    with path.open(encoding='utf-8', errors='replace') as stream:
        text = stream.read(65536)  # Metadata only; embedded media bodies are not titles.
    if path.suffix == '.html':
        m = re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I) or re.search(r'<h1[^>]*>(.*?)</h1>', text, re.S | re.I)
        t = re.sub(r'<[^>]+>', '', m.group(1)) if m else path.stem
    else:
        m = re.search(r'^#\s+(.+)$', text, re.M)
        t = m.group(1) if m else path.stem
    t = re.sub(r'\s+', ' ', html.unescape(t)).strip()
    return t.replace('Governed Harness', 'MultiHarness').replace('Governed harness', 'MultiHarness') if t else path.stem


def collect():
    live = live_members()
    stems = {}
    for p in sorted(DOCS.rglob('*')):
        rel = p.relative_to(DOCS).as_posix()
        if not p.is_file() or p.suffix not in ('.html', '.md') or rel.startswith(EXCLUDE_DIRS):
            continue
        if rel == 'index.html' or rel.startswith('archive/') and False:
            continue
        stems.setdefault(rel[:-len(p.suffix)], {})[p.suffix] = p
    docs = []
    for stem, forms in sorted(stems.items(), key=lambda kv: kv[0].lower()):
        if stem == 'index' or stem in PRIVATE:
            continue  # private pages are not even listed
        main = forms.get('.html') or forms['.md']
        cat = RECORDS[0]
        base = stem.split('/')[-1].upper()
        for key, _, pats in CATEGORIES:
            if any(re.search(pt, base) for pt in pats):
                cat = key
                break
        if stem.startswith(('archive/', 'sdk-wheel', 'test-course')) or re.search(r'_20261\d{3}$', stem):
            cat = RECORDS[0] if cat not in ('risks',) else cat
        served_now = any((stem + e) in live for e in forms)
        docs.append({'stem': stem, 'title': title_of(main), 'forms': sorted(forms), 'cat': cat, 'held': PRIVATE.get(stem) or PUBLICATION_HOLDS.get(stem) or (None if served_now else HELD.get(stem))})
    # A page that links to a repository-only page would pull it into the served bundle through link traversal: hold it too.
    changed = True
    while changed:
        changed = False
        held_targets = {d['stem'] + e for d in docs if d['held'] for e in d['forms']}
        for d in docs:
            if d['held'] or '.html' not in d['forms'] or (d['stem'] + '.html') in live:
                continue
            text = (DOCS / (d['stem'] + '.html')).read_text(encoding='utf-8', errors='replace')
            base = Path(d['stem']).parent
            for href in re.findall(r'href="([^"#?]+)"', text):
                if re.match(r'(https?:|mailto:)', href):
                    continue
                target = (base / href).as_posix()
                target = re.sub(r'^\./', '', target)
                if target in held_targets:
                    d['held'] = 'links to a repository-only page (' + target + ')'
                    changed = True
                    break
    return docs


def link(d):
    if d['held']:
        return '<span class="pill x">repository only</span>'
    out = []
    for ext in ('.html', '.md'):
        if ext in d['forms']:
            out.append('<a href="%s%s">%s</a>' % (d['stem'], ext, ext[1:].upper()))
    return ' '.join(out)


def title_link(d):
    if d['held']:
        return esc(d['title'])
    ext = '.html' if '.html' in d['forms'] else '.md'
    return '<a href="%s%s">%s</a>' % (d['stem'], ext, esc(d['title']))


# Bind these to the two exact owner-provided public reference editions.
# User-confirmed reference, 11 November 2026. Link only the public rendered edition.
# The companion tool-and-risk workbook remains an internal reference, never served.
CANONICAL_REFERENCE_PAGES = ({
    'path': 'ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html',
    'title': 'Architecture draft: two foundation diagrams, actual source and evidence limits',
    'source_filename': 'On_prem_AI_analysis_architecture_draft.pptx',
    'source_sha256': '27cd3a8a0008da8186b1e8018872291cad164a6586045e8ff935a1385ca335db',
}, {
    'path': 'THREE_RISK_CONTROLS.html',
    'title': 'Private risk-workbook alignment: three control layers and cross-layer audit',
    'source_filename': '20261109_tools_risks.xlsx',
    'source_sha256': '214e604a349bf1955171504f4ba42e1f59fb01101fc717a4d9453ef6d860d937',
})


def control_svg_data_uri():
    data = (DOCS / 'diagrams/multiharness-three-risk-control-path.svg').read_bytes()
    if hashlib.sha256(data).hexdigest() != '2243794e1c18f25f92e390a07dcedab799eabd5de325d50d8f6ef8464d9fc736':
        raise ValueError('Control diagram differs from the approved public source bytes')
    return 'data:image/svg+xml;base64,' + base64.b64encode(data).decode('ascii')


def control_first_overview(docs):
    cards = [
        ('1', 'Policy / human control', 'Judge purpose, bind task ownership, choose an allowed profile and record exceptions. Approval never grants a forbidden capability.',
         'THREE_RISK_CONTROLS.html'),
        ('2', 'Harness / deterministic control', 'Enforce trusted dispatch, argument checks, confirmation and budgets; distinguish terminal and subprocess bypass paths.',
         'THREE_RISK_CONTROLS.html'),
        ('3', 'Infrastructure / resource control', 'Constrain runtime identity, network, storage and resources; independently authorize SQL, filesystem and service access.',
         'THREE_RISK_CONTROLS.html'),
    ]
    parts = ['<section aria-labelledby="controls"><h2 id="controls">Start with the three risk controls</h2><div class="grid">']
    for number, title, description, href in cards:
        parts.append('<article class="card"><h3>Control layer ' + number + ': ' + esc(title) + '</h3><p>' + esc(description) + '</p><a href="' + esc(href) + '">Read the controls and user workflows</a></article>')
    parts.append('</div></section>')
    if CANONICAL_REFERENCE_PAGES:
        parts.append('<section><h2>Canonical feature and control references</h2><p>Read these source documents together with the three risk controls.</p><ul>')
        for reference in CANONICAL_REFERENCE_PAGES:
            parts.append('<li><a href="' + esc(reference['path']) + '">' + esc(reference['title']) + '</a></li>')
        parts.append('</ul><p>The source workbook stays private. Its J/K/L control layers and M cross-layer audit are explained without publishing workbook contents. Leakage, damage and containment remain separate risk objectives.</p></section>')
    parts.append('<section><h2>One task through the control boundaries</h2><div tabindex="0" role="region" aria-label="Scrollable control diagram" style="overflow-x:auto;max-width:100%"><img style="min-width:960px" src="' + control_svg_data_uri() + '" alt="An authorized user task enters guardrails, runs with bounded tools in a private workspace, passes result verification, and returns through an authenticated output route. Leakage, damage and result exposure are checked across this path."></div><a href="diagrams/multiharness-three-risk-control-path.svg">Open full-size control diagram</a><p class="lede">Control architecture and intended boundaries. Use feature-level evidence and recorded tests to distinguish configured controls from observed enforcement.</p></section>')
    paths = [
        ('Use MultiHarness', [('DSH_USER_MANUAL.html', 'Everyday workspace, agent and artifact workflows'), ('DSH_GUIDED_TOUR.html', 'Guided tour'), ('COURSE_GUIDE.html', 'Courses and video lessons')]),
        ('Agents and execution', [('AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html', 'Runtime choices and execution boundaries'), ('MANAGED_CLIENT_SUPPORT.html', 'Managed client compatibility'), ('A2A_TASK_DELEGATION.html', 'Agent-to-agent delegation and recorded qualification')]),
        ('Applications and data', [('APP_URLS_AND_INGRESS.html', 'Open and share applications'), ('APP_SERVICE_SUPERVISION.html', 'Managed startup and user controls'), ('USER_CREDENTIAL_MANAGEMENT.html', 'User-managed credentials'), ('SELF_SERVICE_PACKAGES.html', 'Approved package workflows')]),
        ('Architecture and capacity', [('ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html', 'Two foundation diagrams and source-bound architecture'), ('DSH_PLATFORM_GUIDE.html', 'Platform guide'), ('FLEXIBLE_DEPLOYMENT.html', 'Deployment topologies'), ('CAPACITY_REPORT.md', 'Dated capacity observations')]),
        ('Feature coverage and assurance', [('FEATURE_OWASP_REVIEW.html', 'Review of all 80 OWASP mappings, references and risk controls'), ('FEATURE_CONTROL_TRACEABILITY.html', 'All 80 rows: candidate implementation, tests and evidence gaps'), ('FEATURE_MATRIX_BY_OWASP.html', 'Feature matrix by OWASP risk'), ('SECURITY_BY_OWASP.html', 'OWASP control crosswalk'), ('AGENT_SAFETY_LAYERS.html', 'Guardrails, verification and sandbox layers')]),
        ('Banking exercise', [('BANKING_AGENT_REVIEW.html', 'Evidence and comparison'), ('BANKING_CLAUDE_CODE.html', 'Claude Code route'), ('BANKING_DEEP_AGENTS.html', 'Deep Agents route'), ('BANKING_DSH_PYTHON_SDK.html', 'DSH Python SDK route')]),
    ]
    parts.append('<section><h2>Explore by capability and task</h2><div class="grid">')
    for title, links in paths:
        parts.append('<article class="card"><h3>' + esc(title) + '</h3>' + ''.join('<a href="' + esc(path) + '">' + esc(label) + '</a>' for path, label in links) + '</article>')
    parts.append('</div></section><section><h2>Read evidence in context</h2><p>Feature descriptions, source references, executed tests, release receipts and live acceptance are separate records. Historical reviews keep their observation dates; a document or video listing does not establish current runtime qualification. Operational runbooks and private assessment material remain in the internal repository.</p></section>')
    return ''.join(parts)



def current_library_panels(section='status'):
    state=json.loads((DOCS/'LIBRARY_CURRENT_STATE.public.json').read_text(encoding='utf-8'))
    formats=json.loads((DOCS/'LIBRARY_FORMATS.public.json').read_text(encoding='utf-8'))
    location=ROOT/'scripts/build_library_current_state.py'
    spec=importlib.util.spec_from_file_location('library_current_state_index',location)
    current=importlib.util.module_from_spec(spec);spec.loader.exec_module(current)
    return current.index_panels(state,formats,include_status=section=='status',include_formats=section=='formats')


def requirements_module():
    spec = importlib.util.spec_from_file_location('documentation_requirements_index', ROOT / 'scripts/documentation_requirements.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build():
    docs = collect()
    # Public checkout membership, never private package/live acceptance.
    package_members = live_members()
    served = [d for d in docs if not d['held']]
    held = [d for d in docs if d['held']]
    body = [current_library_panels()]
    body.append('<div class="card"><strong>One library, every document.</strong> This index lists all %d documentation pages of the DSH repository: %d are linked, %d are repository-only for now (internal hostnames or operations detail; the owner decides). '
                'It is organised around the <a href="THREE_RISK_CONTROLS.html">three risk controls</a> (policy/human, harness/deterministic, infrastructure/resource; audit spans all), the <a href="SECURITY_BY_OWASP.html">OWASP agentic risks</a>, '
                'the <a href="AGENT_SAFETY_LAYERS.html">three safety layers</a>, then architecture, use cases, features, agents, inference and operations.</div>'
                % (len(docs), len(served), len(held)))
    body.append('<div class="card" id="a2a-status"><strong>Agent-to-agent (A2A) status.</strong> <span>' + esc(A2A_STATUS) + '</span> <a href="A2A_TASK_DELEGATION.html">A2A task delegation</a></div>')
    body.append(control_first_overview(docs))
    body.append(current_library_panels('formats'))
    for key in ORDER:
        rows = [d for d in docs if d['cat'] == key]
        if not rows:
            continue
        body.append('<h2 id="%s">%s <small>(%d)</small></h2><div class="tbl"><table><thead><tr><th>Document</th><th>Formats</th><th>Status</th></tr></thead><tbody>' % (key, esc(CAT_TITLE[key]), len(rows)))
        for d in rows:
            status = ('Included in this library. Qualification evidence is separate.' if any(d['stem'] + e in package_members for e in d['forms']) else 'Repository source; not included in this library') if not d['held'] else 'repository only: ' + esc(d['held'])
            body.append('<tr><td>%s<br><small>%s</small></td><td>%s</td><td>%s</td></tr>' % (title_link(d), esc(d['stem']), link(d), status))
        body.append('</tbody></table></div>')
    body.append('<h2 id="all">All documents A-Z <small>(%d)</small></h2><p class="lede">Every documentation page, one row per document (the HTML edition where there is one). Evidence data files are under <code>context-evidence/</code> in the repository and are not listed.</p>' % len(docs))
    body.append('<div class="tbl"><table><thead><tr><th>Document</th><th>Category</th><th>Formats</th></tr></thead><tbody>'
                + ''.join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (title_link(d), esc(CAT_TITLE[d['cat']]), link(d)) for d in docs)
                + '</tbody></table></div>')
    # The predecessor stays in source history/data; its stale counts are not embedded in the current landing page.
    text = sec.page('MultiHarness Documentation Library', ''.join(body),
                    'The DSH library follows the two exact references, three risk controls and80rows across ten OWASP agentic risks. OpenShell and A2A remain under qualification.')
    text = text.replace('<style>' + sec.CSS, '<style>' + sec.CSS + '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}.grid .card a{display:block;margin:4px 0}.prev{margin-top:12px}details summary{cursor:pointer}', 1)
    # Curated predecessor navigation cannot override current internal-document policy.
    def public_anchor(match):
        href = html.unescape(match.group(1)).split('#', 1)[0].split('?', 1)[0]
        from urllib.parse import unquote, urlsplit
        url = urlsplit(href)
        if url.scheme or url.netloc or not url.path:
            return match.group(0)
        stem = str(Path(unquote(url.path)).with_suffix('')).replace('\\', '/').removeprefix('./')
        return match.group(2) if stem in PRIVATE or stem in PUBLICATION_HOLDS else match.group(0)
    text = re.sub(r'<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>', public_anchor, text, flags=re.I)
    return requirements_module().public_projection_html(requirements_module().canonical_index(text), DOCS / 'index.html'), docs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    text, docs = build()
    data = text.encode('utf-8')
    path = DOCS / 'index.html'
    if args.check:
        if path.read_bytes() != data:
            print('OUT OF DATE: index.html')
            return 1
        return 0
    path.write_bytes(data)
    print('wrote index.html', len(data), 'documents', len(docs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
