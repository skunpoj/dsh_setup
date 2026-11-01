# GPU peer access: read, change, verify, restore

This is a planned administrator-controlled procedure, not evidence of a completed
host change. No automatic boot edit, PCI register write, reboot or engine switch
is performed by this repository. The host and serving stack are shared resources.

## Source map

- Setup, profiles, context-forwarder and SGLang templates: this `dsh_setup` repository.
- SGLang + DSpark rollback: `gpu-stack/profiles/sglang-dspark-rollback.json` and
  `gpu-stack/templates/model.yaml` with its scheduler/indexer gates.
- Current DeepInfer + DSpark: `gpu-stack/profiles/deepinfer-dspark-nccl-current.json`.
- After-change DeepInfer + DSpark trial: `gpu-stack/profiles/deepinfer-dspark-deepep-proposed.json`.
- Engine source: `https://github.com/skunpoj/DeepInfer`, reference commit
  `b4df8657412de7ea8bab8b442c2b8c68f5c1068a`. Selected source matches do not
  resolve the known tokenizer difference or compiled artifact provenance.
- Actual private overlays/builds still originate from the internal Azure
  operational repository. Public profiles do not claim CI/CD cutover is complete.

## 1. Read-only checks and recovery preparation

Record kernel, effective command line, GPU topology, IOMMU group type for every
GPU, upstream bridge ACS controls, actual firmware profile, driver bindings,
VFIO/VM/device-assignment users and active VFs. Zero VFs on GPUs is not evidence
that every other device is unused. Protect DMA/device isolation even on bare metal.

```sh
uname -r
cat /proc/cmdline
cat /sys/kernel/iommu_groups/*/type | sort | uniq -c
nvidia-smi topo -m
lspci -t
lspci -vv
grubby --default-kernel
grubby --info=ALL
```

Capture exact current workload specifications, image digests, mounted-source and
compiled-library hashes, model hashes, service routing and state-preservation
checks privately. Confirm independent console access and a working recovery boot
entry. Set an operator and restoration deadline. Cordon does not stop existing
pods; coordinate drain/eviction, local storage and disruption budgets explicitly.

## 2. Controlled OS trial

Only after the administrator approves the isolation trade-off and maintenance
window, use the installed RHEL boot-management procedure to trial `iommu=pt` on
a selected kernel entry. Keep a recovery entry unchanged. The generic upstream
`iommu.passthrough=1` parameter has related intent, but its exact availability and
device-policy interaction on the installed enterprise kernel must be verified.

Do not blindly edit `/etc/default/grub`, `/etc/kernel/cmdline` and BLS files all at
once. Inspect `/boot/loader/entries/` and the host's kernel-install/managed boot
configuration; after the controlled reboot, `/proc/cmdline` and actual GPU domain
types determine whether the intended mode took effect. A file edit is not proof.

## 3. Integrity before speed

Reproduce direct peer-copy checks in every required GPU direction using multiple
sizes and nonzero seeded patterns; validate destination bytes. A positive CUDA
capability flag or a bandwidth number without correctness is insufficient.
NVIDIA's simpleP2P checks correctness; nvbandwidth can measure qualified bandwidth.
Then qualify DeepEP dispatch/combine and model correctness. Preserve failed
directions and error logs. Do not infer a full four-GPU NVLink domain from two
NVLink pairs.

Only if those tests pass, inspect the proposed profile and change EP exchange to
`deepep` in a separate controlled trial. Keep CP on NCCL, GIN disabled and host-UVA
Engram unchanged. Qualify cancellation, concurrent requests, source identity and
the full authenticated LiteLLM/DSH request path before claiming application recovery.

## 4. ACS / firmware escalation

If required integrity checks still fail, read the exact GPU upstream bridge ACS
bits and consult hardware support. Do not clear all ACS registers system-wide or
assume IOMMU presence proves every redirect bit is enabled. Any scoped software
ACS trial needs a saved bit value, explicit device ownership and rollback.
The HPE Graphic Processing workload profile is a bundled firmware preset; review
the exact processor-generation dependency table and current BIOS values first.
It is not a vendor certification of this engine or a requirement to disable all
virtualization features together.

## 5. Restore and accept

On failed boot, lost devices, copy mismatch, model error or deadline expiry,
restore the known working boot entry and saved serving specification. Restore
DeepInfer/NCCL first or the separately retained SGLang rollback as agreed; never
run both four-GPU engines concurrently. Verify the actual service endpoint,
mounted source, answer correctness, authenticated request path and unchanged
workspace/history/storage state. A 1500-second operational watchdog setting is
not a demonstrated host-reboot RTO or a recovery guarantee.

## Vendor references and limits

- NVIDIA GPU/P2P guidance: https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/troubleshooting/gpu_troubleshooting.html
- CUDA bare-metal IOMMU caveat: https://docs.nvidia.com/cuda/cuda-programming-guide/03-advanced/multi-gpu-systems.html#host-iommu-hardware-pci-access-control-services-and-vms
- Kernel parameters: https://www.kernel.org/doc/html/latest/admin-guide/kernel-parameters.html
- RHEL boot management: https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/managing_monitoring_and_updating_the_kernel/configuring-kernel-command-line-parameters_managing-monitoring-and-updating-the-kernel
- HPE processor-specific profile table: https://support.hpe.com/hpesc/public/docDisplay?docId=sd00003788en_us&page=GUID-0046C58A-060D-4089-9B21-9AFEC16D7F74.html

These references explain mechanisms and available controls. They do not prove
IOMMU is the isolated cause here, certify `iommu=pt` for every HPE/NVIDIA stack,
or establish that changing a preset preserves the host's required isolation.
