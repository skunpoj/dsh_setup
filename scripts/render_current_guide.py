from pathlib import Path
import json,hashlib,html,argparse,re
p=argparse.ArgumentParser(description="Render canonical HTML and Markdown from the current-guide source JSON.")
p.add_argument('--source',required=True)
p.add_argument('--output-dir',required=True)
p.add_argument('--deck',required=True)
p.add_argument('--inventory')
a=p.parse_args()
x=json.loads(Path(a.source).read_text(encoding='utf8'))
ref=x['source_commit']
assert re.fullmatch(r'[0-9a-f]{40}',ref)
for s in x['slides']:
    assert all(re.fullmatch(r'[A-Za-z0-9_.-]+',n) for n in s['sources'])
D=Path(a.output_dir);D.mkdir(parents=True,exist_ok=True)
assert Path(a.deck).stat().st_size<=8*1024*1024
deck=Path(a.deck).read_bytes()
published=json.loads(Path(a.inventory).read_text())['files'] if a.inventory else {}
def sha(b):return hashlib.sha256(b).hexdigest()
def source_md(n):
    target=n if n in published else n[:-3]+'.html'
    return '['+n+']('+target+')' if target in published else n+' (repository source)'
def source_html(n):
    target=n if n in published else n[:-3]+'.html'
    return '<a href="'+target+'">'+html.escape(n)+'</a>' if target in published else html.escape(n)+' (repository source)'
md=['# DSH Current Guide','',f"Implementation reference: `{ref}`. One canonical guide; video lessons retain their own source snapshots.",'']
sections=[]
for i,s in enumerate(x['slides'],1):
    md += [f"## {i} {s['title']}",'',s['lead'],'']+['- '+p for p in s['points']]+['','Sources: '+', '.join(source_md(n) for n in s['sources']), '']
    sections.append(f'<section id="chapter-{i}"><h2>{i} {html.escape(s["title"])}</h2><p class="lead">{html.escape(s["lead"])}</p><ul>'+''.join('<li>'+html.escape(p)+'</li>'for p in s['points'])+'</ul><p class="sources">Sources: '+', '.join(source_html(n) for n in s['sources'])+'</p></section>')
(D/'DSH_CURRENT_GUIDE.md').write_text('\n'.join(md),encoding='utf8')
style='body{font:18px system-ui;max-width:1040px;margin:32px auto;padding:20px;color:#163247;line-height:1.65}h1,h2{line-height:1.2}section{padding:24px 0;border-top:1px solid #ccd8df}li{margin:12px 0}a{color:#0759a5}.lead{color:#386776}.sources,code{font-size:14px;overflow-wrap:anywhere}nav a{margin-right:18px}'
header='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>DSH Current Guide</title><style>'+style+'</style><main><h1>DSH Current Guide</h1><p>One current guide for everyday work, risk controls, application access and safe operation.</p><p class="sources">SHA-256: <code>'+sha(deck)+'</code><br>Implementation reference: <code>'+ref+'</code></p><nav><a href="index.html">Documentation library</a><a href="DSH_USER_MANUAL.html">Detailed user manual</a><a href="COURSE_GUIDE.html">Video courses</a></nav><details><summary>Contents</summary><ol>'+''.join('<li><a href="#chapter-'+str(i)+'">'+html.escape(s['title'])+'</a></li>'for i,s in enumerate(x['slides'],1))+'</ol></details>'
header=header.replace('31 slides',str(len(x['slides']))+' slides')
(D/'DSH_CURRENT_GUIDE.html').write_text(header+''.join(sections)+'</main></html>',encoding='utf8')
from documentation_requirements import apply_guide
apply_guide()
print('Rendered canonical guide plus requirements supplement.')

from documentation_requirements import public_projection_html, public_projection_markdown
for name in ['DSH_CURRENT_GUIDE.html','DSH_CURRENT_GUIDE.md']:
    target=D/name
    text=target.read_text(encoding='utf-8')
    target.write_text(public_projection_html(text,target) if name.endswith('.html') else public_projection_markdown(text,target),encoding='utf-8')
