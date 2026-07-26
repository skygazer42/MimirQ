"""Retrieval orchestration helper submodules.

Split out of ``app.rag.retrieval.orchestrator`` to keep that module at a
maintainable size. Responsibility map:

- ``common``           — scalar coercion helpers, stable doc keys, fallback logging
- ``debug_sanitize``   — bounded, PII-safe sanitizers for retriever debug payloads
- ``hierarchy``        — hierarchy family aggregation + ancestor-wins tree dedup
- ``citation_quality`` — citation coverage proxy, empty-retrieval diagnosis,
  parse-quality risk / parse-repair summaries
- ``kg_merge_boost``   — KG scope resolution, KG doc merge, KG chunk boost,
  KG injection chunk fetch
- ``channel_budget``   — channel budget policy resolution + post-rerank pipeline
  config summaries
- ``anchors``          — metadata exact-anchor annotation and doc ordering

``app.rag.retrieval.orchestrator`` imports every moved name at module top so the
historical ``orchestrator.<name>`` attribute surface (used by tests and by
``app.rag.engine``) is unchanged.

Import direction: submodules MUST NOT import ``app.rag.retrieval.orchestrator``
or ``app.rag.engine`` (circular). Helpers that need the engine or the retrieval
runner stay in ``app.rag.retrieval.orchestrator``. This package intentionally
does not re-export names; import from the submodules directly.
"""
