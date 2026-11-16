import base64,hashlib
import importlib.util,re,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DOCS=ROOT/'docs';sys.path.insert(0,str(ROOT/'scripts'))
import build_library_index as lib
from documentation_requirements import public_projection_html,public_projection_markdown
class PublicLibraryProjection(unittest.TestCase):
 def test_public_index_generator_does_not_need_private_release_archive(self):
  self.assertEqual(lib.live_members(),{p.relative_to(DOCS).as_posix() for p in DOCS.rglob('*') if p.is_file()})
 def test_full_public_index_build_has_no_private_predecessor_or_release_dependency(self):
  text,docs=lib.build();self.assertGreater(len(docs),0);self.assertIn('MultiHarness',text);self.assertNotIn('href="INSTALL.md"',text)
 def test_absent_and_private_links_become_explicit_nonlinks(self):
  text='<a href="not-exported.html">Retained source reference</a><a href="INSTALL.md">Operator instructions</a><a href="THREE_RISK_CONTROLS.html">Controls</a>'
  out=public_projection_html(text,DOCS/'index.html')
  self.assertNotIn('href="not-exported.html"',out);self.assertNotIn('href="INSTALL.md"',out);self.assertIn('href="THREE_RISK_CONTROLS.html"',out);self.assertIn('Not included in this public source projection',out)
 def test_existing_public_page_missing_anchor_falls_back_to_page(self):
  text=public_projection_markdown('[Reference](DSH_PLATFORM_GUIDE.html#not-a-real-public-anchor)',DOCS/'DSH_USER_MANUAL.md')
  self.assertEqual(text,'[Reference](DSH_PLATFORM_GUIDE.html)')
 def test_internal_policy_and_cloud_readiness_remain_distinct(self):
  guide=(DOCS/'DSH_CURRENT_GUIDE.html').read_text(encoding='utf-8')
  for required in ['393216-token context','DeepSeek through the managed LiteLLM route only','multiharness.cloud and superharness.cloud','FREE_ROUTE_SETUP_REQUIRED','not a functioning free-model service','no automatic fallback']:
   self.assertIn(required,guide)
 def test_private_release_and_qa_paths_are_not_links(self):
  text=(DOCS/'index.html').read_text(encoding='utf-8');self.assertNotRegex(text,r'href=[\"\'][^\"\']*(?:internal-runbooks|TOOLS_AND_RISKS_REGISTER|live_gateway_auth_proxy)')


def visible(text):
    text=re.sub(r'<script\b.*?</script>|<style\b.*?</style>','',text,flags=re.S|re.I)
    return re.sub(r'<[^>]+>',' ',text)
INDEX=(DOCS/'index.html').read_text(encoding='utf-8')
class RetainedPublicLibraryAssertions(unittest.TestCase):
    EXACT=("A2A handoff (Claude Code to Deep Agents via the broker and per-task guard) was re-verified live on 10 Nov 2026; "
           "the governed qualification track, the DSH Python SDK, approval cases and chat delegation remain being qualified.")
    def test_cloud_profiles_are_separate_targets_not_internal_feature_runtimes(self):
        # Current user scope requires documenting the separate cloud roadmap.
        internal = (DOCS / 'security-data/features.json').read_text(encoding='utf-8').lower()
        self.assertNotIn('superharness', internal)
        self.assertNotIn('multiharness.cloud', internal)
        guide = (DOCS / 'DSH_CURRENT_GUIDE.html').read_text(encoding='utf-8')
        self.assertIn('id="platform-policy"', guide)
        self.assertIn('393216-token context', guide)
        self.assertIn('DeepSeek through the managed LiteLLM route only', guide)
        self.assertIn('multiharness.cloud and superharness.cloud', guide)
        self.assertIn('FREE_ROUTE_SETUP_REQUIRED', guide)
        self.assertIn('not a functioning free-model service', guide)
        self.assertIn('Cloud deployment is not yet qualified.', guide)
        self.assertIn('no automatic fallback', guide)
        self.assertIn('Roadmap, not live autonomous acceptance', guide)

    def test_exact_wording_in_the_index_and_the_a2a_page(self):
        self.assertEqual(lib.A2A_STATUS, self.EXACT)
        for name in ('index.html',):
            self.assertIn(self.EXACT, (DOCS / name).read_text(encoding='utf-8'), name)

    def test_user_manual_describes_the_quick_actions_menu(self):
        for name in ('DSH_USER_MANUAL.html', 'DSH_USER_MANUAL.md'):
            text = visible((DOCS / name).read_text(encoding='utf-8')) if name.endswith('.html') else (DOCS / name).read_text(encoding='utf-8')
            self.assertIn('launcher button at the bottom right', text, name)
            self.assertIn('round gear icon, named Quick actions', text, name)
            for extra in ('Web Terminal', 'JupyterLab'):
                self.assertIn(extra, text, name + ': ' + extra)
            self.assertIn('Reconnecting', text, name)
            self.assertIn('sign out and sign in again', text, name)
            for item in ('Agent tasks', 'Admin overview', 'My apps', 'Credentials', 'Logout'):
                self.assertIn(item, text, name + ': ' + item)

    def test_index_status_is_qualification_not_universal_runtime_acceptance(self):
        text=visible(INDEX)
        self.assertIn('Qualification evidence is separate',text)
        self.assertIn('DSH Python SDK',text)
        self.assertNotRegex(text.lower(),r'all (?:three|3) agents are (?:live|fully operational)')



class AdditionalRetainedPublicIndexAssertions(unittest.TestCase):
    def test_all_local_links_resolve(self):
        for target in set(re.findall(r'href="([^"#]+)"', INDEX)):
            if re.match(r'(https?:|mailto:)', target):
                continue
            self.assertTrue((DOCS / target).is_file(), target)

    def test_held_pages_are_listed_but_not_linked(self):
        for d in lib.collect():
            if d['held']:
                for ext in ('.html', '.md'):
                    self.assertNotIn('href="%s%s"' % (d['stem'], ext), INDEX.split('<h2>Curated learning paths')[0], d['stem'])
        self.assertIn('repository only', INDEX)

    def test_the_security_pages_lead_the_index(self):
        self.assertLess(INDEX.index('SECURITY_BY_OWASP.html'), INDEX.index('DSH_USER_MANUAL.html'))
        self.assertIn('three risk controls', INDEX.lower())

    def test_nothing_calls_a2a_operational(self):
        for name in ('index.html', 'SECURITY_BY_OWASP.html', 'FEATURE_MATRIX_BY_OWASP.html', 'AGENT_SAFETY_LAYERS.html'):
            text = visible((DOCS / name).read_text(encoding='utf-8'))
            self.assertNotRegex(text, r'(?i)a2a[^.]{0,60}(is|are|now|fully|already)\s+(fully\s+)?operational', name)
            self.assertNotRegex(text, r'(?i)operational[^.]{0,40}a2a', name) if name != 'A2A_TASK_DELEGATION.html' else None

    def test_current_public_root_selection_is_retained_in_navigation(self):
        import json
        names=json.loads((ROOT/'.github/public-manual-entrypoints.json').read_text(encoding='utf-8'))
        for name in names:
            if name!='index.html':self.assertIn('href="'+name+'"',INDEX)
    def test_private_register_is_not_linked_or_promoted(self):
        self.assertNotIn('TOOLS_AND_RISKS_REGISTER',INDEX)
        self.assertNotIn('private register',(DOCS/'SECURITY_BY_OWASP.html').read_text(encoding='utf-8'))
        self.assertNotIn('TOOLS_AND_RISKS_REGISTER',{d['stem'] for d in lib.collect()})



PUBLIC_CURRENT_PAGES=['AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html', 'ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html', 'ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.md', 'DSH_CURRENT_GUIDE.html', 'DSH_CURRENT_GUIDE.md', 'DSH_NETWORK_ZONES.html', 'DSH_USER_MANUAL.html', 'DSH_USER_MANUAL.md', 'FEATURE_CONTROL_TRACEABILITY.html', 'FEATURE_MATRIX_BY_OWASP.html', 'FEATURE_OWASP_REVIEW.html', 'LIBRARY_CURRENT_STATE.html', 'LIBRARY_CURRENT_STATE.md', 'SECURITY_BY_OWASP.html', 'THREE_RISK_CONTROLS.html', 'THREE_RISK_CONTROLS.md', 'UPSTREAM_SYNC_AND_INTERNET_POLICY.html', 'index.html']
class PublicProjectionInventoryAssertions(unittest.TestCase):
    def test_every_current_projection_page_is_in_the_curated_index(self):
        for name in PUBLIC_CURRENT_PAGES:
            if name!='index.html':self.assertIn(name,INDEX,name)
        docs=lib.collect()
        self.assertGreater(len(docs),0)
        for entry in docs:
            self.assertTrue(any((DOCS/(entry['stem']+ext)).is_file() for ext in entry['forms']))
    def test_current_page_product_text_uses_multiharness(self):
        for name in PUBLIC_CURRENT_PAGES:
            text=(DOCS/name).read_text(encoding='utf-8')
            self.assertNotRegex(visible(text) if name.endswith('.html') else text,r'[Gg]overned [Hh]arness',name)

class PublicControlCsp(unittest.TestCase):
 def test_control_diagram_embeds_exact_approved_public_bytes(self):
  index=(DOCS/'index.html').read_text(encoding='utf-8')
  match=re.search(r'<img[^>]+src="(data:image/svg\+xml;base64,[^"]+)"',index)
  self.assertIsNotNone(match)
  raw=base64.b64decode(match.group(1).split(',',1)[1],validate=True)
  self.assertEqual(raw,(DOCS/'diagrams/multiharness-three-risk-control-path.svg').read_bytes())
  self.assertEqual(hashlib.sha256(raw).hexdigest(),'2243794e1c18f25f92e390a07dcedab799eabd5de325d50d8f6ef8464d9fc736')
  self.assertEqual(lib.control_svg_data_uri(),match.group(1))
  self.assertIn('href="diagrams/multiharness-three-risk-control-path.svg"',index)
  self.assertIn('alt="An authorized user task enters guardrails',index)
  self.assertNotIn('src="diagrams/multiharness-three-risk-control-path.svg"',index)

if __name__=='__main__':unittest.main()
