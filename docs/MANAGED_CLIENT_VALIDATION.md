# Validate managed coding clients

Use two disposable accounts, each with separate No Internet and Internet runtimes. Grant Internet only to those test accounts through the normal administrator flow. Do not alter existing users or increase account limits for testing.

For each of the four account/environment contexts, run DSH, Claude Code, Kilo Code and TrueForge in sequence:

1. Put a random value in a workspace file without including it in the prompt.
2. Ask the client to read its installed workspace guide and the file, then write only that value into a new file.
3. Inspect the actual tool events, saved assistant answer and output file. Check guide facts against the installed guide and compare file contents independently.
4. Use the next client to read the previous client's output. Shared files should be visible within the same account/environment without a copy loop; working-directory selection remains explicit.
5. Confirm each context can read its own native DSH history. Attempt cross-user and cross-environment history access, including forged identity headers, and require denial.
6. Archive and hash-check only the disposable users' files/history, revoke their sessions and credentials, remove their accounts/routes, and verify original account records, limits, history hashes and worker identities against the pre-test snapshot.

This matrix contains 16 ordinary client turns. It is separate from near-1M context, sustained throughput, restart persistence and network-egress acceptance. A configured context ceiling or a successful small reply does not prove those additional cases. Record deployment-specific results privately rather than publishing accounts, endpoints, tokens or transcripts.
