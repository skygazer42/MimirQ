# Index Audit + Retrieval-Only Regression Gate + Evidence Pack UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Ship three enterprise RAG hardening features (no LLM dependency):
1) Dataset-scoped **index consistency audit** (DB ↔ vector index, plus actionable missing/orphan signals)
2) **Retrieval-only regression** runs + CI gate (recall/hit@k/MRR/NDCG/abstain_rate) that work even when RAGAS/LLM metrics are disabled
3) A first-class **Evidence Pack** UI: dataset-scoped retrieval preview + one-click export (JSON) for audit/regression authoring

**Architecture:**
- Keep everything **fail-closed** and bounded (max ids scanned; best-effort vector backend support).
- Reuse existing internal retrieval node (`_retrieve_node`) for LLM-free evaluation.
- Store deterministic retrieval quality metrics in regression run `summary` so `scripts/regression_gate.py` can gate without LLM.

**Tech Stack:** FastAPI + SQLAlchemy, Milvus (best-effort), pytest, Next.js (knowledge page), docs.

**Branch:** `enterprise-rag-2026-02-07-audit-evidence`

## Commit Map (Every 2 Tasks)

- Commit 01: Tasks 1–2 (plan + Milvus existence query helpers)
- Commit 02: Tasks 3–4 (index audit service + admin API endpoint)
- Commit 03: Tasks 5–6 (retrieval-only regression mode + regression gate script update)
- Commit 04: Tasks 7–8 (evidence pack export + dataset-scoped retrieval test)
- Commit 05: Tasks 9–10 (index audit UI wiring + docs + verification)

## Tasks

### Task 1: Add this implementation plan

**Files:**
- Create: `docs/plans/2026-02-07-index-audit-retrieval-only-regression-evidence-pack.md`

**Verify:** N/A

### Task 2: MilvusVectorStore: query existing IDs + dataset id listing (best-effort)

**Files:**
- Modify: `app/storage/vector/milvus.py`
- Test: `tests/test_milvus_vector_store_id_queries.py`

**Step 1: Write failing tests**
- Given a fake collection `query()` backend, `fetch_existing_ids([...])` returns the subset that exist.
- ID list chunking never produces expr over configured max chars (best-effort).

**Step 2: Implement minimal**
- Add `MilvusVectorStore.fetch_existing_ids(ids: list[str]) -> set[str]` (batched, best-effort).
- Add `MilvusVectorStore.list_ids_by_dataset(tenant_id, dataset_id, limit)` (optional; bounded).

**Step 3: Run**
- `python -m pytest -q tests/test_milvus_vector_store_id_queries.py`

### Task 3: Index audit summary helper (pure, testable)

**Files:**
- Create: `app/services/index_audit_service.py`
- Test: `tests/test_index_audit_summary.py`

**Step 1: Write failing test**
- Given expected ids + existing ids, compute missing vectors and missing DB vector_id counts correctly.

**Step 2: Implement**
- A pure helper that builds a JSON-safe summary payload (counts + small samples).

**Step 3: Run**
- `python -m pytest -q tests/test_index_audit_summary.py`

### Task 4: Observability admin endpoint: dataset index audit

**Files:**
- Modify: `app/api/v1/observability.py`
- Test: `tests/test_observability_index_audit_unit.py`

**Step 1: Write failing unit test**
- Import-time test that endpoint response model exists and the handler calls the service helper (mock).

**Step 2: Implement**
- `GET /api/v1/observability/index-audit?dataset_id=...`
- Requires owner/admin.
- Response includes: db active chunk counts, vector_id missing count, checked vector ids count, missing ids sample.

**Step 3: Run**
- `python -m pytest -q tests/test_observability_index_audit_unit.py`

### Task 5: Regression runs: always include retrieval gate summary in run.summary

**Files:**
- Modify: `app/rag/evaluation/ragas.py`
- Test: `tests/test_ragas_regression_run_summary_includes_retrieval_gate.py`

**Step 1: Write failing test**
- A pure helper (or extracted function) merges gate summary keys into run summary.

**Step 2: Implement**
- Ensure regression run summary calls `_build_regression_gate_summary(eval_items)` and stores it.

**Step 3: Run**
- `python -m pytest -q tests/test_ragas_regression_run_summary_includes_retrieval_gate.py`

### Task 6: Retrieval-only regression mode (no RAGAS / no LLM)

**Files:**
- Modify: `app/rag/evaluation/ragas.py`
- Modify: `scripts/regression_gate.py`
- Test: `tests/test_regression_gate_parse_metrics.py`
- Docs: `docs/guides/regression_gate.md`

**Step 1: Write failing test**
- `parse_metrics_list(\"\")` returns `[]` and is allowed when thresholds are provided.

**Step 2: Implement**
- In `run_regression_ragas_evaluation`, when `metric_names==[]`, skip RAGAS import/evaluate and:
  - run retrieval-only via `_retrieve_node` (no generation)
  - persist items with `scores={}` but meta populated
  - set run.summary to gate metrics (recall/hit@k/MRR/NDCG/abstain_rate)
- In `scripts/regression_gate.py`, allow `--metrics \"\"` for retrieval-only runs.
- Update docs with a retrieval-only example.

**Step 3: Run**
- `python -m pytest -q tests/test_regression_gate_parse_metrics.py`

### Task 7: Evidence pack: dataset-scoped retrieval in Knowledge page

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Step 1: Implement**
- Pass `dataset_id=selectedDatasetId` into `ragApi.retrievePreview(...)` when present.

**Verify:**
- `make typecheck` (if web deps installed)

### Task 8: Evidence pack export (JSON download)

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Step 1: Implement**
- Add “导出 Evidence Pack” button when results exist.
- Export payload: dataset_id, query, query_for_retrieval, metrics, citations, exported_at ISO.

**Verify:**
- `make typecheck` (if web deps installed)

### Task 9: Knowledge UI: add Index Audit panel (dataset-scoped)

**Files:**
- Modify: `web/lib/api-client.ts`
- Modify: `web/types/index.ts`
- Modify: `web/app/knowledge/page.tsx`

**Step 1: Implement**
- Add `observabilityApi.getIndexAudit({ dataset_id })`.
- Add minimal UI to render audit summary and show actionable samples.

**Verify:**
- `make typecheck` (if web deps installed)

### Task 10: Docs + Global Verify

**Files:**
- Modify: `docs/guides/observability_dashboard.md` (add “Index audit” section)
- Modify: `docs/guides/regression_gate.md` (retrieval-only gate example)

**Verify (End):**
- `make test`
- `make lint-py`
- `make typecheck` (best-effort)

