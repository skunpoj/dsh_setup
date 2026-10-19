import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..');
const modules=process.env.DSH_DOC_NODE_MODULES || 'C:/Users/skunpojt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
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

Self-registration is disabled. Only administrators can create accounts for provisioned private runtimes through Admin overview → User management. Creating an account does not automatically provision compute or storage.

Internet access is a separate per-user permission. Every non-admin account starts without it; administrators retain access and may grant or revoke it individually. The Internet radio option is disabled until valid credentials confirm the permission. The server rejects a forged Internet selection regardless of the browser state. Revocation signs the user out and closes tracked gateway connections; it does not cancel tools already executing. Password changes preserve the permission. No Internet remains the default even for approved users.

These controls are deployed on the main gateway. Separate legacy-instance gateways are not covered by this permission change. Activity oversight and account administration do not grant ownership of private user content.

The deployed dashboard provides account management, access activity and numeric summaries from the 18 configured private runtimes: stored sessions, running agents, queued messages, turns, LLM steps, input/output token totals, recorded decode and wall-clock output rates, and workspace/durable-storage sizes. These are scoped snapshots, not live GPU utilization or independent Claude Code/TrueForge accounting. Actual deployed-code authorization and numeric collection were checked using a loopback-only disposable authenticated account; a real administrator password/browser login was not part of that acceptance. See the [dashboard definitions and scope](ADMIN_USAGE_TELEMETRY.html). Saved demonstration screenshots do not show current utilization.

## Environment and access design

Users enter through the authenticated gateway. The selected identity and environment determine the private runtime and storage scope; browser-supplied names or routing headers do not grant access to another user's environment.

| Access surface | Purpose | Enforced boundary |
|---|---|---|
| Main No Internet environment | Work with internal data and tools without direct public Internet access | Default environment; private execution/storage and restricted destinations. Remote submitted jobs remain subject to their own platform's network controls. |
| Main Internet environment | Prepare dependencies and perform explicitly Internet-capable work | Separate private execution, files, histories and credentials. It does not mount protected No Internet content. |
| Additional owner instances | Provide an assigned owner's Internet-capable workspace | Owner-only authentication and scoped storage; not represented as No Internet environments. |
| Admin overview, /admin | Manage provisioned accounts and review access events | Admin authorization; operational oversight does not automatically grant ownership of users' files or histories. |
| Terminal, /terminal, and approved application previews | Run tools and view generated applications in the selected environment | Authenticated HTTP/WebSocket routing and the same private runtime identity, mounts and network policy. |
| Shared internal inference and optional embeddings | Serve model requests without duplicating GPU models for each user | Internal authenticated route with controlled destinations; shared inference does not merge workspaces. |

Logout ends the gateway session. Changing environment requires signing in again and does not copy files, conversation history or credentials between environments. Incoming and approved package areas provide the controlled dependency-transfer path; they are not shared project storage.

`+find('Interface screenshots').replace('The login screenshots show the live interfaces.', 'The sign-in screenshot illustrates the recorded interface, not a fresh availability check.').replace('Live main DSH login with empty fields','Main DSH sign-in interface with empty fields');
const platformSetup=`## Deploy the DSH application and private environments

### 1 Prepare site settings and preserve rollback

Choose the approved namespace, public gateway hostname, trusted CA, internal service destinations, storage claims and operator identities. Keep private settings and credential values outside Git. Save current image digests, workload/configuration specifications and history/workspace checks before an existing-site change. Build a test namespace first; a documentation example is not an instruction to apply all legacy manifests.

### 2 Build and qualify the application image

The repository Dockerfile packages pinned DSH, Claude Code and TrueForge versions, Linux/Python/Kerberos tooling and the reviewed compatibility overlays. Its default package versions are DSH 0.2.0-rc.2, Claude Code 2.1.301 and TrueForge 0.179.2. Build through the approved image pipeline, inspect the installed package/patch checks and retain the pushed immutable digest. No Internet runtime must start from a prebuilt image rather than downloading packages at startup. Version pins are source defaults, not a fresh check of the upstream registry.

### 3 Provision private storage and identity routes

Use one private runtime per user and environment with bounded workspace, session, attachment and credential mounts. Assign the original owner explicitly when migrating existing content. No Internet uses scoped central storage for durable work/history; keep credentials private and Internet staging separate. Approved packages are read-only to No Internet. Run as the configured non-root identity and map share permissions deliberately. Do not mount a broad parent containing other users' content or migrate a live writer without reconciliation.

### 4 Configure the gateway, policy and internal services

Provision accounts through the protected gateway store and map server-side user/environment routes. Disable self-registration. Only admin may create provisioned accounts; default Internet permission to denied for non-admins and grant it individually through User management. Verify both the disabled selector and server-side refusal, permission persistence and revocation of existing sessions. Do not put credentials into source manifests. Default login to No Internet; switching requires a new login. Apply the enforcing network policies, filtered internal DNS and service-specific allowlists before making the environment available. Cover gateway, tools, inference and database separately. Retain authenticated terminal, attachment/report and application-preview routes; do not create a public bypass. Livy/Spark remains available under its documented remote-network boundary.

### 5 Provision named accounts and verify isolation

Create only accounts with an already provisioned private runtime pair, then let owners change initial passwords privately. Verify correct and incorrect login, logout, role checks, cross-user file/history refusal, terminal routing, No Internet public-destination denial, internal inference and approved-package read-only behavior. Use synthetic users/content for negative tests. A successful login alone does not verify storage or network isolation.

### 6 Check persistence, dashboard and handover

Create a disposable workspace/history marker, replace the intended runtime in a controlled test and read back the same content. Check the centralized dashboard and access audit without exposing credentials or conversation bodies. Preserve existing histories byte-for-byte during migrations; central persistence is not an independent backup. Roll back application/image/configuration on regression while retaining newer durable writes.

The detailed operational procedures remain in [storage and persistence](https://github.com/skunpoj/dsh_setup/blob/main/docs/MULTI_TENANT_STORAGE_AND_PERSISTENCE.md), [upstream maintenance](https://github.com/skunpoj/dsh_setup/blob/main/docs/UPSTREAM_SYNC_AND_INTERNET_POLICY.md) and the reviewed repository deployment sources. Site-specific Secret, storage and destination values are intentionally not supplied by this public guide.

`;
const setup=`# DSH — Step-by-Step Setup and Stress-Test Results\n\nThis operator guide separates reproducible setup, recorded accepted behavior and experimental profiles. Read the companion [Security, Environments and Features](${companionSecurity}) for the three risk boundaries and interface screenshots. Creating these documents does not deploy or benchmark the system.\n\n${status}\n\n${platformSetup}## Shared inference architecture\n${gpuArchitecture}\n## Step-by-step GPU and LiteLLM setup\n\nThese steps reproduce the current qualified portable profile, including its reviewed runtime overlays. Verify the pinned sources and requalify behavior on the target environment before rollout.\n\n${gpuSteps}\n${find('Example usage').replace('## Example usage','## Use the deployed platform')}\n${find('Storage, administration and maintenance')}\n## Qualification results and stress-test history\n\nThe following results describe their stated workloads and dates. The current qualification is summarized above; older restored or rejected profiles remain explicitly historical. Streaming tokens/sec, whole-request latency and aggregate throughput measure different things. A configured request cap does not prove that many full-context requests can execute together.\n\n${history}`;
const shell=fs.readFileSync(path.join(root,'docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html'),'utf8');
const head=shell.slice(0,shell.indexOf('<body>'));
const scripts=shell.slice(shell.indexOf('</main>')+7);
const esc=x=>x.replaceAll('&','&amp;').replaceAll('"','&quot;');
for(const [name,title,md]of [['DSH_SECURITY_ENVIRONMENT_AND_FEATURES','DSH — Security, Environments and Features',security],['DSH_SETUP_AND_STRESS_TEST_GUIDE','DSH — Setup and Stress-Test Results',setup]]){
 const resolved=md;
 fs.writeFileSync(path.join(root,'docs',name+'.md'),resolved);
 let html=marked.parse(resolved);let diagram=0;
 html=html.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,(_,code)=>`<section class="mermaid-wrapper"><div class="mermaid-header"><span>Architecture ${++diagram}</span><div class="mermaid-toolbar"><button onclick="panZoomMermaid(this,'zoomIn')" aria-label="Zoom in">+</button><button onclick="panZoomMermaid(this,'zoomOut')" aria-label="Zoom out">−</button><button onclick="panZoomMermaid(this,'reset')">Reset</button><button onclick="panZoomMermaid(this,'fullscreen')">Fullscreen</button><button onclick="exportMermaid(this,'svg')">Save SVG</button><button onclick="exportMermaid(this,'png')">Save PNG</button><button onclick="exportMermaid(this,'copy')">Copy code</button></div></div><div class="mermaid-container"><div class="mermaid" data-raw-code="${code.replaceAll('"','&quot;')}">${code}</div></div></section>`);
 html=html.replace(/<img src="(images\/platform\/[^"\s]+)" alt="([^"]*)">/g,(_,image,alt)=>`<img src="data:image/png;base64,${fs.readFileSync(path.join(root,'docs',image)).toString('base64')}" alt="${alt}">`);
 const toc=[];html=html.replace(/<h2>(.*?)<\/h2>/g,(_,title)=>{const id='section-'+(toc.length+1);toc.push(`<a href="#${id}">${title}</a>`);return `<h2 id="${id}">${title}</h2>`;});
 const result=head.replace(/<title>.*?<\/title>/,`<title>${title}</title>`).replace('</style>','img{max-width:100%;height:auto;display:block;margin:20px auto;border:1px solid #cedce8;border-radius:8px}table{table-layout:fixed}</style>')+'<body><main>'+html.replace(/(<h1>.*?<\/h1>)/,`$1<nav aria-label="Contents">${toc.join('')}</nav>`)+'</main>'+scripts;
 fs.writeFileSync(path.join(root,'docs',name+'.html'),result);
 console.log(JSON.stringify({file:name+'.html',sections:toc.length,diagrams:diagram,bytes:Buffer.byteLength(result),sourceSHA256:crypto.createHash('sha256').update(guide).digest('hex')}));
}
