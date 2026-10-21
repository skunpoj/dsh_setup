# GPU, LiteLLM and local inference setup

Start with the [complete Kubernetes installation](../docs/INSTALL.md). It covers
the runtime image, local configuration, storage, model-weight download, GPU
deployment, internal LiteLLM, private environments, DNS/TLS and verification.
Use [config.example.yaml](../config.example.yaml) for portable settings and the
[templates](../templates) directory for the rendered workload definitions.

Read [1M context operation](../docs/CONTEXT_1M.md) before testing long requests,
then follow the [validation](../docs/VALIDATION.md) and
[acceptance](../docs/ACCEPTANCE.md) checks. Validate the actual hardware, runtime,
memory headroom and concurrent workload; a configured context ceiling is not a
performance guarantee.

For automatic private-workspace provisioning, integrate the
[signup pressure gate](../docs/SIGNUP_CAPACITY.md) with your trusted collector.

This stable guide link points to the current sanitized installation reference.
Supply site-specific endpoints, storage, credentials and certificates privately;
do not publish an operational deployment export or private history here.
