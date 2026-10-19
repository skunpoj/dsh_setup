import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || path.join(root,'node_modules');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const arg=process.argv.indexOf('--status');
const status=fs.readFileSync(arg<0 ? path.join(root,'docs/context-evidence/SPLIT_GUIDE_STATUS_20261019.md') : process.argv[arg+1],'utf8');
const guide=fs.readFileSync(path.join(root,'docs/DSH_PLATFORM_GUIDE.md'),'utf8').replaceAll('\r\n','\n');
const parts=guide.split(/(?=^## )/m);
const find=name=>{const found=parts.find(p=>p.startsWith('## '+name+'\n'));if(!found)throw Error('Missing section '+name);return found;};
const gpu=find('LLM and GPU setup');
const firstStep=gpu.indexOf('### 1 Prepare prerequisites');
const profile=gpu.indexOf('### Runtime profile');
if(firstStep<0||profile<0)throw Error('GPU source structure changed');
const gpuArchitecture=gpu.slice('## LLM and GPU setup'.length,profile);
const gpuSteps=gpu.slice(firstStep);
const history=gpu.slice(profile,firstStep).replace('Live configured profile','Qualified profile at the recorded review');
const companionSecurity='DSH_SECURITY_ENVIRONMENT_AND_FEATURES.html';
const companionSetup='DSH_SETUP_AND_STRESS_TEST_GUIDE.html';
const prefix=parts[0].replace(/^# [^\n]*\n/,'').trim();
const security=`# DSH — Security, Environments and Features\n\nThis guide explains how the platform controls external leakage, damage or excessive access, and exposure of results, followed by its features and labelled interface screenshots. The environment outline is incorporated as design decisions rather than treated as an approved configuration.\n\nFor installation, configuration, rollback and measured results, use the companion [Setup and Stress-Test Guide](${companionSetup}).\n\n${prefix}\n\n`+
 ['1 Prevent external leakage','2 Prevent damage or excessive access','3 Keep results contained','Connected services and responsibilities'].map(find).join('\n')+'\n'+
 find('Platform features and intended use').replace(/### Installed clients[\s\S]*/, '')+'\n'+
 `## Who can create accounts and use Internet

Use **Create account** on the login page to sign up and receive an exclusive prepared private runtime pair. Internet stays denied until an administrator grants it through User management. Administrators can also create accounts from available private capacity. Full capacity refuses signup; operators add new empty pairs. See the [signup and approval guide](SELF_SERVICE_SIGNUP.html).

Internet access is a separate per-user permission. Every non-admin account starts without it; administrators retain access and may grant or revoke it individually. The Internet radio option is disabled until valid credentials confirm the permission. The server rejects a forged Internet selection regardless of the browser state. Revocation signs the user out and closes tracked gateway connections; it does not cancel tools already executing. Password changes preserve the permission. No Internet remains the default even for approved users.

These controls are deployed on the main gateway. Separate legacy-instance gateways are not covered by this permission change. Activity oversight and account administration do not grant ownership of private user content.

The deployed dashboard provides account management, access activity and numeric summaries from the configured private runtimes, including assigned signup pairs: stored sessions, running agents, queued messages, turns, LLM steps, input/output token totals, recorded decode and wall-clock output rates, and workspace/durable-storage sizes. These are scoped snapshots, not live GPU utilization or independent Claude Code/TrueForge accounting. Actual deployed-code authorization and numeric collection were checked using a loopback-only disposable authenticated account; a real administrator password/browser login was not part of that acceptance. See the [dashboard definitions and scope](ADMIN_USAGE_TELEMETRY.html). Saved demonstration screenshots do not show current utilization.

## Admin-approved service recovery

Jupyter and user apps can use a separate managed startup service. Admin approves the owner, environment and command; new definitions are stopped until Start is selected. The non-root supervisor shares that owner's runtime network and workspace permissions, while startup policy is mounted read-only and status storage is private to the runtime. Stop prevents recovery after pod replacement. URL publication remains a separate control and does not itself execute code.

This supports controlled execution and recovery without granting broader data or Internet permissions. Durable files and notebook settings persist; unsaved kernel memory does not. See [architecture, credential boundaries and setup](APP_SERVICE_SUPERVISION.html) and [recorded admin startup workflow](APP_AUTOSTART_WALKTHROUGH.html).

## Environment and access design

Users enter through the authenticated gateway. The selected identity and environment determine the private runtime and storage scope; browser-supplied names or routing headers do not grant access to another user's environment.

| Access surface | Purpose | Enforced boundary |
|---|---|---|
| Main No Internet environment | Work with internal data and tools without direct public Internet access | Default environment; private execution/storage and restricted destinations. Remote submitted jobs remain subject to their own platform's network controls. |
| Main Internet environment | Prepare dependencies and perform explicitly Internet-capable work | Separate private execution, files, histories and credentials. It does not mount protected No Internet content. |
| Additional owner instances | Provide an assigned owner's Internet-capable workspace | Owner-only authentication and scoped storage; not represented as No Internet environments. |
| Admin overview, /admin | Manage accounts, Internet grants and available private capacity; review access events | Admin authorization; operational oversight does not automatically grant ownership of users' files or histories. |
| Terminal, /terminal, and approved application previews | Run tools and view generated applications in the selected environment | Authenticated HTTP/WebSocket routing and the same private runtime identity, mounts and network policy. |
| Shared internal inference and optional embeddings | Serve model requests without duplicating GPU models for each user | Internal authenticated route with controlled destinations; shared inference does not merge workspaces. |

Logout ends the gateway session. Changing environment requires signing in again and does not copy files, conversation history or credentials between environments. Incoming and approved package areas provide the controlled dependency-transfer path; they are not shared project storage.

`+find('Interface screenshots').replace('The login screenshots show the live interfaces.', 'The sign-in screenshot illustrates the recorded interface, not a fresh availability check.').replace('Live main DSH login with empty fields','Main DSH sign-in interface with empty fields');
const platformSetup=fs.readFileSync(path.join(root,'docs/INSTALLATION_WALKTHROUGH.md'),'utf8')+'\n\n';
const setup=`# DSH — Step-by-Step Setup and Stress-Test Results\n\nThis operator guide separates reproducible setup, recorded accepted behavior and experimental profiles. Read the companion [Security, Environments and Features](${companionSecurity}) for the three risk boundaries and interface screenshots. Creating these documents does not deploy or benchmark the system.\n\n${status.replace('## Latest implementation and qualification','## What is deployed — recorded configuration and qualification')}\n\n${platformSetup}## Shared inference architecture\n${gpuArchitecture}\n## Step-by-step GPU and LiteLLM setup\n\nThese steps reproduce the current qualified portable profile, including its reviewed runtime overlays. Verify the pinned sources and requalify behavior on the target environment before rollout.\n\n${gpuSteps}\n${find('Example usage').replace('## Example usage','## Use the deployed platform')}\n${find('Storage, administration and maintenance')}\n## Qualification results and stress-test history\n\nThe following results describe their stated workloads and dates. The current qualification is summarized above; older restored or rejected profiles remain explicitly historical. Streaming tokens/sec, whole-request latency and aggregate throughput measure different things. A configured request cap does not prove that many full-context requests can execute together.\n\n${history}`;
const shell=fs.readFileSync(path.join(root,'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html'),'utf8');
const head=shell.slice(0,shell.indexOf('<body>'));
const scripts=shell.slice(shell.indexOf('</main>')+7);
const esc=x=>x.replaceAll('&','&amp;').replaceAll('"','&quot;');
for(const [name,title,md]of [['DSH_SECURITY_ENVIRONMENT_AND_FEATURES','DSH — Security, Environments and Features',security],['DSH_SETUP_AND_STRESS_TEST_GUIDE','DSH — Setup and Stress-Test Results',setup]]){
 const resolved=md;
 fs.writeFileSync(path.join(root,'docs',name+'.md'),resolved);
 let html=marked.parse(resolved).replace(/href="\.\.\/([^"\s]+)"/g,(_,ref)=>`href="https://github.com/skunpoj/dsh_setup/blob/main/${ref}"`);let diagram=0;
 html=html.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,(_,code)=>`<section class="mermaid-wrapper"><div class="mermaid-header"><span>Architecture ${++diagram}</span><div class="mermaid-toolbar"><button onclick="panZoomMermaid(this,'zoomIn')" aria-label="Zoom in">+</button><button onclick="panZoomMermaid(this,'zoomOut')" aria-label="Zoom out">−</button><button onclick="panZoomMermaid(this,'reset')">Reset</button><button onclick="panZoomMermaid(this,'fullscreen')">Fullscreen</button><button onclick="exportMermaid(this,'svg')">Save SVG</button><button onclick="exportMermaid(this,'png')">Save PNG</button><button onclick="exportMermaid(this,'copy')">Copy code</button></div></div><div class="mermaid-container"><div class="mermaid" data-raw-code="${code.replaceAll('"','&quot;')}">${code}</div></div></section>`);
 html=html.replace(/<img src="(images\/platform\/[^"\s]+)" alt="([^"]*)">/g,(_,image,alt)=>`<img src="data:image/png;base64,${fs.readFileSync(path.join(root,'docs',image)).toString('base64')}" alt="${alt}">`);
 const toc=[];html=html.replace(/<h2>(.*?)<\/h2>/g,(_,title)=>{const id='section-'+(toc.length+1);toc.push(`<a href="#${id}">${title}</a>`);return `<h2 id="${id}">${title}</h2>`;});
 const result=head.replace(/<title>.*?<\/title>/,`<title>${title}</title>`).replace('</style>','img{max-width:100%;height:auto;display:block;margin:20px auto;border:1px solid #cedce8;border-radius:8px}table{table-layout:fixed}</style>')+'<body><main>'+html.replace(/(<h1>.*?<\/h1>)/,`$1<nav aria-label="Contents">${toc.join('')}</nav>`)+'</main>'+scripts;
 fs.writeFileSync(path.join(root,'docs',name+'.html'),result);
 console.log(JSON.stringify({file:name+'.html',sections:toc.length,diagrams:diagram,bytes:Buffer.byteLength(result),sourceSHA256:crypto.createHash('sha256').update(guide).digest('hex')}));
}
