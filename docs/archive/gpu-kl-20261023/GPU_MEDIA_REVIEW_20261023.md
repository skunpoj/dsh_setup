# GPU qualification media — review edition, 23 October 2026

[Detailed results and derivations](GPU_NEAR1M_COMPACTION_20261023.html) ·
[Captioned code-and-results video](GPU_Qualification_20261023.html)

K and L were rejected at the zero-allocation-retry gate during 384K preparation,
with one retry on each GPU and zero recorded OOMs. Neither completed 384K,
near-1M generation or automatic compaction. This is not a proof that 1M is impossible.

L's completed 128K test generated 617 tokens in 57.588 seconds (10.71 output
tokens/sec whole-turn), with an 8.362-second stream window (73.79 tokens/sec).
Its four overlapping 120-token replies produced 117.30 tokens/sec combined
across the client wall window. These are bounded application measurements.
The generated guide also added unsupported details; timings do not establish
perfect answer accuracy.

The baseline was restored and an exact native recovery reply was checked.
The original 582 qualification files and 291 histories were retained; added
histories were preserved. Test keys were revoked. The accompanying report
records preservation checks separately from workload acceptance.

The video is a silent, captioned 108-second illustration of actual gate code,
recorded results and recovery. It is not live-screen capture. Its MP4 was
decoded in full; native PowerPoint and browser video playback were not tested
in this media review. Live manuals and application deployments were not promoted.

Native companions: [MP4](videos/GPU_Qualification_20261023.mp4),
[English captions](videos/GPU_Qualification_20261023.vtt),
[storyboard](GPU_Qualification_20261023.storyboard.json).
