"""Render public feature crosswalk/evidence; never read private workbook or register payloads."""
import argparse,html,json,hashlib,re,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
esc=lambda v:html.escape(str(v if v is not None else 'Not recorded'),quote=True)
def validate(features,data):
 ids=[f['n'] for f in features['features']];mapped=[r['feature_id'] for r in data['rows']]
 if sorted(ids)!=list(range(1,81)) or sorted(mapped)!=sorted(ids):raise ValueError('Every original feature ID must be mapped exactly once')
 group_ids=[g['id'] for g in data['evidence_groups']]
 if len(set(group_ids))!=len(group_ids):raise ValueError('Duplicate evidence identity')
 if any(x not in group_ids for r in data['rows'] for x in r['evidence_ids']):raise ValueError('Unknown evidence reference')
 if any(r.get('private_tool_row_identity') is not None for r in data['rows']):raise ValueError('Private row identity is not public feature evidence')
 for g in data['evidence_groups']:
  if g['stage']=='live-verified' and g['result']=='PASS':
   if not all(g.get(k) for k in ['test_ids','date_utc','source_commit','image_digest','environment','owner','evidence_link']):raise ValueError('Live PASS missing behavior/deployment evidence')
   if not isinstance(g['test_ids'],list) or not all(isinstance(x,str) and x.strip() for x in g['test_ids']):raise ValueError('Live test IDs must be explicit')
   if not isinstance(g['source_commit'],str) or not re.fullmatch(r'[a-f0-9]{40}',g['source_commit']):raise ValueError('Live source commit must be immutable')
   if not isinstance(g['image_digest'],str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',g['image_digest']):raise ValueError('Live application image digest required')
   if g.get('positive_behavior_verified') is not True or g.get('negative_behavior_verified') is not True:raise ValueError('Live behavior evidence must be true booleans')
   try:stamp=datetime.datetime.fromisoformat(g['date_utc'].replace('Z','+00:00'))
   except (ValueError,TypeError,AttributeError):raise ValueError('Live evidence timestamp must be UTC')
   if stamp.utcoffset()!=datetime.timedelta(0):raise ValueError('Live evidence timestamp must be UTC')
   covered=g.get('feature_ids')
   if not isinstance(covered,list) or not covered or any(type(n) is not int or n not in ids for n in covered) or len(set(covered))!=len(covered):raise ValueError('Live evidence needs exact feature coverage')
 groups={g['id']:g for g in data['evidence_groups']}
 for row in data['rows']:
  state=row.get('live_acceptance_state')
  if state not in {'not established','unverified','blocked','failed','live-verified'}:raise ValueError('Unknown live acceptance state')
  if state=='live-verified':
   if row.get('deployment_state') not in {'deployed','live-verified'}:raise ValueError('Live row needs deployed state')
   if not isinstance(row.get('acceptance_owner'),str) or not row['acceptance_owner'].strip():raise ValueError('Live row needs acceptance owner')
   if not any(groups[key].get('stage')=='live-verified' and groups[key].get('result')=='PASS' and row['feature_id'] in groups[key]['feature_ids'] for key in row['evidence_ids']):raise ValueError('Live row needs feature-scoped live evidence')
 # Metadata consistency is not a substitute for reading actual runtime receipts.
 return True
def render(features,data):
 validate(features,data)
 live_count=sum(r.get('live_acceptance_state')=='live-verified' for r in data['rows'])
 live_summary='No row currently has established live acceptance.' if not live_count else f'Recorded live-acceptance metadata: {live_count} row(s). Inspect linked receipts; schema validation does not establish runtime behavior.'
 groups={g['id']:g for g in data['evidence_groups']};mapped={r['feature_id']:r for r in data['rows']};parts=[]
 parts.append('<p><a href="FEATURE_OWASP_REVIEW.html">12 Nov row-by-row classification review</a> links all80 stable feature dimensions to both governing references and the three risk controls. Documentary review leaves original draft tags, roadmap items and recorded operational evidence unchanged.</p>')
 parts.append('<p>OWASP ASI01–ASI10 is the primary grouping; the three risk controls are the secondary crosswalk. All80 original rows remain:76 controls/roadmap items and4 cross-cutting evidence obligations. Primary category, layer, risk, C/I/A and control-family tags remain draft-inferred. The existing asi_all mapping is retained; no OWASP certification or all-feature operational PASS is claimed.</p>')
 parts.append('<h2>Both confirmed references and remaining analysis</h2><p><a href="AGENT_SAFETY_LAYERS.html">DQ safety design</a> supplies the Guardrails, Verification and Sandbox vocabulary. It is a DQ worked example, not proof its specific SQL/database controls apply to every DSH agent. The companion private assessment supplies control-family vocabulary. Its35-row English draft subset matches retained structured data; three other worksheets have not been semantically reconciled. No exact35-to80 feature/tool identity is inferred. The workbook, private rows and payloads are not served or mirrored.</p><p><a href="THREE_RISK_CONTROLS.html">Three risk controls</a>: '+esc(' · '.join(data['three_risk_controls'].values()))+'. <a href="security-data/feature-reference-evidence.public.json">Public mapping and evidence metadata</a>.</p>')
 parts.append('<p>State meanings: source-tested means only the recorded local aspect passed; deployed needs an exact application digest/environment binding; live-verified needs affected positive and negative behavior. Failed describes its recorded test context. Untested, unverified, blocked and missing ownership remain explicit. '+esc(live_summary)+' Topic source/test filenames are not executed tests.</p>')
 for category in list(sorted(data['owasp_categories']))+['ALL']:
  fs=[f for f in features['features'] if f['asi_primary']==category]
  title=category+' '+(data['owasp_categories'][category][0] if category!='ALL' else 'Cross-cutting evidence')
  parts.append('<h2>'+esc(title)+'</h2><div class="table"><table><thead><tr><th>Feature</th><th>OWASP and three-risk mapping</th><th>Layer and control family</th><th>Both-reference crosswalk</th><th>Source/test candidates</th><th>Evidence and acceptance state</th></tr></thead><tbody>')
  for f in fs:
   r=mapped[f['n']];refs=lambda xs:'<br>'.join('<code>'+esc(x['path'])+'</code><br><small>SHA256 '+esc(x['sha256'])+'</small>' for x in xs)
   evidence=[]
   for key in r['evidence_ids']:
    g=groups[key];evidence.append('<a href="#evidence-'+esc(key)+'">'+esc(g['result'])+'</a><br>'+esc(g['scope']))
   parts.append('<tr id="feature-'+str(f['n'])+'"><th>'+str(f['n'])+'. '+esc(f['feature'])+'</th><td>'+esc(f['asi_primary'])+'<br>Existing mapping: '+esc(', '.join(f['asi_all']))+'<br>'+esc(data['three_risk_controls'].get(f['risk'],'Cross-cutting'))+'</td><td>'+esc(f['layer'] or 'No layer assignment')+'<br>'+esc(f['control_type'] or 'No control-family assignment')+'<br>C/I/A: '+esc(f['cia'] or 'Cross-cutting')+'<br>'+esc(f['tag_status'])+'</td><td><a href="AGENT_SAFETY_LAYERS.html">DQ design</a>: '+esc(r['dq_reference_mapping'])+'<br>Internal assessment: '+esc(r['private_reference_mapping'])+'</td><td>'+refs(r['implementation_candidates'])+'<hr>'+refs(r['test_source_candidates'])+'<p>'+esc(r['candidate_scope'])+' Named source '+esc(data['named_source_commit'])+'</p></td><td>Source status: '+esc(f['evidence_status'])+'<br>Recorded aspect: '+esc(r['source_evidence_state'])+'<br>Deployment: '+esc(r['deployment_state'])+'<br>Live acceptance: '+esc(r['live_acceptance_state'])+'<br>Acceptance owner: '+esc(r['acceptance_owner'])+'<p>'+('<br>'.join(evidence) or 'Test ID/date/commit/image/environment/result/link/owner: no executed feature receipt recorded')+'</p><p>'+esc(r['remaining_gap'])+'</p></td></tr>')
  parts.append('</tbody></table></div>')
 parts.append('<h2>Executed evidence, separate from mappings</h2><p>Recorded groups contain four environment-forwarding unit cases,17 credential-policy assertions, and six owned-cache helper methods. The last group has five dynamic helper cases and one static source-wiring case. Shared feature references do not multiply the executed checks. These groups cover narrow local aspects only; the native SDK qualification failure remains separate and unchanged. No new tests or provider calls are executed by this renderer.</p>')
 for g in data['evidence_groups']:
  parts.append('<section id="evidence-'+esc(g['id'])+'"><h3>'+esc(g['id'])+'</h3><dl>')
  for k,v in g.items():
   if k=='display_log':continue
   parts.append('<dt>'+esc(k)+'</dt><dd>'+esc(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v)+'</dd>')
  parts.append('</dl>')
  if g.get('display_log'):parts.append('<details><summary>Recorded local unit log; display line endings normalized</summary><pre>'+esc(g['display_log'])+'</pre></details>')
  parts.append('</section>')
 return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>80-feature control traceability</title><style>body{font:16px/1.5 system-ui;color:#173047;margin:24px}main{max-width:1600px;margin:auto}.table{overflow:auto}table{border-collapse:collapse;width:100%;min-width:1000px}td,th{padding:12px;border:1px solid #bbc8d5;text-align:left;vertical-align:top;overflow-wrap:anywhere}code,dd,pre{overflow-wrap:anywhere}pre{white-space:pre-wrap}dd{margin:0 0 12px}section{border-top:1px solid #bbc8d5}</style></head><body><main><nav><a href="index.html">Library</a> · <a href="FEATURE_MATRIX_BY_OWASP.html">OWASP matrix</a> · <a href="THREE_RISK_CONTROLS.html">Three risk controls</a> · <a href="HARNESS_TERMINOLOGY.html">Agent and harness terminology</a></nav><h1>80-feature control traceability</h1>'+''.join(parts)+'</main></body></html>\n'
def main():
 p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');a=p.parse_args();fp=ROOT/'docs/security-data/features.json';data=json.loads((ROOT/'docs/security-data/feature-reference-evidence.public.json').read_text(encoding='utf-8'))
 if hashlib.sha256(fp.read_bytes()).hexdigest()!=data['feature_source_sha256']:raise ValueError('Feature data changed; refresh source mapping explicitly')
 result=render(json.loads(fp.read_text(encoding='utf-8')),data).encode();dest=ROOT/'docs/FEATURE_CONTROL_TRACEABILITY.html'
 if a.check:
  if dest.read_bytes()!=result:raise SystemExit('Traceability page is stale')
 else:dest.write_bytes(result)
if __name__=='__main__':main()
