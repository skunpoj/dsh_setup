# Capacity, usage and shared client guidance

## What “new-user slots available” means

Successful signup enables your private **No Internet / Internal** workspace immediately, without individual administrator approval. **Only Internet access requires a separate administrator grant.** Account capacity controls are not an approval queue.

The Create account page displays **N new-user slots available**. N is read from
the gateway's current account assignments, not written as a fixed number in the
page. A slot is a pre-provisioned pair of private execution environments for one
new account. It is not a user's project folder count, app-name allowance or GPU
request allowance. Internet access still requires administrator approval.

The count updates every 15 seconds while the page is visible and when returning
to the tab. If it cannot refresh, the page shows capacity unavailable. Account
creation always rechecks allocation on the server; two people viewing the same
last slot cannot both claim it. An assigned slot stays reserved when its account
is disabled, preserving private files and history. Administrators set a warm-spare target (there is no account limit) in
**Account capacity and automatic provisioning**. A separate provisioner replenishes
ready private pairs automatically; the default target is two spares. Existing
extra spares and assigned storage are retained. Remaining slots do not promise worker health;
runtime availability is shown separately in the admin dashboard.

See [automatic account capacity, architecture and setup](AUTOMATIC_ACCOUNT_CAPACITY.md)
for the admin workflow, preparation checks and rollback.

## Admin capacity and monitoring

Open **Admin overview** to see:

| View | Meaning |
| --- | --- |
| New-user slots | Remaining slots, assigned/prepared slots and enabled/disabled accounts |
| Capacity controls | Desired warm spares (no account limit), automatic replenishment and timestamped provisioner status |
| Browser sessions | Sessions authenticated through the main gateway, split by environment |
| DSH activity | Running DSH agents, queued messages, stored conversations, turns and model steps |
| Token usage | Accumulated input/output tokens and separately labelled recorded/recent decode rates |
| Runtime coverage | Responding/configured private runtimes; incomplete coverage is explicit |
| Storage | Per-user/environment workspace and durable file sizes, local state used/capacity, collection time and partial-scan status |
| Applications | Names, ports, enabled state and one administrator-controlled allowance per account |
| Managed services | Administrator-controlled startup and status when the service supervisor is deployed |
| Access audit | Central access records and projection freshness |

Capacity and DSH activity refresh every 15 seconds while the dashboard is visible.
Unavailable activity clears the numeric cards instead of displaying old numbers
as current. A storage collection older than five minutes is marked; the Refresh
button does not run a new storage scan. The operator updates storage observations
with `scripts/collect_admin_capacity.py`. Saved infrastructure/model observations
retain their own timestamps.

These rates are DSH conversation measurements, not complete Claude Code/Kilo/
TrueForge usage accounting or instantaneous GPU telemetry. Imported histories
can increase accumulated token totals; the recent-rate calculation excludes
old imported conversations. Missing measurements display unknown rather than zero.

## Platform context in all four clients

The [shared platform guide](SHARED_PLATFORM_GUIDE.md) supplies DSH, Claude Code,
Kilo and TrueForge with the same platform concepts. It explains private accounts,
environments, persistent files, app URLs/ports/limits, notebooks, dependencies
and managed inference. The clients do not share conversation memory. Live
account/app settings remain authoritative when an administrator changes them.

Use DSH as the main web workspace; choose Web Terminal or JupyterLab on login when
needed. DSH remains the default landing page. **My apps** registers a name and
port, while the service-startup controls manage a process separately.
