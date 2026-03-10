# Single‑Node Gap Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在单机 / 单实例（Docker Compose / 一台服务器）形态下，把 MimirQ 的“知识库平台化后端”补齐到可长期运行、可回归、可迭代的闭环能力。

**Architecture:** 优先复用现有栈（Postgres + Redis/arq + Milvus），把 Postgres lexical（FTS/pg_trgm）做成可持续的 keyword 主通道；用版本感知缓存 + 回归门禁 + 任务可观测把系统跑稳；再把 feedback→训练→发布串起来。

**Tech Stack:** FastAPI, SQLAlchemy, Postgres (FTS/pg_trgm), Redis/arq, Milvus, pytest, bd（beads）

---

## Task 0: Stabilize baseline (fix existing failing tests first)

**Why:** 当前基线 `pytest` 不是全绿，后续任何改动都无法区分“历史问题”与“新增回归”。

**Files:**
- Modify: `tests/test_retriever_dataset_id_filter_injection.py`
- Modify: `tests/test_retrieval_candidate_cache_corpus_invalidation.py`
- Modify: `tests/test_rerank_budget_governance.py`
- Modify: `tests/test_colbert_retrieval_ann_persisted.py`
- (As needed) Modify: `app/rag/retriever.py`
- (As needed) Modify: `app/rag/retrieval_candidate_cache.py`
- (As needed) Modify: `app/rag/rerank_result_cache.py`

**Step 1: Reproduce each failure with full output**

Run:
- `pytest tests/test_retriever_dataset_id_filter_injection.py -vv`
- `pytest tests/test_retrieval_candidate_cache_corpus_invalidation.py -vv`
- `pytest tests/test_rerank_budget_governance.py -vv`
- `pytest tests/test_colbert_retrieval_ann_persisted.py -vv`

Expected: 这些文件中存在 FAIL（与全量 `pytest` 输出一致）

**Step 2: Fix dataset_id metadata_filter injection regression**

Likely fix direction:
- 允许 metadata_filter 注入除 `dataset_id` 外的版本/embedding 维度（例如 `embedding_space_hash`），测试不应使用 strict equality。

Update test assertions from:
- `assert captured_filter == {"dataset_id": "..."}`
to:
- `assert captured_filter.get("dataset_id") == "..."`

Run: `pytest tests/test_retriever_dataset_id_filter_injection.py -q`  
Expected: PASS

**Step 3: Fix candidate cache corpus invalidation regressions**

Investigate:
- cache key 里 `corpus_cache_token` 是否稳定写入、缺失时是否正确 skip
- corpus token 变更是否导致 miss

Implement minimal fix (one at a time), then run:
- `pytest tests/test_retrieval_candidate_cache_corpus_invalidation.py -q`

Expected: PASS

**Step 4: Fix rerank budget governance regression**

Ensure semantics:
- rerank budget uses requested_k (caller intent) rather than search_k (internal overfetch)

Run:
- `pytest tests/test_rerank_budget_governance.py -q`

Expected: PASS

**Step 5: Fix ColBERT ANN persisted index regression**

Ensure semantics:
- index persists to disk
- reload after in-memory clear does not rebuild

Run:
- `pytest tests/test_colbert_retrieval_ann_persisted.py -q`

Expected: PASS

**Step 6: Verify full suite**

Run: `pytest -q`  
Expected: all tests PASS (allow existing skips)

**Step 7: Commit**

```bash
git add tests/*.py app/rag/*.py
git commit -m "fix(tests): restore baseline regression semantics"
```

---

## Task 1: Issue MimirQ-q075 — Retrieval: lexical DB as primary keyword channel

**Files:**
- Modify: `app/rag/retriever.py`
- Modify: `docs/guides/lexical_fallback.md` (if behavior changes)
- Test: `tests/test_retriever_dataset_id_filter_injection.py`
- (Optional) Add: `tests/test_lexical_db_primary_keyword_mode.py`

**Step 1: Add/adjust tests for keyword mode routing**

Write/extend tests to verify:
- when `retrieval_mode="keyword"`, lexical DB is attempted before BM25 (configurable)
- attribution shows lexical channel used

Run: `pytest tests/test_lexical_db_primary_keyword_mode.py -vv`  
Expected: FAIL until implementation lands

**Step 2: Implement routing + knobs**

In `HybridRetriever._hybrid_search()`:
- add a config/flag to prefer lexical DB for keyword mode (single-node default)
- keep BM25 optional (guarded by `BM25_INDEX_ENABLED`)

**Step 3: Verify no recall regression in hybrid**

Run targeted retrieval tests:
- `pytest tests/test_retriever_dataset_id_filter_injection.py -q`

Expected: PASS

**Step 4: Commit**

```bash
git add app/rag/retriever.py tests/test_*.py docs/guides/lexical_fallback.md
git commit -m "feat(retrieval): prefer lexical DB for keyword mode"
```

---

## Task 2: Issue MimirQ-6zu1 — Cache: version-aware caches + dataset invalidation

**Files:**
- Modify: `app/rag/retrieval_candidate_cache.py`
- Modify: `app/rag/rerank_result_cache.py`
- Modify: `app/services/chat_response_cache.py`
- Modify: `app/services/corpus_cache_tokens.py`
- (Optional) Add: `app/api/v1/cache_admin.py` (or similar)
- Test: `tests/test_retrieval_candidate_cache_corpus_invalidation.py`

**Step 1: Lock in semantics with tests**

Ensure tests cover:
- same corpus token → hit
- changed corpus token → miss
- missing corpus token → skip cache

Run: `pytest tests/test_retrieval_candidate_cache_corpus_invalidation.py -vv`

**Step 2: Unify cache key version dimensions**

Update key builders so all caches consistently include:
- `tenant_id`
- `embedding_space_hash`
- `corpus_cache_token`
- (as needed) dataset scope + retrieval config hash

**Step 3: Add dataset-level invalidation entry point**

Minimum viable:
- admin-only endpoint to clear cache namespaces for a dataset (in-memory caches + redis keys if used)

**Step 4: Verify**

Run:
- `pytest tests/test_retrieval_candidate_cache_corpus_invalidation.py -q`

**Step 5: Commit**

```bash
git add app/rag/*cache*.py app/services/*cache*.py app/api/v1/*.py tests/test_retrieval_candidate_cache_corpus_invalidation.py
git commit -m "feat(cache): make retrieval/rerank caches corpus-version-aware"
```

---

## Task 3: Issue MimirQ-vwve — Sparse/ColBERT persisted index semantics

**Files:**
- Modify: `app/rag/retriever.py`
- (If exists) Modify: `app/rag/retrieval/sparse_index_store.py` or store module used by retriever
- Test: `tests/test_colbert_retrieval_ann_persisted.py`

**Step 1: Make persisted index contract explicit in tests**

Run: `pytest tests/test_colbert_retrieval_ann_persisted.py -vv`

**Step 2: Implement deterministic persisted index load/save**

Key points:
- persisted index keyed by (scope key + provider config hash + corpus fingerprint)
- on mismatch, rebuild instead of silently loading wrong index

**Step 3: Verify**

Run: `pytest tests/test_colbert_retrieval_ann_persisted.py -q`  
Expected: PASS

**Step 4: Commit**

```bash
git add app/rag/retriever.py tests/test_colbert_retrieval_ann_persisted.py
git commit -m "fix(colbert): harden persisted ANN index semantics"
```

---

## Task 4: Issue MimirQ-odid — Ops: background job standardization + observability

**Files:**
- Modify: `app/tasks/jobs.py`
- Modify: `app/tasks/locks.py`
- Modify: `app/services/task_queue_observability_service.py` (if present)
- Modify: `app/api/v1/observability.py`

**Step 1: Add a common job result schema**

Return dict shape:
- `ok: bool`
- `reason: str|None`
- `elapsed_sec: float`
- `tenant_id/run_id/document_id` (when relevant)
- `progress: {stage, done, total}` (best-effort)

**Step 2: Enforce consistent retry/backoff**

Prefer:
- bounded retry with jitter
- clear reasons for retry vs fail

**Step 3: Expose observability snapshot**

Endpoint returns:
- queue name
- worker heartbeat summary
- recent job outcomes (best-effort)

**Step 4: Verify**

Run: `pytest -q` (or targeted task queue tests if present)

**Step 5: Commit**

```bash
git add app/tasks/*.py app/api/v1/observability.py
git commit -m "feat(ops): standardize background jobs and observability snapshot"
```

---

## Task 5: Issue MimirQ-jm5t — Eval: retrieval regression report (JSON/Markdown)

**Files:**
- Modify/Add: `scripts/regression_gate.py` (or existing gate entry)
- Modify: `ci/*` (if CI wiring lives here)
- Docs: `docs/guides/` (short usage)

**Step 1: Add a CLI entry that runs regression and writes artifacts**

Outputs:
- `artifacts/regression/report.json`
- `artifacts/regression/report.md`

**Step 2: Ensure per-channel attribution is included when available**

Leverage `query_debug.channels` (best-effort) to explain regressions.

**Step 3: Verify locally**

Run:
- `python scripts/regression_gate.py --help`
- `python scripts/regression_gate.py --suite retrieval --out artifacts/regression`

Expected: files created

**Step 4: Commit**

```bash
git add scripts/*.py docs/guides/*.md ci/*
git commit -m "feat(eval): add retrieval regression report artifacts"
```

---

## Task 6: Issue MimirQ-fgjd — Feedback/Evidence export training dataset

**Files:**
- Modify: `app/api/v1/feedback.py`
- Modify: `app/api/v1/evidence.py`
- Modify: `app/models/feedback.py`
- Modify: `app/models/evidence.py`
- Add: `docs/guides/training_export.md`
- Test: `tests/test_feedback_training_export.py` (new)

**Step 1: Add failing test for export endpoint**

Run: `pytest tests/test_feedback_training_export.py -vv`  
Expected: FAIL

**Step 2: Implement export (JSONL or CSV)**

Minimum fields:
- question/answer (if present)
- retrieval trace snapshot
- rag config snapshot
- labels/outcome
- timestamps + dataset_id + tenant_id

**Step 3: Verify**

Run:
- `pytest tests/test_feedback_training_export.py -q`

**Step 4: Commit**

```bash
git add app/api/v1/feedback.py app/models/feedback.py docs/guides/training_export.md tests/test_feedback_training_export.py
git commit -m "feat(feedback): export training dataset for LTR/rerank"
```

---

## Task 7: Issue MimirQ-45yg (depends on MimirQ-fgjd) — LTR rollout manual pipeline

**Files:**
- Modify: `app/api/v1/ltr.py`
- Add: `scripts/ltr_train.py` (if needed)
- Add: `scripts/ltr_publish.py` (if needed)
- Docs: `docs/guides/ltr_rollout.md`

**Step 1: Define “model pointer” storage**

Single-node minimal:
- store current model/config pointer in DB or settings table
- keep previous pointer for rollback

**Step 2: Implement train → eval → publish → rollback commands**

**Step 3: Verify**

Run:
- `pytest -q` (and any new tests added)

**Step 4: Commit**

```bash
git add app/api/v1/ltr.py scripts/ltr_*.py docs/guides/ltr_rollout.md
git commit -m "feat(ltr): add manual train/eval/publish/rollback workflow"
```

---

## Task 8: Issue MimirQ-t3jy — Connectors: source identity + reconcile tooling

**Files:**
- Modify: `app/services/connector_sync_state.py`
- Modify: `app/api/v1/connectors.py`
- Add: `app/services/connector_reconcile_service.py` (or similar)
- Docs: `docs/guides/connector_reconcile.md`

**Step 1: Define stable identity fields**

For connector-created docs, ensure doc_metadata includes:
- `connector.connector_id`
- `connector.run_id`
- stable `source_ref` / `source_id` (connector-specific)

**Step 2: Implement reconcile dry-run**

Output:
- missing in source
- present but changed
- tombstoned/deleted

**Step 3: Implement reconcile apply**

Actions:
- soft-disable missing/deleted docs (set `disabled_at`)
- optionally re-enable when reappears (config gated)

**Step 4: Verify**

Run:
- targeted unit tests (add if absent)
- `pytest -q`

**Step 5: Commit**

```bash
git add app/services/*.py app/api/v1/connectors.py docs/guides/connector_reconcile.md
git commit -m "feat(connectors): add reconcile dry-run/apply tooling"
```

---

## Session completion checklist (must-do)

1) `bd update <id> --status in_progress` when starting each issue  
2) Close issues: `bd close <id>` when done  
3) Quality gates: `pytest -q`  
4) Sync issues: `bd sync`  
5) Push:

```bash
git pull --rebase
bd sync
git push
git status  # must be up to date with origin
```

