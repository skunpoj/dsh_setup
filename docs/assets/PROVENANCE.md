# Diagram asset provenance

The report reuses the diagram-control implementation from SMP EDA `smp_eda/docs/ARCHITECTURE_AND_DATAFLOW.html`. Changes: preserve the initial SVG viewBox through repeat initialization and remove the cloned viewport transform for uncropped SVG/PNG exports. Report initialization uses strict Mermaid security and SVG text labels; scripts are embedded for offline use.

Pinned renderer distributions:
- https://cdn.jsdelivr.net/npm/mermaid@10.8.0/dist/mermaid.min.js
- https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js

Original distribution copyright/license notices are retained in their bundled sources. Do not upgrade renderer assets implicitly; rebuild and run the document QA script after any change.

Rebuild with `node scripts/build_security_walkthrough.mjs`. The generator imports `marked` from `DSH_DOC_NODE_MODULES` or the configured bundled runtime directory. Verify with `node scripts/test_security_walkthrough.mjs`; this uses the same Node module root and installed Microsoft Edge. Override `DSH_DOC_QA_OUTPUT` for test artifacts.
