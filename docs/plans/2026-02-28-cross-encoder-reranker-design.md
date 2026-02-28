# Cross-Encoder Reranker Provider (Wave17-T041)

## Goal
Add a **local** cross-encoder reranker provider backed by `sentence-transformers` `CrossEncoder`, wired into:
- `app.rag.reranker.factory.get_reranker()`
- `Settings.RERANKER_PROVIDER` validation

This enables a cheap, deterministic rerank option (CPU/GPU local) without requiring a remote reranker API.

## Constraints / Non-Goals
- Optional dependency: no hard import at module import time. Only import `sentence_transformers` when the model is actually needed.
- CI/offline-friendly: unit tests must not download models.
- Do not change default behavior: the provider is only used when `RERANKER_PROVIDER` is set accordingly.
- Not implementing learned fusion / intent routing / field-aware embeddings in this task.

## API / Configuration
- Provider string: `cross_encoder` (also accept `cross-encoder` and `sentence_transformers` aliases in the factory).
- Model: reuse `settings.RERANKER_MODEL` (default stays unchanged; users opt-in).
- Performance knobs:
  - `batch_size`: default to `settings.RERANKER_API_BATCH_SIZE` for consistency.
  - `max_chars`: default to `settings.RERANKER_MAX_CHARS` (truncate candidate text before scoring).

## Implementation Sketch
1. New module `app/rag/reranker/cross_encoder.py`:
   - `CrossEncoderReranker(BaseReranker)` with a **lazy-loaded** `_model`.
   - Accept optional injected `model=` in `__init__` to allow tests to run without `sentence-transformers`.
   - `rerank()`:
     - Build `(query, candidate_text)` pairs, applying `max_chars` truncation.
     - Score in batches via `model.predict(pairs)`.
     - Sort by score descending, stable tie-break by original index (determinism).
     - Return `RerankResult(ordered_ids, score_map, elapsed_sec, model_used, provider)`.
2. Update `app/rag/reranker/factory.py`:
   - Resolve provider to `CrossEncoderReranker`.
   - Cache instance using the existing `_local_reranker_cache` to avoid repeated model loads.
3. Update `app/core/config.py` provider allowlist to include `cross_encoder` aliases.
4. Tests:
   - Unit test verifies ordering + stable tie-break using an injected fake model (no external dependencies).
   - Unit test verifies factory resolves the provider without triggering model download (lazy import).

## Verification
- `pytest -q tests/test_cross_encoder_reranker_scaffold.py`
- `make test`
- `make verify`

