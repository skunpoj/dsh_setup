from pathlib import Path
import zipfile,io,hashlib,json,copy,xml.etree.ElementTree as E

import argparse
parser=argparse.ArgumentParser(description='Revise the exact historical three-slide login guide without changing its layout.')
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
args=parser.parse_args()
root=args.output_dir;root.mkdir(parents=True,exist_ok=True)
source=args.source.read_bytes()
assert hashlib.sha256(source).hexdigest()=='854488769b92ca1eb9553a2d4a646ebcbc2268e937cd2904f5f2d6f4a5a6991a','Unexpected original edition; review source before revision'
z=zipfile.ZipFile(io.BytesIO(source))
A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
P='{http://schemas.openxmlformats.org/presentationml/2006/main}'
slides=[
 ['DSH applications and current qualification',
  'OpenShell and A2A are being qualified. Full operational acceptance remains incomplete.',
  'Application access supports gated and Public visitor policies.',
  'Application login remains separate from DSH sign-in.',
  'Current state and evidence: docs/LIBRARY_CURRENT_STATE.html'],
 ['Two references and three risk controls',
  'Design reference: dq-agent-safety.html. Exact fingerprints are in the current-state map.',
  'Internal tool-and-risk assessment workbook: private payload, public fingerprint only.',
  'Prevent external leakage. Prevent damage or excessive access. Keep results contained.',
  '80 feature rows across 10 OWASP Agentic domains: 76 primary assignments and 4 shared rows.'],
 ['Evidence and remaining acceptance work',
  'The October App5/App6 login observations are historical. Fresh checks require new evidence.',
  'Component connections: GOVERNED_HARNESS_ARCHITECTURE.html, diagram G00.',
  'All 80 rows retain their identifiers. Feature-wide live acceptance remains unestablished.',
  'OpenShell native checks, full A2A routes, recovery and rollback evidence remain incomplete.']
]
footer='11 November 2026. Source revision pending release and served-content verification.'
changed={}; records=[]
for i,content in enumerate(slides,1):
 name=f'ppt/slides/slide{i}.xml'; raw=z.read(name);tree=E.fromstring(raw)
 shapes=tree.findall('.//'+P+'sp')
 texts=[s for s in shapes if s.findall('.//'+A+'t')]
 assert len(texts)==10
 replacements={0:content[0],2:content[1],4:content[2],6:content[3],8:content[4],9:footer}
 for index,new in replacements.items():
  shape=texts[index];nodes=shape.findall('.//'+A+'t');old=''.join(n.text or '' for n in nodes)
  nodes[0].text=new
  for runprop in shape.iter(A+'rPr'):runprop.attrib.pop('u',None)
  for n in nodes[1:]:n.text=''
  for parent in shape.iter():
   for child in list(parent):
    if child.tag in (A+'hlinkClick',A+'hlinkMouseOver'):parent.remove(child)
  records.append({'slide':i,'shape_index':index,'before':old,'after':new})
 changed[name]=E.tostring(tree,encoding='utf-8',xml_declaration=True)
notes=[
 'Current qualification as of 11 November 2026: OpenShell native acceptance, the complete governed A2A routes, recovery and rollback remain incomplete. App5/App6 observations from October are retained in the original edition and are historical. Application login is separate from DSH access. Current source state: docs/LIBRARY_CURRENT_STATE.html. Source changes and CI do not establish live acceptance.',
 'Governing references: dq-agent-safety.html SHA256 7fe84d37879b91964349a81a84d34762ebff965930596e93a1ccdd4b7a28115f; internal tool-and-risk assessment workbook SHA256 214e604a349bf1955171504f4ba42e1f59fb01101fc717a4d9453ef6d860d937. The workbook payload remains private. Three controls: prevent external leakage; prevent damage or excessive access; keep results contained. OWASP Top 10 for Agentic Applications 2026: 76 primary assignments and four shared evidence rows, across ten domains. See docs/FEATURE_CONTROL_TRACEABILITY.html. Mapping does not prove operational implementation.',
 'Architecture source: docs/GOVERNED_HARNESS_ARCHITECTURE.html#g00-component-deployment. G00 is a source/configuration map, not fresh running image or workload identity evidence. All eighty feature IDs remain in the traceability ledger. Full feature-wide live acceptance is unestablished. Remaining evidence includes native OpenShell checks, the full A2A routes, recovery and rollback. This revised binary must be committed and published through the project-owned release route, then compared against the actually served bytes.'
]
for i,text in enumerate(notes,1):
 name=f'ppt/notesSlides/notesSlide{i}.xml';tree=E.fromstring(z.read(name));nodes=tree.findall('.//'+A+'t');assert nodes;nodes[0].text=text
 for n in nodes[1:]:n.text=''
 changed[name]=E.tostring(tree,encoding='utf-8',xml_declaration=True)
out=io.BytesIO()
with zipfile.ZipFile(out,'w') as dst:
 for item in z.infolist():dst.writestr(copy.copy(item),changed.get(item.filename,z.read(item.filename)))
draft=root/'revised-draft.pptx';draft.write_bytes(out.getvalue())
with zipfile.ZipFile(draft) as after:
 assert set(after.namelist())==set(z.namelist())
 assert set(n for n in z.namelist() if z.read(n)!=after.read(n))==set(changed)
 for n in changed:
  assert len(E.fromstring(after.read(n)).findall('.//'+P+'sp'))==len(E.fromstring(z.read(n)).findall('.//'+P+'sp'))
receipt={'source_path':'docs/presentations/APP_LOGIN_MAIN_TEST_EN.pptx','source_basis':'1dd46cb876c1bfe66681aa117ccaa88b6330e935','source_sha256':hashlib.sha256(source).hexdigest(),'draft_sha256':hashlib.sha256(out.getvalue()).hexdigest(),'only_modified_zip_members':list(changed),'edits':records,'original_preserved':True,'binary_revision_scope':'One existing three-slide guide; other seven decks and three PDFs remain pending','rendered_verification':'PENDING','publication':'PENDING'}
(root/'REVISION_CONTENT_RECEIPT.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in receipt.items() if k!='edits'},indent=2))
