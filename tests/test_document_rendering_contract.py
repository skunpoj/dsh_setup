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
