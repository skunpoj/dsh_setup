# Admin usage and storage overview

Administrators can use `/admin` to manage accounts and review numeric activity summaries for the main service's configured private runtimes. Account permissions, Internet grants, private routing and conversation ownership remain separate from monitoring.

![DSH usage panel with synthetic demonstration counters](images/platform/admin-usage-illustration.png)

The illustration uses synthetic accounts and counters to explain the layout; it is not a live user's activity record.

## Accounts and Internet approval

Users select **Create account** on the login page. Signup assigns an exclusive qualified runtime pair and denies Internet by default. Open **User management** to create an account from available capacity, enable or disable access, sign out sessions, or select **Allow Internet** / **Disable Internet**. Reload the page to pick up new registrations. The usage collector includes assigned signup pairs alongside explicitly configured accounts; unused pairs are capacity, not user activity.

Disabling an account retains its assignment, files and histories. Internet revocation invalidates gateway sessions and closes tracked connections; it does not terminate detached tools already running inside a runtime. An administrator cannot select arbitrary backend addresses or self-assign the admin role through the signup form. Operators replenish empty pairs; the gateway has no Kubernetes management token. See the [signup and approval procedure](SELF_SERVICE_SIGNUP.html).

## Usage panels

| Panel | Meaning |
|---|---|
| Stored conversations | Native DSH session records, including blank, imported and copied sessions |
| Running DSH agents | Sessions whose native `running` flag is true; detached terminal processes are separate |
| Queued messages | Messages in the next-turn and next-step inboxes |
| Recorded turns | Turn counters retained by DSH |
| LLM steps | Recorded model steps, including tool continuations; separate from browser logins |
| Accumulated input tokens | Uncached input plus cache-read and cache-write token counters in stored DSH sessions |
| Accumulated output tokens | Output counters retained in those sessions |
| Recorded decode tokens/sec | Sum of recorded decode tokens divided by recorded decode time; excludes preparation and tool time |
| Recent conversation decode tokens/sec | Newly recorded decode tokens divided by their recorded decode time between complete samples |
| Recent output tokens/sec | Output-counter changes between two complete samples, divided by elapsed time |

The panel refreshes every 15 seconds while visible. Concurrent admin viewers share the same short-lived sample. It displays the available/configured runtime count and the number of sessions with usable token records. A failed worker remains unavailable rather than being presented as an empty workspace. The first recent-rate sample is unknown; incomplete coverage, removed histories or counter resets also invalidate that interval. Importing an old history does not turn its accumulated output into new tokens/sec.

Step counts follow DSH's step lifecycle: completed, failed and cancelled steps are counted. A retried step can contain several HTTP attempts, so this counter is not a count of every backend request. Duration counters preserve the fractional milliseconds supported by the installed SDK.

Stored totals describe retained history, including copies. They are not a deduplicated inference-billing ledger. Claude Code or TrueForge sessions launched independently in a terminal have their own accounting; these DSH application counters do not silently claim to include them.

## Storage panels

Storage observations report workspace file lengths, durable session/attachment/state file lengths, and local state filesystem usage/capacity separately. Partial scans are marked. File-size views may overlap, so they must not be added together and presented as physical disk allocation or a user quota. Shared CIFS server capacity is not a private user's storage quota.

Local state directories can be absent until first use and then contain zero files. The collector uses the actual pod's explicit state mounts to distinguish these optional directories from required mounted roots; a missing required root remains incomplete.

An operator with existing Kubernetes access can collect a new observation:

```powershell
python .\scripts\collect_admin_capacity.py --namespace YOUR_NAMESPACE --output .\private-capacity-observation.json --publish
```

Use a new output filename each time to retain earlier observations. The collector reads only file metadata from fixed workspace and state roots, never follows symlinks, limits each scan and performs at most four worker probes concurrently. It publishes a numeric projection to the gateway's protected audit volume and verifies the saved hash. It grants no new cluster role and restarts no workload. Storage freshness is shown separately from live usage sampling; clicking Refresh does not launch an operator command.

## Access and privacy

Only the gateway's configured administrator role can access the telemetry endpoint. Browser headers cannot elevate an ordinary user. The collector uses operator-provisioned destinations and launch tokens; request parameters cannot select a different host or filesystem path. Requests have time and response-size limits.

The response contains numeric usage summaries and existing provisioned account/environment names. Conversation titles, prompts, answers, tool contents, file paths, cookies and credentials are not returned. Counters are operational summaries reported by the application, not a tamper-proof command or remote-job ledger. Datalake identities and permissions are unchanged.

Internet permission grants and revocations are included in the central access audit alongside the existing account events.

## Verification

```powershell
node .\tests\test_admin_telemetry.js
node .\tests\test_admin_dashboard.js
node .\tests\test_admin_users.js
```

These checks cover the native HTTP summary protocol, numeric projection, private-field exclusion, unavailable workers, caching, rate arithmetic, imported histories, counter resets, role enforcement, read-only methods and browser rendering. Deployment verification separately checks the mounted gateway source, current account records and actual private-runtime responses.
