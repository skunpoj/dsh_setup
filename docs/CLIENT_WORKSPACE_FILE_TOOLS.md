# Managed client workspace file tools

The Kilo and TrueForge corrections passed actual AI acceptance on 21 October
2026 using two fresh isolated accounts, each in No Internet and Internet modes.
All four clients loaded the shared guide and read and wrote a hidden test value:
16 client turns in total. The value and guide answers were not supplied in the
user prompt. Tool events, final answers and saved file contents were checked.

## Kilo

The operator policy allows project file edits while continuing to deny
`external_directory`. Other actions still use their existing permission policy;
this does not enable `--auto` or blanket shell approvals. The managed launcher
requires coding sessions to start inside `/workspace` and refuses the `--dir`
override. Users choose their project by changing directory before launching Kilo.
The internal provider, private state locations and loaded guide remain unchanged.

## TrueForge

The pinned standalone runtime receives three local tools in every agent
definition: `read_file`, `write_file` and `list_directory`. They operate in that
user/environment's `/workspace`, not a remote sandbox. No extra MCP listener,
remote service, shell execution or model credential is exposed to the tools.

The Linux broker traverses directories using descriptors and `O_NOFOLLOW`.
It refuses external paths, traversal, symlink components, hardlinked files and
special files. Reads and writes accept UTF-8 text up to 1 MiB; listings are
bounded to 2,000 entries. File parents must already exist. Replacement is atomic.
These tools do not provide command execution, binary-file editing or deletion.

The adapter validates the pinned upstream resolver before patching both CJS and
ESM variants. Image builds install the adapter after the shared guide. An
immutable ConfigMap overlay supports qualification on the existing pinned image.

## Startup and preservation

The overlay removes only the exact duplicate guide `postStart` hook: the pinned
startup script already installs the guide after copying the initial seed. The
concurrent duplicate could race that copy on an empty state directory. Unknown
hooks and conflicting policy mounts are refused. Storage, image, user mappings,
client histories and other services are preserved.

## Verification and rollout boundary

Linux tests verified real read/write, traversal and external-path denial,
symlink/hardlink/FIFO refusal, file-size bounds, invalid UTF-8 and missing parents.
Both native TrueForge module variants exercised their real ToolSet interface.
Kilo's effective policy and non-workspace launch refusal were checked in all four
fresh contexts. Actual completed DSH histories had four valid own-read controls;
eight cross-user and four cross-mode requests were denied, including forged
identity headers. This does not certify every client's separate history API.

The isolated fixtures and their restricted model key were removed. No active
user workspace was restarted. Source fixes and future-template manifests are
prepared; Main activation is a separate operation. Existing active users and
already provisioned spare workers do not acquire new mounts automatically.
Only proven unassigned spares may be upgraded without affecting an active user;
account-to-slot ownership, data/history checks and rollback must precede that work.

The operator evidence bundle retains original probe output. TrueForge tool
arguments arrive as stream fragments and must be reconstructed by message ID and
tool index; an initial empty argument fragment is not a complete invocation.
