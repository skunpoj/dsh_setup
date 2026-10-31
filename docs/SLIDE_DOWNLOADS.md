# PowerPoint companion downloads (retired)

Retired on 30 Oct 2026. The manual no longer serves `.pptx` files: the bounded slide download service (`scripts/slide_downloads.py`), its manifest and its `/manual/downloads/*.pptx` ingress paths are removed. The HTML guide and the archived HTML companion pages are the delivery format.

Decks that belong to this repository (for example in `docs/presentations/`) are still linked directly from the documentation; they were never served by this service.

To bring downloads back, restore `scripts/slide_downloads.py` and `tests/test_slide_downloads.py` from Git history before this note, add a manifest of reviewed decks with their byte counts and SHA-256, and re-add the page links in the same manual edition.
