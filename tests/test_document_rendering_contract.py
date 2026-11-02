import base64
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentRenderingContractTests(unittest.TestCase):
    def test_agent_runtime_page_has_mobile_overflow_guards(self):
        html = (ROOT / "docs" / "AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("grid-template-columns:minmax(0,1fr)", html)
        self.assertIn("pre{white-space:pre-wrap", html)
        self.assertIn("overflow-wrap:anywhere", html)

    def test_agent_runtime_page_keeps_three_risks_as_primary_decision_columns(self):
        html = (ROOT / "docs" / "AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("Enterprise three-risk comparison", html)
        self.assertIn("Prevent external leakage", html)
        self.assertIn("Prevent damage or excessive access", html)
        self.assertIn("Keep results contained", html)
        self.assertIn("Counterpart deployed alone without DSH AD/LDAP", html)
        self.assertIn("OWASP supporting crosswalk", html)
        self.assertIn("supporting threat taxonomy, not as a replacement", html)

    def test_platform_guide_covers_every_governed_runtime_and_backend(self):
        html = (ROOT / "docs" / "DSH_PLATFORM_GUIDE.html").read_text(encoding="utf-8")
        for value in (
            "DSH Python SDK", "Claude Code", "Deep Agents", "Kilo", "TrueForge",
            "Private workspace", "OpenShell", "litellm-gateway", "context-forwarder",
            "deepinfer-dspark", "sglang-dspark", "Prevent external leakage",
            "Prevent excessive access", "Keep results contained",
        ):
            self.assertIn(value, html)
        self.assertEqual(html.count('class="mermaid-wrapper"'), 3)
        self.assertIn("Save SVG", html)
        self.assertIn("Save PNG", html)
        self.assertIn("Copy code", html)

    def test_documentation_library_lists_every_current_html_page(self):
        index = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
        for page in (ROOT / "docs").glob("*.html"):
            if page.name != "index.html":
                self.assertIn(f'href="{page.name}"', index, page.name)

    def test_jupyter_walkthrough_contains_real_caption_content(self):
        html = (ROOT / "docs" / "JUPYTER_DSH2_DSH3_WALKTHROUGH.html").read_text(
            encoding="utf-8"
        )
        match = re.search(
            r'<track[^>]+kind="captions"[^>]+src="data:text/vtt;base64,([A-Za-z0-9+/=]+)"',
            html,
        )
        self.assertIsNotNone(match)
        captions = base64.b64decode(match.group(1), validate=True).decode("utf-8")
        self.assertTrue(captions.startswith("WEBVTT"))
        self.assertGreater(len(captions), 500)
        self.assertIn("JupyterLab", captions)


if __name__ == "__main__":
    unittest.main()
