# Vendored ttyd runtime

`ttyd` 1.7.7-40e79c7 for Linux x86_64 is stored here so the approved Azure build does not depend on GitHub network access.

- Upstream project: https://github.com/tsl0922/ttyd
- Runtime source: verified current DSH Production binary
- SHA-256: `8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55`

The Docker build checks this digest and the pipeline executes `ttyd --version` from the built image.
