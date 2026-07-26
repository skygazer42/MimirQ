"""Support modules for the document processor service.

Mechanical split of ``app/parsing/processors/processor.py`` to keep it at a
maintainable size. Responsibilities:

- ``common``: shared logger plus redaction/path constants used by the service
  and the split-out helpers/stages.
- ``results``: stage result dataclasses (``ParseResult``, ``InlineAssetResult``,
  ``GovernanceResult``, ``ChunkingResult``, ``ChunkDedupResult``,
  ``ChunkAssetResult``, ``ChunkAssetOptions``, ``ChunkPostprocessStats``,
  ``IndexResult``) and ``DocumentCancelledError``.
- ``parse_io``: logical-source metadata attachment, markdown join helpers and
  parse-cache (de)serialization of parsed documents.
- ``assets``: asset reference collection (img_ids / artifact dirs),
  inline-asset audit patching and chunk asset detection.
- ``quality``: seal summaries, OCR quality summaries and governance quality
  metrics/statistics.
- ``chunk_postprocess``: chunk truncation, uniform sampling, page-offset
  rebasing and small-chunk merging.
- ``stages``: pipeline stage classes (``ParsingStage`` ... ``ChunkAssetStage``).

Import direction: submodules must NEVER import
``app.parsing.processors.processor`` (circular import). Stage classes that need
the service receive it through ``__init__(self, service)`` and use it at call
time; anything tests monkeypatch on the ``processor`` module namespace (e.g.
``Indexer``) must keep its call sites in ``processor.py``.

This package does not re-export names; ``app.parsing.processors.processor``
re-imports everything so its public surface stays unchanged.
"""
