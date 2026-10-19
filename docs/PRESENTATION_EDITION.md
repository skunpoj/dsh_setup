# Current English DSH/GPU presentation

**Current edition: expanded English, 44 slides, 19 October 2026.**

- [English narrated video](https://github.com/skunpoj/fastco-workspace/releases/download/technical-tutorials-20261019-r3e0b48f/DSH_GPU_Expanded_Technical_Guide_EN_20261019.mp4) — all 44 slides, English synthetic narration, 44 chapters and sentence-aligned subtitles. [VTT captions](https://github.com/skunpoj/fastco-workspace/releases/download/technical-tutorials-20261019-r3e0b48f/DSH_GPU_Expanded_Technical_Guide_EN_20261019.vtt), [SRT captions](https://github.com/skunpoj/fastco-workspace/releases/download/technical-tutorials-20261019-r3e0b48f/DSH_GPU_Expanded_Technical_Guide_EN_20261019.srt), [narration transcript](https://github.com/skunpoj/fastco-workspace/releases/download/technical-tutorials-20261019-r3e0b48f/DSH_GPU_Expanded_Technical_Guide_EN_20261019_narration.txt).
- [English HTML walkthrough](https://github.com/skunpoj/fastco-workspace/releases/download/technical-tutorials-20261019-r3e0b48f/DSH_GPU_Expanded_Technical_Guide_EN_20261019.html) — all 44 slide images, searchable slide text, explanations and pinned source links. Images and scripts are embedded; no CDN is required.
- [Matching editable PowerPoint](https://github.com/skunpoj/fastco-workspace/releases/download/technical-tutorials-20261019-r3e0b48f/DSH_GPU_Expanded_Technical_Guide_EN_20261019.pptx) — 44 slides with speaker notes and editable tables.

Downloads require authorized GitHub access to the private release. Public setup instructions remain in this repository.

## Content and source scope

Architecture, private user/environment boundaries, central persistence, offline packages, browser tools, admin applications, portable GPU setup and rollback, the 1M budget, admission/concurrency, prefill memory, caching, compaction and recorded tests.

The original presentation uses source `3e0b48f`. The expanded edition adds the later `af2897b` admin application controls: default eight names and one numeric override per user. Performance belongs to the recorded DeepSeek-V4.1-Flash-1017 qualification. This publication does not run a new model test or deploy a runtime.

The English HTML matches the expanded PPTX. Earlier 25-slide English and additional Thai editions remain unchanged as historical releases. A Thai 44-slide edition is not part of this deliverable. Source videos retain their separate frozen versions.

## Verified files

| Format | Bytes | SHA256 |
|---|---:|---|
| English HTML | 3918241 | `a8fda9f09058f82b3aab14441215a33318f91cef8927e889a186a7cfdd45ff5a` |
| English PPTX | 365232 | `f4ac14da9d2d533de9ad2bf0962d29f5d38337c84305952888631081ee448252` |

All 44 HTML slide transcripts match the PPTX. All embedded images decoded; search, navigation and mobile layout passed browser checks. Both published files passed authenticated full-download byte/hash comparisons. Pinned source and download links are checked separately from runtime behavior.

## English video edition

The video follows the exact 44 final PPTX slide images and corresponding English HTML order. Narration uses the displayed default eight-app limit and 172.52 combined cohort tokens/sec, correcting stale wording in two inherited speaker notes. These are recorded measurements, not new benchmarks. Original long source walkthroughs and earlier 25-slide editions remain unchanged.

Verification covers complete media decoding, non-silent English speech on every slide, sentence-aligned caption intervals, all 44 decoded slide images, browser playback and seeking, and authenticated full-download hashes. Synthetic narration is disclosed; these automated checks are not a human listening review.

Video: **26m 52s**, **34,032,096 bytes**, SHA256 `60ce32d146a7104064b530595fde983254e0a81e459b778ab19d316d34eaf835`. English captions: **264 sentence-aligned cues**; chapters: **44**.

Audio is encoded once from a continuous soundtrack. Per-segment AAC concatenation was rejected because encoder delay accumulated. Final encoded-speech alignment samples passed on all 44 slides, with less than one millisecond offset; caption text matches all 264 narration sentences.
