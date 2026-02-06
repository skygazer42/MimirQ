# RAG Quality/Observability Sprint (20 Tasks) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve MimirQ RAG correctness (retrieval + grounding), observability, and regression measurability with 20 small, test-backed changes (commit every 2 tasks).

**Architecture:** Keep behavior safe-by-default (behind existing settings where appropriate), add deterministic utilities, and extend existing trace/regression pipelines to expose useful *PII-safe* metrics.

**Tech Stack:** Python/FastAPI, LangChain/LangGraph, pytest, docs.

**Branch:** `rag-opt-2026-02-06`

## Commit Map (Every 2 Tasks)

- Commit 01: Tasks 1–2 (plan + docs)
- Commit 02: Tasks 3–4 (metadata filter composition + string ops)
- Commit 03: Tasks 5–6 (embedding cache key + embedding cache validation)
- Commit 04: Tasks 7–8 (regression recall/hit metrics + run summary)
- Commit 05: Tasks 9–10 (rag-trace retriever_debug + safe citation extras)
- Commit 06: Tasks 11–12 (stable hashing util + migrate hash() callsites)
- Commit 07: Tasks 13–14 (RRF fusion tie-breakers + tests)
- Commit 08: Tasks 15–16 (settings validation + request weight normalization)
- Commit 09: Tasks 17–18 (observability dashboard enrichment + trace tail script)
- Commit 10: Tasks 19–20 (metadata filter guardrails + docs for recall metrics)

## Tasks

### Task 1: Add this sprint plan

**Files:**
- Create: `docs/plans/2026-02-06-rag-opt-20-tasks.md`

**Verify:** N/A

### Task 2: Extend the RAG optimization guide (metadata_filter + trace tips)

**Files:**
- Modify: `docs/guides/rag_optimization.md`

**Verify:** N/A

### Task 3: Metadata filter supports `$and` / `$or`

**Files:**
- Modify: `app/rag/core/filters.py`
- Test: `tests/test_metadata_filter.py`

**Verify:** `python -m pytest -q tests/test_metadata_filter.py`

### Task 4: Metadata filter supports `$not` + `$startswith` / `$endswith`

**Files:**
- Modify: `app/rag/core/filters.py`
- Test: `tests/test_metadata_filter.py`

**Verify:** `python -m pytest -q tests/test_metadata_filter.py`

### Task 5: Embedding cache key includes embedding space hash (provider/model/base_url)

**Files:**
- Modify: `app/rag/embedding/adapter.py`
- Test: `tests/test_embedding_cache_key_space_hash.py`

**Verify:** `python -m pytest -q tests/test_embedding_cache_key_space_hash.py`

### Task 6: Validate embedding cache config (prefix + ttl)

**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_embedding_cache_validation.py`

**Verify:** `python -m pytest -q tests/test_settings_embedding_cache_validation.py`

### Task 7: Regression items include retrieval recall/hit@k (evidence overlap)

**Files:**
- Modify: `app/rag/evaluation/regression_sample_builder.py`
- Test: `tests/test_ragas_regression_sample_builder.py`

**Verify:** `python -m pytest -q tests/test_ragas_regression_sample_builder.py`

### Task 8: Regression run summary includes recall/hit rates + abstain rate

**Files:**
- Modify: `app/rag/evaluation/ragas.py`
- Test: `tests/test_ragas_regression_summary_metrics.py`

**Verify:** `python -m pytest -q tests/test_ragas_regression_summary_metrics.py`

### Task 9: RAG trace output includes *sanitized* per-query `retriever_debug`

**Files:**
- Modify: `app/rag/trace_schema.py`
- Modify: `app/services/rag_trace_service.py`
- Test: `tests/test_rag_trace_schema.py`

**Verify:** `python -m pytest -q tests/test_rag_trace_schema.py`

### Task 10: RAG trace citations include safe extras (`retrieval_role`, `neighbor_of`)

**Files:**
- Modify: `app/services/rag_trace_service.py`
- Test: `tests/test_rag_trace_schema.py`

**Verify:** `python -m pytest -q tests/test_rag_trace_schema.py`

### Task 11: Add stable hashing utility for IDs/keys

**Files:**
- Create: `app/rag/core/hashing.py`
- Test: `tests/test_stable_hashing.py`

**Verify:** `python -m pytest -q tests/test_stable_hashing.py`

### Task 12: Replace Python `hash()` callsites with stable hashing

**Files:**
- Modify: `app/rag/engine.py`
- Modify: `app/rag/retriever.py`
- Modify: `app/rag/workflows/parallelization.py`
- Modify: `app/rag/memory/short_term.py`
- Test: `tests/test_stable_hashing.py`

**Verify:** `python -m pytest -q tests/test_stable_hashing.py`

### Task 13: Make `fuse_docs_rrf` deterministic under ties

**Files:**
- Modify: `app/rag/engine.py`
- Test: `tests/test_fuse_docs_rrf.py`

**Verify:** `python -m pytest -q tests/test_fuse_docs_rrf.py`

### Task 14: Add unit tests for `fuse_docs_rrf` scoring/meta contract

**Files:**
- Test: `tests/test_fuse_docs_rrf.py`

**Verify:** `python -m pytest -q tests/test_fuse_docs_rrf.py`

### Task 15: Settings validation: retrieval knobs fail-fast on invalid values

**Files:**
- Modify: `app/core/config.py`
- Test: `tests/test_settings_retrieval_validation.py`

**Verify:** `python -m pytest -q tests/test_settings_retrieval_validation.py`

### Task 16: Request-time weight normalization (vector/keyword) when enabled

**Files:**
- Modify: `app/api/schemas/chat.py`
- Test: `tests/test_chat_rag_weight_normalization.py`

**Verify:** `python -m pytest -q tests/test_chat_rag_weight_normalization.py`

### Task 17: Observability dashboard includes overfetch + trim metrics (PII-safe)

**Files:**
- Modify: `app/services/rag_metrics_dashboard.py`
- Test: `tests/test_observability_rag_metrics.py`

**Verify:** `python -m pytest -q tests/test_observability_rag_metrics.py`

### Task 18: Add a trace tail helper script (debugging ergonomics)

**Files:**
- Create: `scripts/rag_trace_tail.py`

**Verify:** `python scripts/rag_trace_tail.py --help`

### Task 19: Guardrails for metadata filters (depth/size limits, fail-closed)

**Files:**
- Modify: `app/rag/core/filters.py`
- Test: `tests/test_metadata_filter.py`

**Verify:** `python -m pytest -q tests/test_metadata_filter.py`

### Task 20: Update regression gate docs to mention recall/hit/abstain metrics

**Files:**
- Modify: `docs/guides/regression_gate.md`

**Verify:** N/A

## Global Verify (End)

Run:
- `make test`
- `make lint-py`

