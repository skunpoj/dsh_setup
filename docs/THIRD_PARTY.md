# Third-party components

The runtime installs DeepSeek Harness, Claude Code and TrueForge at the versions
declared in the Dockerfile. Their licenses and service terms apply separately.
The SGLang image, LiteLLM image, PostgreSQL image and model weights likewise keep
their upstream licenses. This repository does not relicense those components or
grant model-access rights.

The bundled `ttyd` artifact and integrity verification are documented in
`vendor/README.md`; retain its upstream provenance. Review redistribution rights,
accepted model terms and the exact software bill of materials before publishing
your own images or offering subscriptions. Do not infer commercial permission
merely because software or a model can be downloaded.

The optional gateway LDAP client is `ldapts` 9.2.0 (MIT), vendored with its license and package provenance under `vendor/ldapts/`. Its digest is checked before loading and when building the runtime; no LDAP package is downloaded during login.
