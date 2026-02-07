# Enterprise RAG Hardening Sprint (Evidence + Regression + Span Grounding) — 20 Tasks

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Move MimirQ closer to “RAGFlow‑grade enterprise KB” by hardening the **retrieval‑only evaluation loop**, **evidence → regression authoring**, and **span‑level grounding** (no LLM dependency required for the core loop).

**Architecture:** Prefer deterministic + bounded utilities (stable ids / span extraction / robust matching) and expose them via:
- Knowledge UI (retrieval preview → evidence pack → regression case)
- Evaluation UI (dataset-scoped cases/runs, retrieval-only mode)
- Chat UX (clickable span-level citations + claim→evidence map in diagnostics)

**Tech Stack:** Python/FastAPI + SQLAlchemy + pytest, Next.js/TS, docs.

**Branch:** `enterprise-rag-2026-02-07-audit-evidence`

## Commit Map (Every 2 Tasks)

- Commit 01: Tasks 1–2 ✅ (`150907ca`, `c0d9606c`)
- Commit 02: Task 3 ✅ (`ca84b568`) + (carry: already landed separately)
- Commit 03: Tasks 4–5 (Evaluation UI: dataset scope + retrieval-only toggle)
- Commit 04: Tasks 6–7 (Evidence Pack import → create regression case)
- Commit 05: Tasks 8–9 (Knowledge UI: select evidence + create regression case)
- Commit 06: Tasks 10–11 (Backend: richer ReferenceSource + robust matching)
- Commit 07: Tasks 12–13 (Backend: citation span extraction)
- Commit 08: Tasks 14–15 (Frontend: span highlighting + backend claim→evidence map)
- Commit 09: Tasks 16–17 (Attach claim evidence to responses + UI diagnostics display)
- Commit 10: Tasks 18–19 (CLI helper + connector validate endpoint)
- Commit 11: Task 20 (Docs + global verify)

## Tasks

### Task 1: Retrieval-only regression gate ✅

**Outcome:** Regression runs support `metrics=[]` (no RAGAS/LLM) while still persisting retrieval gate metrics (recall/hit@k/MRR/NDCG/abstain_rate).

**Files:** (already implemented)

### Task 2: Evidence Pack export ✅

**Outcome:** Knowledge → Retrieval tab can export dataset-scoped retrieval preview results as an “Evidence Pack” JSON payload.

**Files:** (already implemented)

### Task 3: Index Audit panel ✅

**Outcome:** Knowledge → Retrieval tab shows dataset-scoped index audit results.

**Files:** (already implemented)

### Task 4: Evaluation UI — dataset selector + dataset-scoped case listing

**Files:**
- Modify: `web/components/evaluation/regression-tab.tsx`
- Modify: `web/components/test-case-manager.tsx`
- Modify: `web/lib/api-client.ts` (if needed)

**Verify:** `make typecheck`

### Task 5: Evaluation UI — retrieval-only run toggle (allow metrics = empty) + run creation sends dataset_id

**Files:**
- Modify: `web/components/evaluation/regression-tab.tsx`
- Modify: `web/types/index.ts` (tighten types if needed)

**Verify:** `make typecheck`

### Task 6: Evidence Pack import dialog (upload JSON + preview citations)

**Files:**
- Modify: `web/components/test-case-manager.tsx`
- Create (if needed): `web/components/evaluation/evidence-pack-import-dialog.tsx`

**Verify:** `make typecheck`

### Task 7: Create regression case from Evidence Pack (select ground-truth citations → reference_sources)

**Files:**
- Modify: `web/components/test-case-manager.tsx`

**Verify:** `make typecheck`

### Task 8: Knowledge UI — allow selecting “ground truth” citations in retrieval preview

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Verify:** `make typecheck`

### Task 9: Knowledge UI — one-click “Create regression case” from selected citations

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Verify:** `make typecheck`

### Task 10: Backend — ReferenceSource supports chunk_index + fill missing doc_pipeline_key/pipeline_hash/quote

**Files:**
- Modify: `app/api/schemas/regression.py`
- Modify: `app/api/v1/evaluations.py`
- Test: `tests/test_reference_sources_finalize_enrichment.py`

**Verify:** `python -m pytest -q tests/test_reference_sources_finalize_enrichment.py`

### Task 11: Backend — regression matching falls back to (doc_pipeline_key+chunk_index) and quote overlap

**Files:**
- Modify: `app/rag/evaluation/regression_sample_builder.py`
- Test: `tests/test_regression_reference_matching_fallbacks.py`

**Verify:** `python -m pytest -q tests/test_regression_reference_matching_fallbacks.py`

### Task 12: Backend — citation span extraction helper (query → evidence span offsets)

**Files:**
- Modify: `app/rag/core/citations.py`
- Modify: `app/api/schemas/chat.py`
- Test: `tests/test_citation_evidence_spans.py`

**Verify:** `python -m pytest -q tests/test_citation_evidence_spans.py`

### Task 13: Backend — propagate evidence span fields to retrieval preview + chat citations

**Files:**
- Modify: `app/rag/pipelines/langgraph.py`
- Modify: `app/rag/engine.py`
- Test: `tests/test_citation_evidence_spans.py`

**Verify:** `python -m pytest -q tests/test_citation_evidence_spans.py`

### Task 14: Frontend — citation click highlights evidence span when available

**Files:**
- Modify: `web/components/chat/message-item.tsx`
- Modify: `web/types/index.ts` (Citation type additions)

**Verify:** `make typecheck`

### Task 15: Backend — deterministic claim→evidence mapping (per-claim supporting spans)

**Files:**
- Create: `app/rag/core/claim_evidence.py`
- Test: `tests/test_claim_evidence_map.py`

**Verify:** `python -m pytest -q tests/test_claim_evidence_map.py`

### Task 16: Backend — attach claim_evidence map into message_metadata (LangChain + LangGraph)

**Files:**
- Modify: `app/rag/engine.py`
- Modify: `app/rag/pipelines/langgraph.py`
- Test: `tests/test_claim_evidence_map.py`

**Verify:** `python -m pytest -q tests/test_claim_evidence_map.py`

### Task 17: Frontend — diagnostics dialog shows claim evidence + deep-links to highlighted spans

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Verify:** `make typecheck`

### Task 18: CLI — convert Evidence Pack JSON → Regression bundle v1

**Files:**
- Create: `scripts/evidence_pack_to_regression_bundle.py`
- Test: `tests/test_evidence_pack_to_regression_bundle.py`

**Verify:** `python -m pytest -q tests/test_evidence_pack_to_regression_bundle.py`

### Task 19: Backend — connector validate endpoint (best-effort config + connectivity checks)

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_connector_validate_endpoint_unit.py`

**Verify:** `python -m pytest -q tests/test_connector_validate_endpoint_unit.py`

### Task 20: Docs — evidence → regression loop + span citations + retrieval-only runs

**Files:**
- Modify: `docs/guides/regression_gate.md`
- Modify: `docs/guides/observability_dashboard.md`
- Create/Modify: `docs/guides/evidence_pack_to_regression.md`

**Verify (End):**
- `make test`
- `make lint-py`
- `make typecheck`

