from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/'docs'/'GOVERNED_HARNESS_RUNTIME_COMPARISON.html'


class _Document(HTMLParser):
    def __init__(self):
        super().__init__();self.hrefs=[];self.text=[];self.tables=0
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='a' and values.get('href'):self.hrefs.append(values['href'])
        if tag=='table':self.tables+=1
    def handle_data(self,data):self.text.append(data)


class GovernedHarnessComparisonTests(unittest.TestCase):
    def setUp(self):
        self.document=_Document();self.document.feed(HTML.read_text(encoding='utf-8'))
        self.text=' '.join(' '.join(self.document.text).split())

    def test_risk_columns_are_primary_and_owasp_is_supporting(self):
        required=(
            'Primary enterprise risk-control analysis',
            'Prevent external leakage',
            'Prevent damage or excessive access',
            'Keep results contained',
            'Same runtime deployed alone without DSH AD/LDAP',
            'OWASP Agentic Top 10 crosswalk',
        )
        for value in required:self.assertIn(value,self.text)
        self.assertLess(self.text.index(required[0]),self.text.index(required[-1]))
        self.assertGreaterEqual(self.document.tables,6)

    def test_local_links_resolve(self):
        for href in self.document.hrefs:
            if '://' in href or href.startswith('#'):continue
            target=(HTML.parent/href.split('#',1)[0]).resolve()
            self.assertTrue(target.is_file(),href)


if __name__=='__main__':unittest.main()
