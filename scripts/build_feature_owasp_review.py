"""Render the public eighty-feature documentary review; never open private inputs."""
import argparse,collections,hashlib,html,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
E=lambda value:html.escape(str(value),quote=True)

def validate(features,review):
 rows=review['rows'];fs={f['n']:f for f in features['features']};domains={'ASI%02d'%i for i in range(1,11)}
 if sorted(fs)!=list(range(1,81)) or sorted(r['feature_id'] for r in rows)!=list(range(1,81)):raise ValueError('Exactly eighty stable feature identities required')
 if set(review['categories'])!=domains:raise ValueError('Exactly ten category definitions required')
 if len(review['references'])!=2 or set(review['risk_controls'])!={'1','2','3'}:raise ValueError('Two references and three controls required')
 private=[r for r in review['references'] if r['kind']=='private-workbook']
 if len(private)!=1 or private[0]['public_page'] is not None or private[0]['payload_included'] is not False or private[0]['label']!='Internal tool-and-risk assessment workbook':raise ValueError('Private reference must remain metadata only')
 if any(r['payload_included'] is not False for r in review['references']):raise ValueError('Reference payloads are not review metadata')
 if len({r['mapping_rationale'] for r in rows})!=80:raise ValueError('Each row needs a distinct rationale')
 for row in rows:
  f=fs[row['feature_id']]
  if row['primary_category']!=f['asi_primary'] or row['existing_related_categories']!=f['asi_all'] or row['original_tag_status']!=f['tag_status']:raise ValueError('Documentary review cannot silently retag original source')
  if row['feature_name']!=f['feature'] or row['operational_evidence_unchanged'] is not True:raise ValueError('Review cannot promote implementation or acceptance')
  expected=domains if f['kind']=='evidence' else set(f['asi_all'])
  if set(row['applicable_categories'])!=expected:raise ValueError('Category coverage must match original mapping; shared evidence spans ten domains')
  risks={'1','2','3'} if f['kind']=='evidence' else {f['risk']}
  if set(row['three_risk_controls'])!=risks:raise ValueError('Risk controls must retain source mapping')
  if len(row['mapping_rationale'].strip())<40 or row['review_state']!='content-reviewed; proposed mapping, owner acceptance pending':raise ValueError('Explicit proposed rationale required')
  if row.get('private_tool_row_identity') is not None or row.get('private_payload') is not None:raise ValueError('Private payload is not public review metadata')
 return True

def render(features,review):
 validate(features,review);rows=review['rows'];parts=['<nav><a href="index.html">Library</a> / <a href="FEATURE_MATRIX_BY_OWASP.html">Complete matrix</a> / <a href="FEATURE_CONTROL_TRACEABILITY.html">Tests and acceptance gaps</a> / <a href="LIBRARY_CURRENT_STATE.html">Current qualification</a></nav><h1>80-feature OWASP and control review</h1>']
 parts+=['<p>Reviewed '+E(review['reviewed_date'])+' against source '+E(review['source_basis'])+'. '+E(review['review_scope'])+'</p><p>'+E(review['remaining_reference_limit'])+'</p>']
 parts+=['<h2>Two governing references</h2><ul>']
 for ref in review['references']:
  name='<a href="'+E(ref['public_page'])+'">'+E(ref['label'])+'</a>' if ref['public_page'] else E(ref['label'])+' (private; metadata only)'
  parts+=['<li>'+name+'; original SHA256 <code>'+E(ref['sha256'])+'</code></li>']
 parts+=['</ul><h2>Three risk controls</h2><ol>'+''.join('<li>'+E(review['risk_controls'][str(i)])+'</li>' for i in range(1,4))+'</ol><p>Primary groups below count76 controls/roadmap dimensions once. Four shared evidence obligations span all ten domains and appear once at the end. Secondary mappings overlap; they are not additional features.</p><p>Classification basis: <a href="'+E(review['taxonomy_url'])+'">OWASP Agentic Top10 for2026</a>. Row interpretations are project proposals, not OWASP-endorsed assessments.</p>']
 def table(group):
  out=['<div class="table"><table><thead><tr><th>Stable feature</th><th>OWASP interpretation and limits</th><th>Three controls</th><th>Both-reference crosswalk</th><th>Evidence</th></tr></thead><tbody>']
  for row in group:
   out+=['<tr id="feature-'+str(row['feature_id'])+'"><th>'+str(row['feature_id'])+'. '+E(row['feature_name'])+'</th><td><strong>'+E(row['primary_category'])+'</strong><br>'+E(row['mapping_rationale'])+'<p>'+E(row['mapping_limit'])+'</p><small>'+E(row['review_state'])+'; original tag: '+E(row['original_tag_status'])+'</small></td><td>'+ '<br>'.join(E(review['risk_controls'][risk]) for risk in row['three_risk_controls'])+'</td><td>DQ layer: '+E(row['dq_design_layer'])+'<br>'+E(row['dq_reference_scope'])+'<p>Control family: '+E(row['control_family'])+'<br>'+E(row['internal_reference_scope'])+'</p></td><td><a href="'+E(row['evidence_link'])+'">Source, executed tests and acceptance gaps</a><p>Operational evidence unchanged; this review runs no model or runtime test.</p></td></tr>']
  return ''.join(out)+'</tbody></table></div>'
 for i in range(1,11):
  category='ASI%02d'%i;group=[row for row in rows if row['primary_category']==category];parts+=['<h2 id="'+category.lower()+'">'+category+' / '+E(review['categories'][category])+' / '+str(len(group))+' primary rows</h2>'+table(group)]
 parts+=['<h2>Shared evidence obligations across all ten domains</h2>'+table([r for r in rows if r['primary_category']=='ALL'])]
 return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>80-feature OWASP and control review</title><style>body{font:16px/1.5 system-ui;color:#173047;margin:24px}main{max-width:1600px;margin:auto}.table{overflow:auto}table{border-collapse:collapse;width:100%;min-width:1250px;table-layout:fixed}th:nth-child(1){width:13%}th:nth-child(2){width:30%}th:nth-child(3){width:14%}th:nth-child(4){width:27%}th:nth-child(5){width:16%}td,th{border:1px solid #bbc8d5;padding:12px;vertical-align:top;text-align:left;overflow-wrap:anywhere}code{overflow-wrap:anywhere}</style></head><body><main>'+''.join(parts)+'</main></body></html>\n'

def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();raw=(ROOT/'docs/security-data/features.json').read_bytes();review=json.loads((ROOT/'docs/security-data/feature-owasp-review.public.json').read_text(encoding='utf-8'))
 if hashlib.sha256(raw).hexdigest()!=review['feature_source_sha256']:raise ValueError('Feature source hash mismatch')
 content=render(json.loads(raw),review).encode();target=ROOT/'docs/FEATURE_OWASP_REVIEW.html'
 if a.check:
  if target.read_bytes()!=content:raise ValueError('Review page is stale')
 else:target.write_bytes(content)
if __name__=='__main__':main()
