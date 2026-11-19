"""Render current qualification and reference/format entrypoints from public metadata only."""
import argparse,html,json
from pathlib import Path
import sys,re
sys.path.insert(0,str(Path(__file__).resolve().parent))
from documentation_requirements import public_projection_html,public_projection_markdown

def plain_public_html(text,source):
 text=public_projection_html(text,source)
 return re.sub(r'<span class="public-reference-unavailable" title="Not included in this public source projection">([\s\S]*?)</span>',r'\1',text)

ROOT=Path(__file__).resolve().parents[1]
esc=lambda x:html.escape(str(x),quote=True)

def validate(state,formats,features,evidence):
 if len(state['reference_sources'])!=2 or len(state['three_risk_controls'])!=3:raise ValueError('Two references and three risk controls required')
 if len(features['features'])!=80 or len(evidence['rows'])!=80 or len(evidence['owasp_categories'])!=10:raise ValueError('Preserve80rows and10OWASPdomains')
 if len({r['path'] for r in formats['records']})!=len(formats['records']):raise ValueError('Duplicate format record')
 count=sum(r['live_acceptance_state']=='live-verified' for r in evidence['rows'])
 if state['feature_ledger_established_live_acceptances']!=count:raise ValueError('Acceptance summary differs from actual feature ledger')
 if {x.get('reference_kind') for x in state['reference_sources']}!={'public-design-reference','private-workbook'}:raise ValueError('Exact public/private reference kinds required')
 if state.get('reference_basis_version')=='current-attached-references/v1' and (any(x.get('sha256') is not None or x.get('public_payload') for x in state['reference_sources']) or len(state.get('historical_reference_sources',[]))!=2):raise ValueError('Current protected identities must stay private; historical mapping identity must remain separate')
 if any(x.get('reference_kind')=='private-workbook' and (x['public_payload'] or x['filename']!='Internal tool-and-risk assessment workbook') for x in state['reference_sources']):raise ValueError('Private workbook requires safe public label and no payload')
 slides=[r for r in formats['records'] if r['kind']=='PowerPoint (.pptx)'];pdfs=[r for r in formats['records'] if r['kind']=='PDF']
 if len(slides)!=state['powerpoint_decks'] or sum(r['units'] for r in slides)!=state['powerpoint_slides'] or len(pdfs)!=state['pdf_documents'] or sum(r['units'] for r in pdfs)!=state['pdf_pages']:raise ValueError('Format totals differ from actual inventory')
 return True

def reference_identity(reference):
 if reference.get('identity_visibility')=='authenticated-library':return 'Exact source identity retained in the authenticated library'
 return 'SHA256 '+str(reference['sha256'])

def historical_reference_html(state):
 refs=state.get('historical_reference_sources',[])
 if not refs:return ''
 out=['<h3 id="historical-reference-basis">Historical80-row mapping references</h3><p>The following editions are retained for historical traceability. They are not the current attached reference basis.</p><ul>']
 for r in refs:
  title=esc(r['filename']);title='<a href="ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html">'+title+'</a>' if r.get('public_payload') else title
  out.append('<li>'+title+'<br><code>'+esc(reference_identity(r))+'</code></li>')
 return ''.join(out)+'</ul>'

def legacy_guidance(record):
 urls=record.get('current_guidance_urls',[])
 allowed={'THREE_RISK_CONTROLS.html','DSH_CURRENT_GUIDE.html#reference-controls','ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html'}
 if any(url not in allowed for url in urls):raise ValueError('Unreviewed legacy guidance target')
 return '<p>Current guidance: '+ ' · '.join('<a href="'+esc(url)+'">'+esc(url)+'</a>' for url in urls)+'</p>' if urls else ''


def index_panels(state,formats,include_status=True,include_formats=True):
 out=['<section id="current-qualification" class="card"><h2>Current qualification work</h2><p>'+esc(state['statement'])+'</p><a href="LIBRARY_CURRENT_STATE.html">Current state, exact references and all formats</a> · <a href="HARNESS_TERMINOLOGY.html">Agent and harness terminology</a><p>Source, local tests, deployment, served content and operational acceptance remain distinct.</p></section>']
 refs=' · '.join(esc(r['filename'])+' — '+esc(reference_identity(r)) for r in state['reference_sources'])
 out[0]=out[0].replace('</section>','<p>Reference basis: '+refs+'. The current attachments organize this library. The historical80-row OWASP mapping retains its original edition separately.</p></section>')
 if not include_status:out=[]
 if not include_formats:return ''.join(out)
 out.append('<section id="all-formats"><h2>PowerPoint and PDF inventory</h2><p>PowerPoint and PPTX refer to the same editable slide format here. All source editions below are registered. Revision and visual-verification status is recorded per edition. Download links are limited to existing bodies actually read back and matched to source.</p><div class="tbl"><table><thead><tr><th>Document and owner</th><th>Format / slides or pages</th><th>Edition state</th><th>Existing delivery</th></tr></thead><tbody>')
 for r in formats['records']:
  label=esc(r['path']);target=r['path'] if r['owner_library']=='DSH / MultiHarness' else r['delivery_url'];name='<a href="'+esc(target)+'">'+label+'</a>' if r['delivery_url'] else '<code>'+label+'</code>'
  out.append('<tr><td>'+name+'<br><small>'+esc(r['owner_library'])+'</small></td><td>'+esc(r['kind'])+'<br>'+str(r['units'])+'</td><td>'+esc(r['edition_alignment'])+legacy_guidance(r)+'</td><td>'+esc(r['delivery_state'])+'</td></tr>')
 out.append('</tbody></table></div><p>The source snapshot has '+str(state['source_formats']['.html'])+' HTML and '+str(state['source_formats']['.md'])+' Markdown files, including historical and restricted material. It has no Word DOC/DOCX files. Restricted source content is not made public by this inventory.</p></section>')
 return ''.join(out)

def _render_source(state,formats,features,evidence):
 validate(state,formats,features,evidence)
 body=['<h1>MultiHarness current state and documentation map</h1><p>'+esc(state['statement'])+'</p><p>Reviewed '+esc(state['reviewed_utc'])+' against named source '+esc(state['source_basis'])+'. This is a source/qualification summary, not a new runtime acceptance receipt.</p>']
 body.append('<h2 id="two-references">The two governing references</h2><ul>')
 for r in state['reference_sources']:
  title=esc(r['filename'])+' (protected original; payload excluded from public projections)'
  rendered='<br>Rendered source edition: <code>'+esc(r['public_rendered_source_sha256'])+'</code>' if r.get('public_rendered_source_sha256') else ''
  body.append('<li>'+title+'<br>'+esc(reference_identity(r))+rendered+'</li>')
 body.append('</ul>'+historical_reference_html(state)+'<p>The current attached agent-safety design and tool/risk workbook define the organizing reference basis. The earlier80-row mapping keeps its historical editions. Workbook J/K/L are control layers and M is cross-layer audit; leakage, damage and containment remain risk objectives. Topic-level mappings and remaining row-specific validation gaps stay visible in <a href="FEATURE_CONTROL_TRACEABILITY.html">feature traceability</a>.</p><h2 id="three-risk-controls">Three risk controls</h2><ol>')
 for control in state['three_risk_controls']:body.append('<li>'+esc(control)+'</li>')
 body.append('</ol><p><a href="THREE_RISK_CONTROLS.html">Control objectives and boundaries</a> · <a href="ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html">Component and deployment map</a></p><h2 id="qualification">Operational work and remaining evidence</h2>')
 for title,key in [('OpenShell','openshell_scope'),('A2A','a2a_scope'),('Banking comparison','banking_scope')]:body.append('<h3>'+title+'</h3><p>'+esc(state[key])+'</p>')
 body.append('<p>The feature ledger currently records '+str(state['feature_ledger_established_live_acceptances'])+' established feature-wide live acceptances. Narrow source/unit successes remain attributed to their exact tested aspects. This count does not erase retained narrow live observations.</p><h2 id="owasp-matrix">80 rows across ten OWASP agentic risks</h2><p>76 rows have a primary domain. Four cross-cutting evidence rows apply across all ten domains; they do not form an eleventh OWASP risk. The canonical matrix preserves every original feature ID and the 14 roadmap entries.</p>')
 shared=[r for r in features['features'] if r['asi_primary']=='ALL']
 def links(rows):return ' · '.join('<a href="FEATURE_CONTROL_TRACEABILITY.html#feature-'+str(r['n'])+'">'+str(r['n'])+'. '+esc(r['feature'])+'</a>' for r in rows)
 for key in sorted(evidence['owasp_categories']):
  body.append('<section><h3>'+esc(key+' '+evidence['owasp_categories'][key][0])+'</h3><p>'+links([r for r in features['features'] if r['asi_primary']==key])+'</p><p>Shared evidence: '+links(shared)+'</p></section>')
 body.append('<h2 id="project-structure">Project-owned libraries</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in state['project_libraries'])+'</ul><p>'+esc(state['project_rule'])+'</p>')
 body.append(index_panels(state,formats))
 body.append('<h2>Publication and current-edition rules</h2><p>'+esc(state['current_edition_publication'])+'</p><p>Every current HTML/Markdown guide and slide/PDF edition must state its relevant reference/control mappings, source revision, qualification scope and evidence links. Original and historical editions remain preserved and dated. Current-state work on a deck does not become complete until the revised editable file and its rendered companion have been inspected and their served bytes verified.</p><p><a href="LIBRARY_CURRENT_STATE.public.json">Status metadata</a> · <a href="LIBRARY_FORMATS.public.json">Format catalog metadata</a></p>')
 page='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MultiHarness current state and documentation map</title><style>body{font:16px/1.6 system-ui;color:#173047;margin:0}main{max-width:1300px;margin:auto;padding:24px}a{color:#075985}code,a{overflow-wrap:anywhere}.card{background:#eff6fb;padding:18px;border-left:4px solid #147391}.tbl{overflow:auto}table{border-collapse:collapse;min-width:850px;width:100%}th,td{border:1px solid #bbc8d5;padding:10px;text-align:left;vertical-align:top}h1,h2,h3{line-height:1.3}section{margin:20px 0}</style></head><body><main><nav><a href="index.html">Library index</a> · <a href="FEATURE_MATRIX_BY_OWASP.html">OWASP matrix</a></nav>'+''.join(body)+'</main></body></html>\n'
 md='# MultiHarness current documentation state\n\n'+state['statement']+'\n\nSee [the full current-state map](LIBRARY_CURRENT_STATE.html), [traceability for all 80 rows](FEATURE_CONTROL_TRACEABILITY.html), [three risk controls](THREE_RISK_CONTROLS.html), and [agent/harness terminology](HARNESS_TERMINOLOGY.html).\n\nReferences:\n\n'+''.join('- '+r['filename']+'; '+reference_identity(r)+(' (protected source; payload excluded)' if not r['public_payload'] else '')+'\n' for r in state['reference_sources'])+'\nThe 80 rows have 76 primary OWASP assignments and four shared evidence rows across ten domains. Current feature-wide live acceptance is not established. Two PowerPoint decks retain locally revised content and render records. APP_LOGIN_MAIN_TEST_EN.pptx is retained legacy/not current because its dated reference and risk terminology are superseded; use [the J/K/L control guide](THREE_RISK_CONTROLS.html) and [the two foundation SVGs](ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html) for current guidance. Five decks and three PDFs still need current-state revision and visual verification. Original editions are preserved.\n'
 md+='\n## OpenShell qualification evidence\n\n'+state['openshell_scope']+'\n\n[Retained OpenShell qualification evidence](OPENSHELL_STATUS_AND_USAGE.html#current-openshell-evidence).\n'
 return page,md

def render(state,formats,features,evidence):
 page,md=_render_source(state,formats,features,evidence)
 return plain_public_html(page,ROOT/'docs/LIBRARY_CURRENT_STATE.html'),public_projection_markdown(md,ROOT/'docs/LIBRARY_CURRENT_STATE.md').replace(' (not included in this public source projection)','')

def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args();d=ROOT/'docs'
 state=json.loads((d/'LIBRARY_CURRENT_STATE.public.json').read_text(encoding='utf-8'));formats=json.loads((d/'LIBRARY_FORMATS.public.json').read_text(encoding='utf-8'));features=json.loads((d/'security-data/features.json').read_text(encoding='utf-8'));evidence=json.loads((d/'security-data/feature-reference-evidence.public.json').read_text(encoding='utf-8'))
 for name,text in zip(['LIBRARY_CURRENT_STATE.html','LIBRARY_CURRENT_STATE.md'],render(state,formats,features,evidence)):
  b=text.encode()
  if args.check:
   if (d/name).read_bytes()!=b:raise SystemExit('Current library page is stale: '+name)
  else:(d/name).write_bytes(b)
if __name__=='__main__':main()
