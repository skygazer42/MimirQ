# Task 22: Context Compression (Evidence-Only Context, Citations Preserved)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce model distraction by compressing retrieved chunks down to only the most query-relevant sentences/fields, without losing citation metadata.

**Architecture:** Keep compression *per chunk* so citations stay anchored to the original `chunk_id`/`page_number`/offset metadata. Use deterministic extraction (no LLM calls) with bounded output sizes. Ensure observability in `rag_trace` + `done.metrics`.

**Tech Stack:** Python, RAG engine (`app/rag/engine.py`), text helpers (`app/rag/core/text.py`), pytest.

**Status:** DONE (2026-02-06)

## Notes

- Setting: `RAG_CONTEXT_EVIDENCE_ENABLED` (default OFF)
- Safety: evidence extraction is best-effort (falls back to raw chunk content)
- Tests: `tests/test_context_compression_evidence_extraction.py`

## Task 1: Add regression tests for evidence extraction

**Files:**
- Modify: `app/rag/core/text.py`
- Test: `tests/test_context_compression_evidence_extraction.py`

**Step 1: Write failing tests**

- When the query matches 1–2 terms, extraction keeps only matching sentences (bounded).
- When no terms match, extraction still returns a small prefix (non-empty, bounded).
- When `max_chars` is set, output is always `<= max_chars + 3` (for `...`).

**Step 2: Implement minimal fixes (if needed)**

- Keep deterministic behavior; avoid overfitting to a single language.

**Step 3: Run**

Run: `python -m pytest -q tests/test_context_compression_evidence_extraction.py`

## Task 2: Ensure compression is observable + safe to enable

**Files:**
- Modify: `app/rag/engine.py`
- Modify: `app/core/config.py`
- Test: `tests/test_context_compression_evidence_extraction.py`

**Step 1: Write failing test**

- When `RAG_CONTEXT_EVIDENCE_ENABLED=True`, `done.metrics.context_evidence_enabled` is true and `rag_trace.context_evidence.enabled` is true.

**Step 2: Implement**

- Ensure the engine records relevant compression knobs in `rag_trace` and `done.metrics`.
- Keep feature default OFF; never raise if extraction fails (best-effort).

**Step 3: Run**

Run: `python -m pytest -q tests/test_context_compression_evidence_extraction.py`

## Verify

Run:
- `python -m pytest -q`
