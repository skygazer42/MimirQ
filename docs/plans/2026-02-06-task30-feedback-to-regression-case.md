# Task 30: Feedback to Regression Case (with Retrieval Trace) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert online feedback into actionable regression cases with evidence pointers and request-level retrieval trace for reproducible debugging.

**Architecture:** Extend `POST /feedback/messages/{id}/to-regression-case` so it extracts `reference_sources` from assistant citations and enriches `extra` with the matching `rag_trace` selected by `message_metadata.request_id`.

**Tech Stack:** FastAPI, SQLAlchemy models (`Message`, `MessageFeedback`, `RagasRegressionCase`), existing trace reader (`app/services/rag_trace_service.py`).

## Notes / Constraints

- Keep behavior fail-open: if trace log is unavailable, regression case creation must still succeed.
- Preserve current endpoint contract and existing fallback logic for missing user question / dataset metadata.

## Implementation Tasks

### Task 1: Add failing regression test (RED)

**Files:**
- Add: `tests/test_task30_feedback_to_regression_case.py`

**Checks:**
- Feedback conversion includes `reference_sources` from assistant `citations`.
- `extra.retrieval_trace` is attached when `request_id` matches one trace record.
- Existing behavior remains (dataset/document scope + inferred question).

### Task 2: Implement conversion enrichment (GREEN)

**Files:**
- Modify: `app/api/v1/feedback.py`

**Changes:**
- Add citation-to-reference normalization helpers (UUID-safe, dedupe, optional span fields).
- Add request-id trace lookup helper via `list_rag_traces(...)`.
- Populate `RagasRegressionCase.reference_sources`.
- Attach matched trace payload into `extra.retrieval_trace`.

### Task 3: Verify and track

**Files:**
- Modify: `docs/plans/2026-02-06-seq-rag-improvements-tracker.md`

**Checks:**
- `PYTHONPATH=. python -m pytest -q tests/test_task30_feedback_to_regression_case.py`
- `PYTHONPATH=. python -m pytest -q`
- Mark Task 30 complete and add this plan to tracker pointers.
