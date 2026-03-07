# Cache Invalidation And Distributed Rerank Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make chat, retrieval-candidate, and evidence post-rerank caches safe under corpus churn and multi-replica deployment by binding them to strong corpus-version tokens and adding a shared rerank-cache backend.

**Architecture:** Introduce a small corpus-cache-token helper that derives a stable dataset-scoped or document-scoped invalidation token from dataset `updated_at` and document `updated_at` plus active pipeline hashes. Thread that token into chat cache keys and retrieval candidate cache keys, and fail closed when the token cannot be resolved. Upgrade the evidence post-rerank cache from memory-only TTL storage to a configurable `memory|redis` backend while preserving the existing API surface and bounded metrics.

**Tech Stack:** Python, SQLAlchemy, Redis, FastAPI, pytest, existing RAG/cache services.

---

### Task 1: Add corpus cache token helpers and key coverage

**Files:**
- Create: `app/services/corpus_cache_tokens.py`
- Modify: `app/services/chat_response_cache.py`
- Modify: `app/rag/retrieval_candidate_cache.py`
- Test: `tests/test_chat_response_cache_does_not_cross_scopes.py`
- Test: `tests/test_retrieval_candidate_cache_key_includes_scope.py`
- Test: `tests/test_corpus_cache_tokens.py`

**Step 1: Write the failing test**

Add tests that prove:
- document-scope corpus tokens change when `updated_at` or active pipeline hash changes
- dataset-scope corpus tokens change when dataset `updated_at` changes
- chat cache keys and retrieval candidate cache keys change when `corpus_cache_token` changes

**Step 2: Run test to verify it fails**

Run:
`pytest -q tests/test_chat_response_cache_does_not_cross_scopes.py tests/test_retrieval_candidate_cache_key_includes_scope.py tests/test_corpus_cache_tokens.py`

**Step 3: Write minimal implementation**

Add:
- pure token builders for dataset scope and document scope
- DB-backed resolver helper
- optional `corpus_cache_token` input on both key builders

**Step 4: Run test to verify it passes**

Run:
`pytest -q tests/test_chat_response_cache_does_not_cross_scopes.py tests/test_retrieval_candidate_cache_key_includes_scope.py tests/test_corpus_cache_tokens.py`

### Task 2: Wire corpus tokens into chat and retrieval candidate caches

**Files:**
- Modify: `app/api/v1/chat.py`
- Modify: `app/rag/retriever.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/rag/pipelines/langgraph.py` if retrieval cache signatures need parity
- Test: `tests/test_chat_cache_corpus_invalidation.py`
- Test: `tests/test_retrieval_candidate_cache_corpus_invalidation.py`

**Step 1: Write the failing test**

Add tests that prove:
- chat cache is skipped or busted when the corpus token changes
- retrieval candidate cache keys stop reusing stale entries after corpus changes
- metrics/debug payloads expose hit/miss/skip reasons for these caches

**Step 2: Run test to verify it fails**

Run:
`pytest -q tests/test_chat_cache_corpus_invalidation.py tests/test_retrieval_candidate_cache_corpus_invalidation.py`

**Step 3: Write minimal implementation**

Add:
- corpus token resolution before chat cache lookup/store
- corpus token resolution before retrieval candidate cache lookup/store
- bounded metrics fields like `chat_cache_skip_reason` and retriever `channels.cache.skip_reason`

**Step 4: Run test to verify it passes**

Run:
`pytest -q tests/test_chat_cache_corpus_invalidation.py tests/test_retrieval_candidate_cache_corpus_invalidation.py`

### Task 3: Add shared evidence post-rerank cache backend

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/rag/rerank_result_cache.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `docs/guides/evidence_api.md`
- Test: `tests/test_evidence_post_rerank_cache.py`

**Step 1: Write the failing test**

Add tests that prove:
- `memory` backend keeps existing behavior
- `redis` backend can serve a cached rerank result without relying on in-process TTL state
- orchestrator metrics expose cache backend and bounded hit/miss/skip metadata

**Step 2: Run test to verify it fails**

Run:
`pytest -q tests/test_evidence_post_rerank_cache.py`

**Step 3: Write minimal implementation**

Add:
- `EVIDENCE_POST_RERANK_CACHE_BACKEND`
- Redis-backed get/set path with TTL + prefix reuse
- orchestrator metrics for cache backend and miss accounting

**Step 4: Run test to verify it passes**

Run:
`pytest -q tests/test_evidence_post_rerank_cache.py`

### Task 4: Verify the focused hardening slice

**Files:**
- Verify only

**Step 1: Run focused test suite**

Run:
`pytest -q tests/test_chat_response_cache_does_not_cross_scopes.py tests/test_retrieval_candidate_cache_key_includes_scope.py tests/test_corpus_cache_tokens.py tests/test_chat_cache_corpus_invalidation.py tests/test_retrieval_candidate_cache_corpus_invalidation.py tests/test_evidence_post_rerank_cache.py`

**Step 2: Run lint**

Run:
`ruff check app/services/corpus_cache_tokens.py app/services/chat_response_cache.py app/rag/retrieval_candidate_cache.py app/api/v1/chat.py app/rag/retriever.py app/rag/rerank_result_cache.py app/rag/retrieval/orchestrator.py tests/test_chat_response_cache_does_not_cross_scopes.py tests/test_retrieval_candidate_cache_key_includes_scope.py tests/test_corpus_cache_tokens.py tests/test_chat_cache_corpus_invalidation.py tests/test_retrieval_candidate_cache_corpus_invalidation.py tests/test_evidence_post_rerank_cache.py`

**Step 3: Commit**

```bash
git add app/core/config.py app/services/corpus_cache_tokens.py app/services/chat_response_cache.py app/rag/retrieval_candidate_cache.py app/api/v1/chat.py app/rag/retriever.py app/rag/rerank_result_cache.py app/rag/retrieval/orchestrator.py docs/guides/evidence_api.md tests/test_chat_response_cache_does_not_cross_scopes.py tests/test_retrieval_candidate_cache_key_includes_scope.py tests/test_corpus_cache_tokens.py tests/test_chat_cache_corpus_invalidation.py tests/test_retrieval_candidate_cache_corpus_invalidation.py tests/test_evidence_post_rerank_cache.py
git commit -m "feat: harden cache invalidation and rerank cache backend"
```
