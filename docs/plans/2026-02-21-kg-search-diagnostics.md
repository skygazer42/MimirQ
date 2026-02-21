# KG Search Diagnostics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Dynamic OneEval-style diagnostics API for KG search, seeded by RAGAS regression cases, with automatic KG preflight extraction, LLM-generated hardcases, and actionable attribution (vector/entity/relation/skill).

**Architecture:** Keep it DB-light (no new tables). Implement as an on-demand evaluation endpoint under `/api/v1/evaluations`, backed by a small orchestrator that:
1) loads regression cases, 2) ensures evidence docs have KG extracted, 3) runs KG search with bounded overrides, 4) computes deterministic metrics vs evidence chunk ids, 5) generates + runs hardcases (LLM), 6) returns a stable diagnostic payload.

**Tech Stack:** FastAPI, SQLAlchemy (existing session), existing KG pipeline (`KGSearcher` / `SearchConfig`), existing LLM wrapper (`BaseLLMClient.chat_with_schema` via `create_llm_client`), pytest (unit tests; LLM mocked).

---

### Task 1: Add KG Diagnostics API Schemas

**Files:**
- Create: `app/api/schemas/kg_diagnostics.py`
- Modify: `app/api/v1/evaluations.py`

**Step 1: Create request/response Pydantic models**

Include:
- `KGSearchDiagnosticsRequest`
- `KGSearchDiagnosticsResponse`
- `KGSearchDiagnosticsSummary`
- `KGSearchDiagnosticsItem`
- `KGSearchRunResult` (baseline/hardcase run)
- `KGEvalAttribution`

**Step 2: Wire schemas into endpoint signature**

Add endpoint stub:
- `POST /api/v1/evaluations/kg/search/diagnostics`

**Step 3: Verify it imports**

Run:
```bash
python -m compileall -q app
```

Expected: exit code 0

**Step 4: Commit**
```bash
git add app/api/schemas/kg_diagnostics.py app/api/v1/evaluations.py
git commit -m "feat(eval): add KG search diagnostics API schemas"
```

---

### Task 2: Implement Deterministic Metrics Helpers (Hit@K / MRR / Recall)

**Files:**
- Create: `app/rag/evaluation/kg_search_diagnostics_metrics.py`
- Create: `tests/test_kg_search_diagnostics_metrics.py`

**Step 1: Write failing unit tests**

Test cases:
- perfect hit at rank 1
- hit only after rank k (hit@k false, mrr > 0 when considering full list)
- multiple evidence chunks with partial coverage (recall fraction)
- empty results

Run:
```bash
pytest tests/test_kg_search_diagnostics_metrics.py -q
```
Expected: FAIL

**Step 2: Implement helper**

Signature (suggested):
```python
def compute_kg_hit_metrics(*, events: list[dict], evidence_chunk_ids: set[str], k: int) -> dict:
    ...
```

**Step 3: Run tests**

Expected: PASS

**Step 4: Commit**
```bash
git add app/rag/evaluation/kg_search_diagnostics_metrics.py tests/test_kg_search_diagnostics_metrics.py
git commit -m "feat(eval): add KG search diagnostic metrics"
```

---

### Task 3: Implement LLM Hardcase Generator (Knowledge + Reasoning Pressure)

**Files:**
- Create: `app/rag/evaluation/kg_hardcase_generator.py`
- Create: `tests/test_kg_hardcase_generator_guardrails.py`

**Step 1: Write failing tests (LLM mocked)**

Guardrails to test:
- dedupe
- length caps
- cap count (hardcases_per_failed_case)
- schema parsing fallback when LLM returns `{"raw": ...}`

Run:
```bash
pytest tests/test_kg_hardcase_generator_guardrails.py -q
```
Expected: FAIL

**Step 2: Implement generator**

- `generate_hardcases_llm(question, evidence_snippets, entity_hints, *, n, temperature) -> list[Hardcase]`
- best-effort fallback: return [] and include error meta

**Step 3: Run tests**

Expected: PASS

**Step 4: Commit**
```bash
git add app/rag/evaluation/kg_hardcase_generator.py tests/test_kg_hardcase_generator_guardrails.py
git commit -m "feat(eval): add LLM hardcase generator for KG diagnostics"
```

---

### Task 4: Implement KG Search Diagnostics Orchestrator

**Files:**
- Create: `app/rag/evaluation/kg_search_diagnostics.py`

**Step 1: Implement core runner**

Main entry:
```python
async def run_kg_search_diagnostics(*, db, tenant_id, account_id, req: KGSearchDiagnosticsRequest) -> KGSearchDiagnosticsResponse:
    ...
```

Responsibilities:
- Load cases from `RagasRegressionCase` (validate dataset readable)
- Preflight KG extraction for evidence documents when `auto_extract_kg=true`
  - check `documents.doc_metadata["kg_extracted_at"]`
  - if missing, call existing KG extraction pipeline for that document
- Resolve ground truth event ids from `KgSourceEvent.chunk_id in evidence_chunk_ids`
- Run KG search baseline using `KGSearcher.search(SearchConfig(...))`
  - override `rerank.max_results = max(k, 30)` for diagnostics-only visibility
- Compute metrics + attribution (use clues/stats + evidence presence)
- For baseline failures, generate hardcases via Task 3 and rerun search + metrics

**Step 2: Add minimal runtime guardrails**
- hard caps for `max_cases`, `max_failed_cases_for_hardcase`, `hardcases_per_failed_case`
- bounded preflight concurrency

**Step 3: Commit**
```bash
git add app/rag/evaluation/kg_search_diagnostics.py
git commit -m "feat(eval): add KG search diagnostics runner"
```

---

### Task 5: Wire Endpoint + Unit Endpoint Test

**Files:**
- Modify: `app/api/v1/evaluations.py`
- Create: `tests/test_kg_search_diagnostics_endpoint_wiring.py`

**Step 1: Wire endpoint**
- Enforce `DatasetService.ensure_member`
- Enforce dataset readable
- Call `run_kg_search_diagnostics(...)`

**Step 2: Unit wiring test (mock runner)**
- Build a small FastAPI app with just the endpoint
- Override dependencies `get_db/get_tenant_id/get_current_account_id`
- Monkeypatch `run_kg_search_diagnostics` to return a minimal response dict
- Assert status=200 + response shape

Run:
```bash
pytest tests/test_kg_search_diagnostics_endpoint_wiring.py -q
```
Expected: PASS

**Step 3: Commit**
```bash
git add app/api/v1/evaluations.py tests/test_kg_search_diagnostics_endpoint_wiring.py
git commit -m "feat(eval): add KG search diagnostics endpoint"
```

---

### Task 6: Docs Update

**Files:**
- Modify: `docs/guides/knowledge_graph.md`

Add a short section:
- How to run KG diagnostics (endpoint + key params)
- Which feature flags affect results (skills/relations/relation-expansion)

**Step 2: Commit**
```bash
git add docs/guides/knowledge_graph.md
git commit -m "docs(kg): document KG search diagnostics eval"
```

---

### Task 7: Verification + Beads Workflow + Push

**Step 1: Run unit tests**
```bash
pytest -q
```

**Step 2: Run lint (if available)**
```bash
ruff check .
```

**Step 3: Update beads**
```bash
bd close MimirQ-qq2
bd sync
```

**Step 4: Push**
```bash
git pull --rebase
git push
git status -sb
```

Expected: `## main...origin/main` with no ahead/behind.

