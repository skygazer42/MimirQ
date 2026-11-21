"""Document processing stages, results, and workflow helpers.

Responsibilities:

- ``common``: shared metadata writes, gate outcomes, logger and redaction/path
  constants used by the processor and stage helpers.
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
- ``stages``: parsing, asset, governance, chunking, and deduplication functions.
- ``recovery``: retry cleanup, checkpoints, ingestion gates, and post-completion KG.

The processing entry and ordered workflow live in ``app.rag.ingestion.pipeline``.
Workflow and stage functions import their actual helper owners directly.
``processor.py`` owns document persistence and image helpers and does not import
the workflow or stages. This package has no aggregate re-exports.
"""
