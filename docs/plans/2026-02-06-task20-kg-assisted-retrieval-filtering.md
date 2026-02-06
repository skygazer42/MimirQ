# Task 20: KG-Assisted Retrieval (Entity Linking → Structured Filtering)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Use KG entity linking (query→entities→events) to improve RAG retrieval precision by turning KG results into **structured filters / chunk candidates** (e.g., chunk_id allowlists) instead of only adding a narrative “KG summary” block.

**Architecture:** Reuse existing `kg_search()` (already returns events with `document_id`/`chunk_id`). In the RAG pipeline, merge KG-derived chunk candidates into the retrieved chunk set (dedupe + bounded), tagging them with `retrieval_role="kg"` so rerankers/prompt can treat them differently. Keep it best-effort and gated by settings to avoid regressions.

**Tech Stack:** Python, existing RAG engine (`app/rag/engine.py`), KG pipeline (`app/rag/kg/pipeline.py`), SQLAlchemy `DocumentChunk` reads.

**Status:** DONE (2026-02-06)

## Notes

- Settings: `RAG_KG_CHUNK_INJECTION_ENABLED`, `RAG_KG_CHUNK_INJECTION_MAX_CHUNKS`
- Output/Trace: `done.metrics.kg_chunks_injected` + `rag_trace.kg.chunks_injected`

## Task 1: Add KG chunk injection helper (best-effort)

**Files:**
- Modify: `app/rag/engine.py`
- (Optional) Create: `app/rag/kg/retrieval.py`
- Test: `tests/test_rag_kg_chunk_injection.py`

**Step 1: Write failing test**

- When `KG_ENABLED && KG_CHAT_ENABLED` and `kg_search()` returns events with `chunk_id`,
  the engine injects those chunks into `docs` with `metadata.retrieval_role="kg"` and without duplicates.

**Step 2: Implement minimal**

- Add settings:
  - `RAG_KG_CHUNK_INJECTION_ENABLED` (default False)
  - `RAG_KG_CHUNK_INJECTION_MAX_CHUNKS` (default 5)
- Fetch chunks by IDs (tenant-scoped) and convert to `langchain_core.documents.Document`.
- Merge into `docs` before context assembly.

**Step 3: Run**

Run: `python -m pytest -q tests/test_rag_kg_chunk_injection.py`

## Task 2: Add metrics + trace fields

**Files:**
- Modify: `app/rag/engine.py`
- Test: `tests/test_rag_kg_chunk_injection.py`

**Steps:**
1. Record `kg_chunks_injected` count into `rag_trace` metrics (best-effort).
2. Ensure the injection is bounded and never raises.

## Verify

Run:
- `python -m pytest -q`
