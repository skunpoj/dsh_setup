# Existing-workspace client compatibility layer

This optional layer enables the qualified Kilo editing policy and TrueForge
workspace file tools for **new client processes**, without replacing a workspace
pod, restarting DSH/Jupyter, signalling an existing client, or moving its history.
It is a compatibility bridge, not an immutable image upgrade or security boundary.

## What changes

An operator stages a small, hash-qualified release under
`/state/.dsh-managed-clients/releases/<release>` and activates its `current` link.
The installer appends one bounded block to the owner's existing `.bashrc`, keeping
the original bytes and a private recovery copy. New interactive Bash terminals
then resolve `kilo`, `kilocode` and `trueforge` to that release.

An already-open terminal may explicitly load the same functions:

```sh
. /state/.dsh-managed-clients/current/activate.sh
```

This changes subsequent commands in that shell. It does not change a running
Kilo turn or TrueForge server. An existing TrueForge process retains its loaded
SDK until its owner finishes and next launches it. Do not start a competing server
on a port already used by that owner's client.

Noninteractive commands, absolute image executable paths and other shells do not
automatically use a Bash function. They can explicitly use the release launcher.
Do not claim that every invocation path has been replaced.

## Preserved behavior and boundaries

- Kilo keeps `/state/kilo/{data,state,cache}`, the internal model/provider policy
  and external-directory denial. The qualified launcher confines editing to a
  project under `/workspace` and rejects policy-changing launch options.
- TrueForge keeps `/state/trueforge`, the existing managed provider store,
  credential file, network controls and port. Its new process registers a Node
  loader for only two exact, hash-qualified SDK modules. Other agents and modules
  receive no global `NODE_OPTIONS` change.
- The existing local broker confines reads, writes and listings to the private
  `/workspace`, with bounded UTF-8 data and symlink/hardlink protections.
- Image files and read-only Kubernetes mounts are not edited. Deployment
  templates, accounts, credentials and gateway routes are not changed by this
  installer. `/state` is private to the existing user/environment mount.

The files are writable by their owner. Provider authorization and network
isolation remain separately enforced; this layer does not strengthen those
controls or authorize access to another user's data.

## Qualification and activation gates

Before an existing-user installation, verify the actual source hashes, Node
version, profile ownership/type, running process identities and history snapshot.
Qualify both old-image environments using real SDK file operations, Linux
file-boundary tests, a full restore/reapply rehearsal and actual model-selected
file-tool calls during a coordinated inference window.

`install_live_client_layer.py` accepts an operator-generated bundle and the
preflight profile/source hashes on stdin. It refuses unexpected source bytes,
foreign activation pointers, symlinked/hardlinked profiles, FIFOs, oversized files
and changes detected during reads. Its append preserves existing profile bytes;
this is not a claim of absolute atomicity against an uncooperative owner editing
the same file concurrently. Verify saved bytes and actual new-shell behavior.

Rollback uses the returned private recovery path and refuses to overwrite a
profile edited after installation. It restores the previous pointer/profile only
when ownership and recorded hashes still match. Release files remain available
to processes that already loaded them; rollback never kills those processes.

## Workspace replacement

The release and recovery copies persist in `/state`. Without the registered
startup plugin, a container with an ephemeral HOME or `.bashrc` can require the
explicit activation command after a full pod replacement. With the qualified
persistent native DSH startup plugin registered, normal replacement restores
Bash activation automatically. Instances with a persistent complete HOME retain
the activation directly. Full image/template adoption remains a separate step.
Adopt the full immutable tools overlay at the next separately authorized safe
maintenance window. Do not repair boot scripts, change an immutable ConfigMap,
or roll a deployment merely to make this temporary layer permanent.

## Automatic activation after worker replacement

For existing-workspace deployments, the optional persistent native DSH startup plugin restores the qualified Bash activation block after normal replacement. Instances with a persistent complete HOME retain that activation directly. This restores compatibility for newly launched clients; it does not start agents or resume an in-memory process. Existing running clients keep their loaded code. New images still require their own qualification. See [automatic activation setup and recovery](AUTOMATIC_CLIENT_ACTIVATION.md).
