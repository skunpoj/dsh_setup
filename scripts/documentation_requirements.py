"""Pure documentation renderer; source description is never runtime acceptance."""

from html import escape
import json
from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def requirements():
    return json.loads((DOCS / "LIBRARY_REQUIREMENTS.public.json").read_text(encoding="utf-8"))


def body():
    parts = []
    for section in requirements()["sections"]:
        text = '<section id="' + section["id"] + '"><h2>' + escape(section["title"]) + "</h2>"
        text += "".join("<p>" + escape(p) + "</p>" for p in section["paragraphs"])
        if section["headers"]:
            text += (
                '<div style="overflow:auto"><table><thead><tr>'
                + "".join("<th>" + escape(c) + "</th>" for c in section["headers"])
                + "</tr></thead><tbody>"
            )
            text += "".join(
                "<tr>" + "".join("<td>" + escape(c) + "</td>" for c in row) + "</tr>"
                for row in section["rows"]
            )
            text += "</tbody></table></div>"
        parts.append(text + "</section>")
    return '<div id="canonical-platform-requirements" style="overflow-wrap:anywhere;min-width:0">' + "".join(parts) + "</div>"


def markdown():
    parts = []
    for section in requirements()["sections"]:
        parts.extend(["", "## " + section["title"], "", *section["paragraphs"]])
        if section["headers"]:
            parts += [
                "",
                "| " + " | ".join(section["headers"]) + " |",
                "| " + " | ".join("---" for _ in section["headers"]) + " |",
            ]
            parts += ["| " + " | ".join(row) + " |" for row in section["rows"]]
    return "\n\n".join(parts)


def canonical_index(text):
    if 'id="canonical-reading-routes"' in text:
        return text
    routes = [
        (
            "DSH_CURRENT_GUIDE.html#canonical-reading",
            "Start here",
            "One current task guide; older pages provide supporting detail.",
        ),
        (
            "THREE_RISK_CONTROLS.html",
            "Two references / three controls",
            "Policy, harness, infrastructure/resource; audit across all.",
        ),
        (
            "ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html",
            "Two architecture maps",
            "Deployment and network/identity/data boundaries; source versus target.",
        ),
        (
            "DSH_CURRENT_GUIDE.html#identity-session-persistence",
            "Identity and persistence",
            "kinit evidence limits, sessions, credentials, mounts and isolation.",
        ),
        (
            "DSH_CURRENT_GUIDE.html#platform-policy",
            "Internal versus cloud",
            "Enterprise DeepSeek/393216 target versus customizable cloud profiles.",
        ),
        (
            "DSH_CURRENT_GUIDE.html#bounded-arena",
            "Bounded arena roadmap",
            "Minimal intervention inside authority; no self-approved deployment.",
        ),
        (
            "FEATURE_MATRIX_BY_OWASP.html",
            "80 features / ten OWASP risks",
            "Stable feature IDs, evidence gaps and inferred mappings.",
        ),
    ]
    panel = '<section id="canonical-reading-routes"><h2>Canonical reading routes</h2><p>Central index: <a href="index.html">/manual/index.html</a>. Read current guidance once through these routes; existing topic URLs and evidence remain intact.</p><ol>'
    panel += (
        "".join(
            '<li><a href="' + href + '">' + escape(title) + "</a> — " + escape(note) + "</li>"
            for href, title, note in routes
        )
        + "</ol></section>"
    )
    text = re.sub(r"(</h1>)", lambda m: m[0] + panel, text, count=1)
    text = text.replace(
        '<h2 id="risks">',
        '<details id="source-catalog"><summary>Complete categorized source catalog and A–Z index</summary><h2 id="risks">',
        1,
    )
    if 'id="source-catalog"' in text:
        text = text.replace("</main>", "</details></main>", 1)
    return text.replace("เธขเธ—", "·")


def apply_guide():
    path = DOCS / "DSH_CURRENT_GUIDE.html"
    text = path.read_text(encoding="utf-8")
    if 'id="canonical-platform-requirements"' not in text:
        text = text.replace("</main>", body() + "</main>", 1)
    else:
        start = text.index('<div id="canonical-platform-requirements"')
        end = text.index("</main>", start)
        text = text[:start] + body() + text[end:]
    risk = requirements()["sections"][1]
    updated = (
        '<section id="chapter-2"><h2>2 Three risk controls</h2><p>'
        + escape(risk["paragraphs"][1])
        + '</p><p><a href="#reference-controls">Canonical control definitions and required evidence</a></p></section>'
    )
    text = re.sub(
        r'<section id="chapter-2">.*?</section>', lambda m: updated, text, count=1, flags=re.S
    )
    path.write_text(text, encoding="utf-8", newline="\n")
    md = DOCS / "DSH_CURRENT_GUIDE.md"
    original = md.read_text(encoding="utf-8")
    original = re.sub(
        r"## 2 Three risk controls.*?(?=\n## 3 )",
        lambda m: "## 2 Three risk controls\n\n" + risk["paragraphs"][1] + "\n\n",
        original,
        count=1,
        flags=re.S,
    )
    if "## One library and one reading route" in original:
        original = original[: original.index("## One library and one reading route")]
    original += markdown() + "\n"
    md.write_text(original, encoding="utf-8", newline="\n")


def box(x, y, width, lines, color="#eaf2fa"):
    lines = [part for line in lines for part in textwrap.wrap(line, max(16, (width - 28) // 8), break_long_words=False)]
    height = 26 + 23 * len(lines)
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="8" fill="{color}" stroke="#486a83"/>'
        + "".join(
            f'<text x="{x + 12}" y="{y + 26 + i * 23}">{escape(line)}</text>'
            for i, line in enumerate(lines)
        )
    )


def arrow(path):
    return (
        '<path d="'
        + path
        + '" fill="none" stroke="#486a83" stroke-width="2" marker-end="url(#edge)"/>'
    )


def diagram(title, description, parts, height=1000):
    marker = "edge-" + title.split(",")[0].split()[0].lower()
    return (
        (
            '<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="'
            + escape(title, quote=True)
            + '" viewBox="0 0 1120 '
            + str(height)
            + '"><title>'
            + escape(title)
            + "</title><desc>"
            + escape(description)
            + '</desc><defs><marker id="edge" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#486a83"/></marker></defs><g font-family="system-ui,sans-serif" font-size="15" fill="#172b40">'
            + "".join(parts)
            + "</g></svg>"
        )
        .replace('id="edge"', 'id="' + marker + '"')
        .replace("url(#edge)", "url(#" + marker + ")")
    )


def deployment_svg():
    parts = [
        box(20, 20, 220, ["Browser / authenticated owner", "Web chat, terminal, app links"]),
        box(330, 20, 260, ["dsh-gateway", "Login, owner route, manual"]),
        box(800, 20, 300, ["Controller / provisioner", "Pod lifecycle, capacity policy"]),
        arrow("M240 60H328"),
        arrow("M590 60H798"),
    ]
    parts += [
        '<rect x="20" y="150" width="1080" height="370" rx="10" fill="#f5f8fb" stroke="#64748b" stroke-dasharray="7 5"/><text x="35" y="178">Per-owner workspace/profile boundary — shared Pod network; placement depends on exact image and overlay</text>'
    ]
    parts += [
        box(40, 205, 220, ["DSH web / terminal", "Owner entry and task context"]),
        box(330, 205, 215, ["DSH Python SDK", "Managed execution route"]),
        box(595, 205, 215, ["Claude Code", "Managed client route"]),
        box(860, 205, 215, ["Deep Agents", "Managed client route"]),
        arrow("M460 100V200"),
        arrow("M260 245H328"),
    ]
    parts += [
        box(40, 365, 220, ["Jupyter / arbitrary code", "Same authority as its UID"]),
        box(330, 365, 215, ["Application processes", "Sidecar not universal"]),
        box(595, 365, 215, ["Local files / tools", "A2A / optional OpenShell", "Source-bound authority"]),
        box(860, 365, 215, ["PVC state / workspace", "History files, not kernel RAM"]),
    ]
    parts += [
        arrow("M437 280V310H570V565"),
        arrow("M702 280V310H570"),
        arrow("M967 280V310H570"),
        arrow("M150 445V480H570V565"),
    ]
    parts += [
        box(
            330,
            570,
            480,
            [
                "Managed inference path",
                "litellm-gateway / context-forwarder",
                "Context/output admission (target)",
            ],
        ),
        box(
            330,
            715,
            480,
            [
                "deepinfer-dspark / DeepSeek backend",
                "sglang-dspark is a separately owned execution role",
            ],
        ),
        arrow("M570 670V713"),
    ]
    parts += [
        box(
            20,
            845,
            510,
            [
                "Controlled connectors → SQL/JDBC, Spark/Livy, HDFS, Git",
                "Independent resource ACLs; bootstrap outside agent shell",
            ],
        ),
        box(
            590,
            845,
            510,
            [
                "Protected gateway / audit state",
                "Not user-workspace owned; no shared credential implied",
            ],
        ),
    ]
    parts += [
        '<text x="20" y="980">Source/reference map, not live readiness. Same UID/mount means shared access; stopped workspace is not accepted.</text>'
    ]
    parts += [arrow("M437 285V335H700V360"), arrow("M700 485V535H280V842"), arrow("M590 100H1110V820H850V842"), arrow("M437 440V505H967V482")]
    return diagram(
        "Deployment, containers, three agents and inference",
        "Two governing references plus source relationships. No current active Pod or universal sidecar topology is asserted.",
        parts,
    )


def network_svg():
    parts = [
        box(
            20,
            20,
            1080,
            [
                "Policy / human → Harness / deterministic → Infrastructure / resource authorization",
                "Audit/evidence spans all three; CIA and leakage/damage/exposure remain objectives",
            ],
        )
    ]
    parts += [
        box(
            20,
            155,
            330,
            ["On-prem Internal", "Approved internal routes", "DeepSeek/LiteLLM + 393216 target"],
        ),
        box(
            395,
            155,
            330,
            [
                "On-prem Internet-enabled",
                "Same enterprise provider restriction",
                "Broad HTTPS bypass unqualified",
            ],
        ),
        box(
            770,
            155,
            330,
            [
                "Customizable cloud / arena",
                "Explicit provider and billing choice",
                "Free default not yet verified",
            ],
        ),
    ]
    parts += [
        arrow("M185 255V320H480V355"),
        arrow("M560 255V355"),
        arrow("M935 255V320H635V355"),
        box(
            300,
            360,
            520,
            [
                "Actual workload boundary",
                "DSH / SDK / Claude / Deep Agents / Jupyter",
                "UID, mounts, environment and effective NetworkPolicy",
            ],
        ),
    ]
    parts += [
        box(
            20,
            550,
            330,
            [
                "Login identity / task owner",
                "AD/LDAP is not kinit",
                "No passwords in agent prompts",
            ],
        ),
        box(
            395,
            550,
            330,
            [
                "Managed model ingress",
                "LiteLLM / context-forwarder",
                "Not data-resource authorization",
            ],
        ),
        box(
            770,
            550,
            330,
            [
                "Network and resource control",
                "Namespace/RBAC, quotas, PVC ACL",
                "Actual selector/traffic tests pending",
            ],
        ),
        arrow("M480 460V500H185V545"),
        arrow("M560 460V545"),
        arrow("M635 460V500H935V545"),
    ]
    parts += [
        box(
            20,
            740,
            510,
            [
                "Kerberos bootstrap / delegated resource identity",
                "Historical FILE:/state/kerberos/ccache, sessions 631–632",
                "Current kinit/klist, renewal and cross-user proof absent",
            ],
        ),
        box(
            590,
            740,
            510,
            [
                "SQL/JDBC, Spark/Livy and raw HDFS",
                "Resource ACLs apply independently on every route",
                "Same-UID code can access the same mounted credentials",
            ],
        ),
    ]
    parts += [
        arrow("M185 650V735"),
        arrow("M935 650V735"),
        arrow("M530 790H588"),
        '<text x="20" y="945">Saved files/history ≠ live kernel/task/session. Separate credential caches, namespaces and mount checks need receipts.</text>',
        '<text x="20" y="978">Blue boxes describe source/design roles; no color certifies current enforcement or remote resource entitlement.</text>',
    ]
    return diagram(
        "Network, identity, credentials, data and persistence boundaries",
        "Internal and customizable cloud policies differ. Kerberos historical references do not establish current identity or isolation.",
        parts,
    )


def apply_architecture():
    path = DOCS / "ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html"
    text = path.read_text(encoding="utf-8")
    svgs = [deployment_svg(), network_svg()]
    index = iter(svgs)
    text, count = re.subn(r"<svg\b.*?</svg>", lambda m: next(index), text, count=2, flags=re.S)
    if count != 2:
        raise ValueError("Exactly two foundation SVGs required")
    if 'id="canonical-boundary-guide"' not in text:
        text = text.replace(
            "</h1>",
            '</h1><section id="canonical-boundary-guide"><h2>Current canonical boundary guide</h2><p><a href="DSH_CURRENT_GUIDE.html#identity-session-persistence">Identity, kinit, sessions and persistence</a> · <a href="DSH_CURRENT_GUIDE.html#platform-policy">Internal/cloud policy</a> · <a href="DSH_CURRENT_GUIDE.html#bounded-arena">Bounded arena roadmap</a>. The numbered source readback below is retained historical evidence, not a fresh fleet scan.</p><p><a href="diagrams/dsh-deployment-runtime.svg">Deployment SVG</a> · <a href="diagrams/dsh-network-identity-data.svg">Network/identity SVG</a></p></section>',
            1,
        )
    path.write_text(text, encoding="utf-8", newline="\n")
    (DOCS / "diagrams").mkdir(exist_ok=True)
    for name, svg in zip(["dsh-deployment-runtime.svg", "dsh-network-identity-data.svg"], svgs):
        (DOCS / "diagrams" / name).write_text(svg, encoding="utf-8", newline="\n")


def apply_aliases():
    aliases = {
        "DSH_USER_MANUAL.html": "canonical-reading",
        "AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html": "identity-session-persistence",
        "DSH_NETWORK_ZONES.html": "platform-policy",
        "UPSTREAM_SYNC_AND_INTERNET_POLICY.html": "platform-policy",
    }
    for name, anchor in aliases.items():
        path = DOCS / name
        text = path.read_text(encoding="utf-8")
        panel = (
            '<section id="canonical-current-guidance"><h2>Current consolidated guidance</h2><p><a href="index.html">Open the central MultiHarness documentation library</a> · <a href="DSH_CURRENT_GUIDE.html#'
            + anchor
            + '">Read the canonical current guide</a> · <a href="ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html">Architecture and trust boundaries</a>. This URL and its supporting detail remain available; dated observations below retain their original scope.</p></section>'
        )
        if 'id="canonical-current-guidance"' not in text:
            text = re.sub(r"(</h1>)", lambda m: m[0] + panel, text, count=1)
        text = text.replace(
            "Approved startup services run in a separate supervisor container.",
            "Approved startup-service placement depends on the image and workspace profile. A template may use a supervisor sidecar; fresh-signup provisioning removes that sidecar, so a separate supervisor container is not universal.",
        )
        text = text.replace(
            "the supervisor runs non-root inside that user&#39;s selected pod.",
            "the supervisor role is configured non-root in the selected owner runtime; actual process/container placement is profile-bound.",
        )
        path.write_text(text, encoding="utf-8", newline="\n")
    md = DOCS / "DSH_USER_MANUAL.md"
    text = md.read_text(encoding="utf-8").replace(
        "Approved startup services run in a separate supervisor container.",
        "Approved startup-service placement is profile/image-bound; a template sidecar is not universal because fresh-signup provisioning removes it.",
    )
    text = text.replace(
        "the supervisor runs non-root inside that user's selected pod.",
        "the supervisor role is configured non-root; actual process/container placement is profile-bound.",
    )
    md.write_text(text, encoding="utf-8", newline="\n")


def apply_reference_coverage():
    topics = [
        (
            "1",
            "Trusted dispatch / separate authority",
            "Architecture: three agent clients, owner runtime and independent resource boundary.",
        ),
        (
            "2",
            "Policy, harness, runtime and resource",
            "Three controls: runtime containment and resource authorization both sit in infrastructure/resource; audit spans all.",
        ),
        (
            "3",
            "SQL/JDBC",
            "Canonical identity section: read-only source ACL, separately scoped scratch; Kerberos remains unverified.",
        ),
        (
            "4",
            "Python runtime",
            "Arbitrary code has OS authority; disposable processes do not imply disposable persistent project files.",
        ),
        (
            "5",
            "Filesystem",
            "Same boundary for tools and equivalent Python/terminal access; RO input and quota-controlled outputs require actual mounts.",
        ),
        (
            "6",
            "Local retrieval",
            "Project-scoped retrieval is knowledge, not authorization; ingestion and access controls remain separate.",
        ),
        (
            "7",
            "Typed helpers",
            "Fixed operations and validated arguments; credential bootstrap is runtime-owned, not agent shell text.",
        ),
        (
            "8",
            "Local Git",
            "Fixed repository/branch and trusted scanning; local history does not grant remote credentials or network.",
        ),
        (
            "9",
            "Spark",
            "Delegation, driver/executor identities, HDFS ACLs, queue limits and cancellation need independent acceptance.",
        ),
        (
            "10",
            "Azure DevOps",
            "Optional connector remains disabled until approved network/auth; cloud DevOps is not implicitly allowed.",
        ),
    ]
    panel = '<section id="governing-reference-coverage"><h2>Coverage of the ten-slide architecture reference</h2><div style="overflow:auto"><table><thead><tr><th>Slide</th><th>Design topic</th><th>Canonical interpretation</th></tr></thead><tbody>'
    panel += "".join(
        "<tr>" + "".join("<td>" + escape(c) + "</td>" for c in row) + "</tr>" for row in topics
    )
    panel += '</tbody></table></div><p>These are derived design interpretations, not implementation acceptance. The original no-agent-Internet design and per-service separation questions must not be silently equated with an Internet-enabled workspace or multiple processes sharing one Pod/UID. Kubernetes NetworkPolicy normally selects Pods, not individual containers; actual selectors and equivalent-code routes need verification.</p><p>All four workbook roles were inspected: scope notes, initial tool/risk sketch, expanded J/K/L/M register, and account/login/autonomy/container-boundary questions. Private tool rows are not published or assumed to be identical to the 80 feature dimensions. <a href="DSH_CURRENT_GUIDE.html#reference-controls">Canonical control definitions</a> · <a href="DSH_CURRENT_GUIDE.html#bounded-arena">Arena roadmap</a>.</p></section>'
    path = DOCS / "THREE_RISK_CONTROLS.html"
    text = path.read_text(encoding="utf-8")
    if 'id="governing-reference-coverage"' not in text:
        text = text.replace("</html>", panel + "</html>", 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    apply_guide()
    apply_architecture()
    apply_aliases()
    apply_reference_coverage()
    path = DOCS / "index.html"
    path.write_text(canonical_index(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()


# Public-source projection only. Private canonical generators remain unchanged.
def _private_source_stem(stem, private):
    import hashlib
    return stem in private or 'sha256:' + hashlib.sha256(stem.encode('utf-8')).hexdigest() in private

def public_projection_html(text, source, members=None):
    import posixpath
    from urllib.parse import urlsplit, unquote
    from html import unescape
    source = Path(source)
    root = source.parent.parent if source.parent.name == 'docs' else ROOT
    if members is None:
        members = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
    relative = source.relative_to(root).as_posix()
    private = {'sha256:c7486707ae1dccd42d026007804582a7dc2d73018d43e8d65fff480c0c695e24', 'CREDENTIAL_OPERATIONS', 'ENTERPRISE_ROOT_CA_SETUP', 'INSTALL', 'INSTALLATION_WALKTHROUGH', 'OPERATIONS_AND_TROUBLESHOOTING_MANUAL', 'DSH_SETUP_AND_STRESS_TEST_GUIDE', 'INFRA_ADMIN_P2P_NOTE_20261030'}
    def target(href):
        u = urlsplit(unescape(href))
        if u.scheme or u.netloc or not u.path:
            return None
        if u.path.startswith('/'):
            return False
        name = posixpath.normpath(posixpath.join(posixpath.dirname(relative), unquote(u.path)))
        if _private_source_stem(Path(name).stem, private) or 'internal-runbooks' in name or name not in members:
            return False
        return name
    anchor_cache = {}
    def anchor(m):
        opening, href, label = m.group(1), m.group(3), m.group(4)
        u = urlsplit(unescape(href))
        if u.path.startswith('/') and not u.netloc and not u.scheme:
            return opening.replace(href, 'https://dsh.example.invalid' + href) + label + '</a>'
        resolved = target(href)
        if resolved is False:
            return '<span class="public-reference-unavailable" title="Not included in this public source projection">' + label + '</span>'
        if resolved and u.fragment and resolved.endswith(('.html', '.svg')) and (root / resolved).is_file():
            if resolved not in anchor_cache:
                target_text = (root / resolved).read_text(encoding='utf-8', errors='replace')
                target_text = re.sub(r'<script\b[\s\S]*?</script>|<style\b[\s\S]*?</style>', '', target_text, flags=re.I)
                anchor_cache[resolved] = set(re.findall(r'\b(?:id|name)=[\"\']([^\"\']+)', target_text))
            anchors = anchor_cache[resolved]
            if unquote(u.fragment) not in anchors:
                return opening.replace(href, href.split('#', 1)[0]) + label + '</a>'
        return m.group(0)
    # Never rewrite bundled JavaScript/CSS as if it were document navigation.
    pieces = re.split(r'(<script\b[^>]*>[\s\S]*?</script>|<style\b[^>]*>[\s\S]*?</style>)', text, flags=re.I)
    for i in range(0, len(pieces), 2):
        pieces[i] = re.sub(r'(<a\b[^>]*href=([\"\'])(.*?)\2[^>]*>)([\s\S]*?)</a>', anchor, pieces[i], flags=re.I)
    result = ''.join(pieces)
    # Reserved example hosts express configurable deployment locations, never live acceptance.
    result = re.sub(r'https?://[^/\s\"<>]*' + r'\x62ot\.or\.th', 'https://deployment.example.invalid', result, flags=re.I)
    return result


def public_projection_markdown(text, source, members=None):
    import posixpath
    from urllib.parse import urlsplit, unquote
    source = Path(source)
    root = source.parent.parent if source.parent.name == 'docs' else ROOT
    if members is None:
        members = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and '.git' not in p.parts}
    relative = source.relative_to(root).as_posix()
    def link(m):
        label, href = m.group(1), m.group(2)
        u = urlsplit(href)
        if u.scheme or u.netloc or not u.path:
            return m.group(0)
        name = posixpath.normpath(posixpath.join(posixpath.dirname(relative), unquote(u.path)))
        if name not in members:
            return label + ' (not included in this public source projection)'
        if u.fragment and name.endswith(('.html', '.svg')) and (root / name).is_file():
            target_text = (root / name).read_text(encoding='utf-8', errors='replace')
            anchors = set(re.findall(r'\b(?:id|name)=[\"\']([^\"\']+)', target_text))
            if unquote(u.fragment) not in anchors:
                return '[' + label + '](' + href.split('#', 1)[0] + ')'
        return m.group(0)
    result = re.sub(r'(?<!!)\[([^]\n]+)\]\(([^)\s]+)\)', link, text)
    return re.sub(r'https?://[^/\s\"<>]*' + r'\x62ot\.or\.th', 'https://deployment.example.invalid', result, flags=re.I)
