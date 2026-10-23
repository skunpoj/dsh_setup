# Allocator telemetry qualification helpers

These source files support reproducible qualification of a pinned SGLang runtime. They are not an installer or an instruction to change a running service.

## Run the CPU checks

Use Python 3.10 or later. From this directory:

```sh
python -m unittest discover -s . -p 'test_*.py'
```

The 32 checks use fake CUDA interfaces and temporary configuration files. They do not load model weights, contact a cluster, allocate GPU memory or run inference. Include `allocator_observer.original.py`: the foreground-equivalence test compares against that preserved source.

## Periodic observations

`allocator_observer.py` preserves its existing foreground observer. The additional periodic sampler is disabled by default. A qualification operator can opt in with `DSH_QUALIFICATION_PERIODIC_READONLY_COUNTERS=1`; the existing native allocator observer must also be enabled and successfully initialized first.

The added sampler reads `memory_stats` for the explicitly selected device every five seconds. It does not launch a tensor operation, synchronize, reset counters, clear a cache or change a memory fraction. This statement describes the added sampler: the preserved foreground observer already contains the original memory-fraction behavior.

Each observation records its start and finish time and the process PID/start ticks. Missing required counters, failed reads or failed logging stop that sampler; missing measurements are not converted into zeros. Qualification must compare the same process before and after the last tested operation on all four ranks. An observation that ends before that operation cannot establish full-window coverage.

## Source-equivalence proof

`telemetry_equivalence.verify(old_sources, new_sources, proof_path)` returns `None` for identical valid source maps. Otherwise it permits only the observer source change under a strictly verified proof. It checks artifact hashes, immutable ConfigMaps and the exact candidate specification. The only allowed specification changes are the allocator ConfigMap reference, the opt-in flag and the read-only telemetry annotation. Model, image, kernel, memory, graph and other configuration changes are rejected.

The CPU tests exercise both accepted and rejected changes. Source equivalence does not prove runtime correctness, completed compaction, model quality or deployment acceptance. Those require the actual native conversation, persisted files, timestamps, counter observations and recovery readbacks described in the performance report.

Raw account data, conversations, site manifests, credentials and user-state snapshots are deliberately excluded from this directory.
