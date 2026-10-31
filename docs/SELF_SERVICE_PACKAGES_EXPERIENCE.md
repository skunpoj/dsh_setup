# Package self-service implementation lessons

The production workflow was qualified on isolated synthetic accounts before the main gateway handover. These engineering notes complement the clean user procedure; they are not instructions for users to weaken isolation.

| Trial or issue | Correction and verification |
|---|---|
| Python virtual environments created from the managed Jupyter environment did not automatically inherit ipykernel | A fixed bootstrap appends the managed Jupyter libraries after the new environment libraries. Real kernels imported the requested private package successfully. |
| CIFS rejected Python's default lib64 symlink | Precreate a real lib64 directory and use venv --copies. A real CIFS private environment installed, imported and survived synthetic process replacement. |
| Installer fsGroup could change permissions on a parent state PVC | Remove installer fsGroup; mount only the Jupyter subdirectory and preserve existing owner masks. A protected state sentinel outside the mount remained mode 0600 and unchanged. |
| A newly queued request sorting before active records could bypass a sequential concurrency counter | Count all active records before admitting new requests. The lexical-order regression passed in Linux. |
| A stale readiness record could belong to the previous controller | Bind readiness to current pod UID and a fresh status timestamp; serialize controllers using a durable lease. |
| Kubernetes client-side apply exceeded ConfigMap annotation size | Use server-side apply for the dedicated resources. Existing gateway source keys remain intact. |
| Windows could not launch a full-spec patch passed as one argument | Write a private patch file and use --patch-file. The first attempt never modified the gateway; the subsequent CAS patch and readback succeeded. |
| A tamper-test setup raced a terminating old controller | Wait for zero synthetic controller pods before mutation. The final real tampered-wheel case failed closed and created no environment. |
| Brief gateway handover response | One probe received HTTP 503 during replacement. Post-ready held-session, new request, terminal and kernel checks passed. Do not describe a handover as uninterrupted availability. |

The qualified main request completed in 26.94 seconds. The synthetic pair completed in 26.07 seconds. These measurements depend on wheel size, index/network service and cluster scheduling; they are not a latency guarantee. No inference or GPU throughput test was performed for this feature.

The release adds per-owner artifact storage and a gateway-only queue. It does not replace the older operator-reviewed shared Approved cache, change AD/datalake grants, share protected project files with Internet, or update existing user environments in place.
