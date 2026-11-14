"""Document processing stages, results, and workflow helpers.

Responsibilities:

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
- ``stages``: parsing, asset, governance, chunking, and deduplication functions.
- ``recovery``: retry cleanup, checkpoints, ingestion gates, and post-completion KG.
- ``process_document_flow``: the processing entry and ordered pipeline flow.

Workflow and stage functions import their actual helper owners directly.
``processor.py`` owns document persistence and image helpers and does not import
the workflow or stages. This package has no aggregate re-exports.
"""
