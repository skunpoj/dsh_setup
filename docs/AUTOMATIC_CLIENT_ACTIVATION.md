# Automatic activation after workspace replacement

The optional compatibility layer can register a small native DSH startup plugin in the existing persistent web profile. At the next normal DSH startup it validates the retained release, installed module/policy fingerprints, private file ownership/type and profile state, then restores the bounded Bash activation block only when missing. It never restarts a workspace or an already-running client.

The registration uses the installed native root-insert contract with an explicit empty-string root selector. The actual child plugin has a nonempty, fixed ID. This satisfies both native patch composition and the deployed profile upgrader's string/unique-ID checks. Registration refuses an occupied root selector, conflicting plugin identity, unsupported YAML tags and prototype-like IDs; preserves existing profile bytes as an exact prefix; saves a private original; and refuses detected concurrent edits. Re-registration recognises the same native entry after standard YAML formatting without adding a duplicate.

Boot assets are source-pinned and private. The runtime checks their type, owner, link count, size and hash. The qualified launch layer continues to confine file tools and Kilo edits to the private workspace and uses the existing provider/state paths. The retained policy includes Kilo's schema metadata because otherwise the native CLI adds it and changes the pinned file during normal session commands. The startup helper rejects altered releases rather than weakening fingerprints.

An integrity or profile error records a bounded negative boot receipt and leaves DSH available. No credentials or profile content are written to that receipt. This is owner-writable compatibility code, not a privilege or network security boundary. A corrupt component must be repaired from qualified source; a readiness flag alone does not establish successful activation.

Running clients keep their already-loaded code. New Bash terminals select the retained current launchers. Other shells, absolute old executable paths and noninteractive invocations are outside the Bash-function scope. Full immutable image adoption is separate.

Legacy runtimes whose entire HOME already persists do not need a new native plugin entry: their Bash profile and retained release survive together. Verify the actual login profile sources Bash configuration and qualify that distinct replacement path.

Use `build_live_client_autostart.py` to construct the boot package from a qualified launch bundle and reviewed source. The profile installer is an operator tool; it performs no inference and does not change account mappings, templates, deployment specifications, supervisor controls or history. Guarded rollback restores the exact saved profile only while its recorded hash still matches; owner edits or native rewriting require reconciliation rather than forced overwrite. Release/boot files are retained for already-loaded clients.

Acceptance requires actual native startup and whole-pod replacement in disposable persistent storage, positive and damaged-asset recovery checks, actual fresh-shell client/file-tool behavior, and retained conversation content. Build checks or a live process alone do not establish those outcomes. Keep original failure evidence and separate candidate qualification from live adoption.
