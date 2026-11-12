from pathlib import Path
import argparse,zipfile,io,copy,hashlib,json,xml.etree.ElementTree as E
parser=argparse.ArgumentParser(description='Reframe the exact historical domain-routing deck with current qualification and control context, preserving its layouts.')
parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
source=args.source.read_bytes();assert hashlib.sha256(source).hexdigest()=='64e6401994aff11ad727da84877e41595850e8a5f5056a070258c2d1584bb09f','Unexpected original edition; review source before revision'
root=args.output_dir;root.mkdir(parents=True,exist_ok=True);z=zipfile.ZipFile(io.BytesIO(source));A='{http://schemas.openxmlformats.org/drawingml/2006/main}';P='{http://schemas.openxmlformats.org/presentationml/2006/main}'
SUMMARY=[['DSH applications and current qualification', '01', 'OpenShell and A2A are being qualified. Full operational acceptance remains incomplete.', '02', 'Application access supports gated and Public visitor policies.', '03', 'Application login remains separate from DSH sign-in.', '04', 'Current state and evidence: docs/LIBRARY_CURRENT_STATE.html', '11 November 2026. Source revision pending release and served-content verification.'], ['Two references and three risk controls', '01', 'Design reference: dq-agent-safety.html. Exact fingerprints are in the current-state map.', '02', 'Internal tool-and-risk assessment workbook: private payload, public fingerprint only.', '03', 'Prevent external leakage. Prevent damage or excessive access. Keep results contained.', '04', '80 feature rows across 10 OWASP Agentic domains: 76 primary assignments and 4 shared rows.', '11 November 2026. Source revision pending release and served-content verification.'], ['Evidence and remaining acceptance work', '01', 'The October App5/App6 login observations are historical. Fresh checks require new evidence.', '02', 'Component connections: GOVERNED_HARNESS_ARCHITECTURE.html, diagram G00.', '03', 'All 80 rows retain their identifiers. Feature-wide live acceptance remains unestablished.', '04', 'OpenShell native checks, full A2A routes, recovery and rollback evidence remain incomplete.', '11 November 2026. Source revision pending release and served-content verification.']]
NOTES=['Current qualification as of 11 November 2026: OpenShell native acceptance, the complete governed A2A routes, recovery and rollback remain incomplete. App5/App6 observations from October are retained in the original edition and are historical. Application login is separate from DSH access. Current source state: docs/LIBRARY_CURRENT_STATE.html. Source changes and CI do not establish live acceptance.\n\n', 'Governing references: dq-agent-safety.html SHA256 7fe84d37879b91964349a81a84d34762ebff965930596e93a1ccdd4b7a28115f; internal tool-and-risk assessment workbook SHA256 214e604a349bf1955171504f4ba42e1f59fb01101fc717a4d9453ef6d860d937. The workbook payload remains private. Three controls: prevent external leakage; prevent damage or excessive access; keep results contained. OWASP Top 10 for Agentic Applications 2026: 76 primary assignments and four shared evidence rows, across ten domains. See docs/FEATURE_CONTROL_TRACEABILITY.html. Mapping does not prove operational implementation.\n\n', 'Architecture source: docs/GOVERNED_HARNESS_ARCHITECTURE.html#g00-component-deployment. G00 is a source/configuration map, not fresh running image or workload identity evidence. All eighty feature IDs remain in the traceability ledger. Full feature-wide live acceptance is unestablished. Remaining evidence includes native OpenShell checks, the full A2A routes, recovery and rollback. This revised binary must be committed and published through the project-owned release route, then compared against the actually served bytes.\n\n']
changes={};edits=[]
def replace(shape,new,slide):
 nodes=shape.findall('.//'+A+'t');old=''.join(n.text or '' for n in nodes);nodes[0].text=new
 for n in nodes[1:]:n.text=''
 for parent in shape.iter():
  if parent.tag==A+'rPr':parent.attrib.pop('u',None)
  for child in list(parent):
   if child.tag in (A+'hlinkClick',A+'hlinkMouseOver'):parent.remove(child)
 edits.append({'slide':slide,'before':old,'after':new})
for i in range(1,18):
 name=f'ppt/slides/slide{i}.xml';tree=E.fromstring(z.read(name));shapes=[s for s in tree.findall('.//'+P+'sp') if s.findall('.//'+A+'t')]
 if i>=15:
  assert len(shapes)==len(SUMMARY[i-15])==10
  for j,s in enumerate(shapes):replace(s,SUMMARY[i-15][j],i)
 else:
  for j,s in enumerate(shapes):
   old=''.join(n.text or '' for n in s.findall('.//'+A+'t'));new=old
   if j==len(shapes)-1:new='Historical October routing lesson. Current qualification and controls: slides 15-17. Revised 11 November 2026.'
   else:
    new=new.replace('Actual Test application links','Historical Test application examples').replace('Current settings:','October settings example:').replace('Working example,','Historical example,').replace('Current DSH and dedicated Test flows','Main and Test routing lesson').replace('RegChat is a working example.','RegChat was the recorded example.').replace('The verified login flow uses','The recorded login flow used')
   if new!=old:replace(s,new,i)
 changes[name]=E.tostring(tree,encoding='utf-8',xml_declaration=True)
 name=f'ppt/notesSlides/notesSlide{i}.xml';tree=E.fromstring(z.read(name));nodes=tree.findall('.//'+A+'t');old='\n'.join(n.text or '' for n in nodes);assert nodes
 text=NOTES[i-15] if i>=15 else 'Historical routing lesson from October 2026, retained for explanation. This is not a fresh live verification. Current OpenShell and A2A full acceptance remains incomplete. Governing references, the three risk controls, the eighty-row OWASP crosswalk and remaining acceptance work are on slides 15-17 and docs/LIBRARY_CURRENT_STATE.html. Historical source narration follows:\n\n'+old
 nodes[0].text=text
 for n in nodes[1:]:n.text=''
 changes[name]=E.tostring(tree,encoding='utf-8',xml_declaration=True)
out=io.BytesIO()
with zipfile.ZipFile(out,'w') as dst:
 for item in z.infolist():dst.writestr(copy.copy(item),changes.get(item.filename,z.read(item.filename)))
final=out.getvalue();(root/'revised-draft.pptx').write_bytes(final)
with zipfile.ZipFile(io.BytesIO(final)) as after:
 assert set(after.namelist())==set(z.namelist())
 assert set(n for n in z.namelist() if z.read(n)!=after.read(n))==set(changes)
 for i in range(1,18):
  n=f'ppt/slides/slide{i}.xml';assert len(E.fromstring(z.read(n)).findall('.//'+P+'sp'))==len(E.fromstring(after.read(n)).findall('.//'+P+'sp'))
receipt={'source_path':'docs/presentations/DSH_Domain_Routing_English.pptx','source_basis':'dd2893043d0f6659a3ba63c01f09741bd86bdf45','original_sha256':hashlib.sha256(source).hexdigest(),'final_sha256':hashlib.sha256(final).hexdigest(),'bytes':len(final),'slides':17,'changed_members':list(changes),'edits':edits,'original_preserved':True,'scope':'Historical routing lesson retained with explicit context; slides15-17 carry current references, controls and incomplete qualification. No new live routing/agent acceptance claimed.'}
(root/'REVISION_CONTENT_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8');print(receipt['final_sha256'])
