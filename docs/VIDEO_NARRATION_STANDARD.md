# Video narration and captions

English SMP and DSH instructional videos use **Google Gemini TTS, Fola** with a calm, conversational teaching style. Use the same voice for course chapters, feature demonstrations and short update clips. Local operating-system voices and other Google voices are not automatic substitutes.

## Prepare narration

Keep the reviewed teaching script and its source revision together. Check that the script contains no passwords, tokens, private keys or protected datasets before sending it to the speech provider. Use the approved project authentication in place; do not copy credentials into a video bundle or a public repository.

Record a SHA-256 hash of each script. Reuse an existing audio result only when its script hash, provider, model, voice and file hash all match. Preserve original historical editions rather than overwriting their evidence.

## Generate audio

Use finite batches with a request count, output budget, deadline and concurrency limit. Save the request intent before calling the provider and save the returned audio and provider receipt. If a connection fails, reconcile the recorded outcome before making another generation request. A download retry must not silently become another paid generation.

## Rebuild captions and navigation

Align captions against the actual generated speech. Recalculate chapter boundaries and function-seek positions whenever audio duration changes. Preserve the complete reviewed script, use readable plain-text WebVTT cues, and check cue ordering and bounds. Listen to representative passages, including technical names and numbers; inspect any substantial difference between recognized speech and the script.

## Verify and publish

Fully decode every new video. Check duration, audio presence, caption loading, playback, seeking, category filters and reference links. Preserve file/function counts with their source revision and counting scope. Verify both local output and actual published content.

Publish a versioned edition, retain the previous release for recovery, and preserve unrelated manual assets, user files and histories. Public repository copies contain portable examples and sanitized configuration. A source commit, successful build or available file alone does not establish that the new media is live.
