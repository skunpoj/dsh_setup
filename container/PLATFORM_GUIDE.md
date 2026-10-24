# DSH shared platform guide

Guide version: 2026-10-20.1

This is platform context shared by DSH, Claude Code, Kilo and TrueForge. It does
not grant permissions or replace the user's task and project instructions.

## Accounts, environments and projects

An account receives one private execution environment for No Internet and, when
approved by an administrator, a separate Internet environment. Each has private
files, credentials and conversation state. Multiple project folders or DSH
workspaces inside that environment are not additional accounts or containers.
The clients use the same platform services but keep their own conversations.

Within one account and selected environment, DSH, Web Terminal and JupyterLab
see the same `/workspace` files directly: there is no background copy or sync
delay. Claude Code, Kilo and TrueForge launched there use that filesystem too.
Select the same project folder explicitly; a terminal's current directory or
Jupyter's open folder need not match the active DSH project automatically.
Other accounts and the account's other environment have different workspaces.
Sharing files does not merge the clients' chat histories or running kernels.

No Internet is the default. Its network policy permits required internal
services; it is not a physically disconnected air gap. Internet approval is
separate from account creation. Never claim Internet access from a model's tool
description: test the actual relevant execution path when asked. Remote
Livy/Spark workers have their own network and authorization boundaries.

An approved internal Git service can be available in No Internet without
enabling public Internet. Use the site's configured internal repository URL.
Diagnose DNS, TCP connectivity, certificate trust and repository authorization
separately. A 401 or credential prompt means authentication is required; it
does not mean Internet must be enabled. Use the user's approved credentials
privately. Never put passwords or tokens in clone URLs, instructions or logs,
disable TLS verification, or widen network rules to bypass a clone failure.

## Persistent files and instructions

Keep projects in `/workspace`. DSH history, attachments and client state use
their configured private persistent mounts under `/state`. Temporary files and
unmounted container directories are not durable storage. Do not move or delete
another user's files, copy credentials, or change mounts to solve a permission
error. Ask the operator to repair access instead. Preserve project instructions.

Internet prepares dependencies in `/packages/incoming`. An operator reviews and
promotes approved artifacts. No Internet installs from the read-only approved
cache; the Internet environment does not write its protected workspace.

## Browser applications, ports and names

Use **My apps** at `/applications` on the current platform address to register an
application name and its listening port. The registry returns the actual path
URL and, when DNS/TLS and hostname routing are configured, its hostname URL.
Use these returned URLs rather than inventing a hostname. A name check checks
the platform registry; it does not prove external DNS or a running application.

An application name maps to a port inside the selected private environment. It
does not create another workspace, start a server or permit Internet access.
The default allowance is **8 application names per account across both
environments**. Administrators can set that account's allowance. Read the live
My apps page for the current used count, allowance and enabled state; do not
assume a saved number remains current. Path and hostname for one registration
count as one name. Removing a name does not delete project files.

The canonical numeric port path is `/proxy/<port>/` on the current platform
address. Servers should listen on the required container interface. A browser
on the user's computer cannot reach container `localhost` directly. App names,
ports and URLs do not determine the number of project folders or user slots.

## DSH, terminal, notebooks and managed clients

Login offers DSH, Web Terminal and JupyterLab. DSH is the default landing page;
the selected environment remains the security boundary. `/terminal` opens the
authenticated Web Terminal. JupyterLab uses `/proxy/8888/lab`. New private
accounts are provisioned with managed Jupyter startup enabled. The supervisor
starts it only when that account and environment are allowed; an administrator's
explicit Stop is preserved. Check the managed service status if unavailable;
do not start a competing server or override an administrator's Stop. Saved
notebooks and Jupyter settings persist, while in-memory kernel computation
does not survive process replacement. A URL registration alone does not
supervise a process. Never enable unauthenticated notebook or terminal access.

Claude Code, Kilo and TrueForge use the operator-managed internal LiteLLM model
route. Changing a client name does not change account permissions. TrueForge's
local code sandbox may be unavailable under the container's restrictions; do
not weaken those restrictions to make it work.

## Inference and responsiveness

The main managed route supports a **1,048,576 total-token ceiling**, including
input, tool definitions and generated output; the maximum output is 8,192.
These are limits, not the size or speed of every request. One request above
128K is admitted at a time; shorter work can remain parallel. Long context
preparation may take many minutes. A busy response requires retrying later,
not bypassing admission or changing the provider. Verify the actual active
profile before extending this statement to another deployment.

For a short question, check only the facts needed and answer briefly. Batch
independent read-only checks where practical. Do not explore unrelated systems
or create reports unless requested. Never sacrifice accuracy or required
authorization to reduce response time.

## Administration and help

The admin dashboard at `/admin` manages accounts, environment approval,
application names/ports and per-user allowances. Capacity for new accounts is
the number of unused pre-provisioned runtime pairs, not a user's project count
or app-name allowance. Read current counts and freshness in the UI.

Operational summaries cover the configured scope and sample interval. Stored
history token totals are accumulated usage, not billing or instantaneous GPU
throughput. Missing or stale samples mean unknown, not zero. The dashboard does
not expose private prompts, passwords or unrestricted terminal command bodies.

Open the floating **User manual** button for the platform manual and guided
tour. Live gateway settings and returned application URLs take precedence over
examples in a saved guide. Do not invent features or claim a fresh test from a
saved report.
