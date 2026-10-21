# Qualified normal-site integration candidate

The ten-file candidate includes the current Main signup helper and a dedicated resolver for external proxy requests. It does not change the gateway system resolver or any worker DNS settings. All returned addresses still pass the existing private allowlist or public-only checks and strict TLS verification.

The exact candidate passed 87 Node tests plus three verifier-race cases. The actual gateway fixture enabled the dedicated resolver. The additional five resolver tests cover mixed private answers, configuration validation, unavailable families and timeouts without fallback.

Main activation and old gateway retirement are separate reviewed operations. Qualification is not evidence that those operations are complete. No credentials, private plans, cookie jars or auth backups belong in this repository.
