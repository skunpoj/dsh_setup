import importlib.util,json,re,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DOCS=ROOT/'docs';sys.path.insert(0,str(ROOT/'scripts'))
import build_security_pages as gen
class PublicSecurityProjection(unittest.TestCase):
 def test_all80_original_ids_and10_domains_preserved(self):
  features=json.loads((DOCS/'security-data/features.json').read_text(encoding='utf-8'))['features']
  self.assertEqual([x['n'] for x in features],list(range(1,81)))
  self.assertEqual(set(gen.ASI),{'ASI%02d'%i for i in range(1,11)})
  text=(DOCS/'FEATURE_CONTROL_TRACEABILITY.html').read_text(encoding='utf-8')
  for i in range(1,81):self.assertIn('feature-'+str(i),text)
 def test_public_generator_never_reads_or_emits_private_assessment(self):
  features,private=gen.load();self.assertEqual(private,{})
  pages=gen.generate();self.assertEqual(set(pages),{'SECURITY_BY_OWASP.html','FEATURE_MATRIX_BY_OWASP.html'})
  self.assertTrue(all('security-data/private/' not in name for name in pages))
  with self.assertRaisesRegex(ValueError,'PRIVATE_ASSESSMENT_EXCLUDED'):gen.build_register({'untrusted':'payload'})
 def test_no_new_compliance_or_runtime_acceptance_claim(self):
  for name in ['SECURITY_BY_OWASP.html','FEATURE_MATRIX_BY_OWASP.html']:
   text=(DOCS/name).read_text(encoding='utf-8').lower();self.assertNotRegex(text,r'\b(is|are) (fully )?owasp[- ]compliant')


PUBLIC = ["SECURITY_BY_OWASP.html","FEATURE_MATRIX_BY_OWASP.html","AGENT_SAFETY_LAYERS.html"]
ALL=PUBLIC
def data():return json.loads((DOCS/"security-data/features.json").read_text(encoding="utf-8"))["features"]

class RetainedPublicSecurityAssertions(unittest.TestCase):
    def test_feature_data_is_complete_and_consistent(self):
        feats = data()
        self.assertEqual([f['n'] for f in feats], list(range(1, 81)))
        evidence = [f for f in feats if f['kind'] == 'evidence']
        self.assertEqual([f['n'] for f in evidence], [63, 64, 65, 66])
        for f in feats:
            if f['kind'] == 'feature':
                self.assertIn(f['asi_primary'], f['asi_all'], f['feature'])
                self.assertIn(f['risk'], {'1', '2', '3'}, f['feature'])
                self.assertIn(f['layer'], {'Guardrails', 'Verification', 'Sandbox'}, f['feature'])
                self.assertIn(f['cia'], {'C', 'I', 'A'}, f['feature'])
                self.assertTrue(set(f['asi_all']) <= set(gen.ASI), f['feature'])
        self.assertEqual(set(f['asi_primary'] for f in feats if f['kind'] == 'feature') | {'ASI01'}, set(gen.ASI) | {'ASI01'})
        self.assertEqual(set(gen.ASI), {'ASI%02d' % i for i in range(1, 11)})

    def test_every_feature_appears_on_the_overview_and_the_matrix(self):
        overview = (DOCS / 'SECURITY_BY_OWASP.html').read_text(encoding='utf-8')
        matrix = (DOCS / 'FEATURE_MATRIX_BY_OWASP.html').read_text(encoding='utf-8')
        for f in data():
            self.assertIn(gen.esc(f['feature']), matrix, f['feature'])
            if f['kind'] == 'feature':
                self.assertIn(gen.esc(f['feature']), overview, f['feature'])
        for key in gen.ASI:
            self.assertIn('id="%s"' % key.lower(), overview)
            self.assertIn('id="%s"' % key.lower(), matrix)

    def test_the_grid_counts_add_up(self):
        feats = data()
        primary, tagged, grid, risks = gen.counts(feats)
        self.assertEqual(sum(primary.values()), 76)
        self.assertEqual(sum(grid.values()), 76)
        self.assertEqual(sum(risks.values()), 76)

    def test_no_replacement_character_in_the_text_of_any_page(self):
        # Nine pages embed a markdown renderer whose <script> uses U+FFFD as a legitimate literal; the visible text must not.
        for path in sorted(DOCS.glob('*.html')) + sorted(DOCS.glob('*.md')):
            text = path.read_text(encoding='utf-8')
            visible = re.sub(r'<script\b.*?</script>', '', text, flags=re.S | re.I)
            self.assertNotIn('�', visible, path.name)

    def test_no_external_fonts_or_scripts(self):
        for name in ALL:
            text = (DOCS / name).read_text(encoding='utf-8')
            self.assertNotIn('fonts.googleapis', text)
            self.assertNotIn('<script', text)

    def test_local_links_resolve(self):
        for name in ALL:
            text = (DOCS / name).read_text(encoding='utf-8')
            for target in re.findall(r'(?:href|src)="([^"#]+)', text):
                if re.match(r'(https?:|mailto:)', target):
                    continue
                self.assertTrue((DOCS / target).is_file(), name + ' -> ' + target)

    def test_no_compliance_claim(self):
        for name in PUBLIC:
            text = (DOCS / name).read_text(encoding='utf-8').lower()
            self.assertNotRegex(text, r'\b(is|are) (fully )?owasp[- ]compliant')
        self.assertIn('no claim of owasp compliance', (DOCS / 'SECURITY_BY_OWASP.html').read_text(encoding='utf-8').lower())

    def test_the_human_in_the_loop_principle_and_three_risk_controls_are_stated(self):
        overview = (DOCS / 'SECURITY_BY_OWASP.html').read_text(encoding='utf-8')
        self.assertIn('flag, pause, human in the loop', overview.lower())
        self.assertIn('Three control layers', overview)
        self.assertIn('Policy/human; harness/deterministic; infrastructure/resource', overview)
        self.assertIn('Workbook J/K/L; audit spans all layers in M', overview)
        self.assertIn('Risk objectives', overview)
        self.assertIn('Original risk-objective IDs are retained separately from enforcement layers', overview)

    def test_proposed_additions_fill_the_thin_risks(self):
        matrix = (DOCS / 'FEATURE_MATRIX_BY_OWASP.html').read_text(encoding='utf-8')
        self.assertIn('id="proposed"', matrix)
        self.assertEqual(len(gen.PROPOSED), 8)
        self.assertTrue({'ASI02', 'ASI09', 'ASI01'} & {p['asi_primary'] for p in gen.PROPOSED})

    def test_public_pages_have_no_private_register_payload(self):
        for name in PUBLIC:
            text=(DOCS/name).read_text(encoding='utf-8')
            self.assertNotRegex(text,r'\bBOT\b',name)
            self.assertNotRegex(text,r'[\u0e00-\u0e7f]',name)
            self.assertNotIn('tools_register',text,name)
            self.assertNotIn('TOOLS_AND_RISKS_REGISTER',text,name)
    def test_public_index_routes_to_existing_security_pages(self):
        text=(DOCS/'index.html').read_text(encoding='utf-8')
        for name in PUBLIC:self.assertIn('href="'+name+'"',text)
        for name in ['THREE_RISK_CONTROLS.html','THREE_RISK_CONTROLS.md']:
            self.assertIn('OWASP',(DOCS/name).read_text(encoding='utf-8'))



class PublicGeneratedSnapshotAssertions(unittest.TestCase):
    def test_committed_public_pages_equal_projected_generator_output(self):
        from documentation_requirements import public_projection_html
        for name,text in gen.generate().items():
            self.assertEqual((DOCS/name).read_bytes(),public_projection_html(text,DOCS/name).encode('utf-8'),name)

if __name__=='__main__':unittest.main()
