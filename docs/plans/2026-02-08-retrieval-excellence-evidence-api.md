# Retrieval Excellence: Evidence API + Coverage Profiles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Add a production retrieval-only "Evidence API" (no generation) and expand retrieval profiles beyond `recall20` to support high-recall / coverage presets for "does the corpus contain this information?" workflows.

**Architecture:** Reuse the existing retrieval core (`app.rag.pipelines.langgraph._retrieve_node`) and request schema (`ChatRAGConfig`). Add retrieval profiles as deterministic presets that override request fields (a contract). Expose a stable response with explicit `has_evidence` + `abstain_triggered` signals for downstream systems.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, LangChain/LangGraph, pytest.

---

### Task 1: Expand Retrieval Profiles (Coverage Presets)

**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/rag/pipelines/langgraph.py`
- Test: `tests/test_retrieval_profile_schema.py`

**Step 1: Write failing tests for new profiles**

Add tests asserting the preset overrides (top_k / threshold and any additional toggles you introduce).

Run:
```bash
python -m pytest -q tests/test_retrieval_profile_schema.py
```
Expected: FAIL with `ValueError` (profile not recognized) or mismatched assertions.

**Step 2: Implement minimal profile support**

Implement new values like:
- `recall50` (top_k >= 50, score_threshold = 0.0)
- `coverage80` (top_k >= 80, score_threshold = 0.0)

Keep it deterministic and "override allowed" (preset is a contract).

**Step 3: Verify tests pass**

Run:
```bash
python -m pytest -q tests/test_retrieval_profile_schema.py
```
Expected: PASS.

**Step 4: Commit**

```bash
git add app/api/schemas/chat.py app/rag/pipelines/langgraph.py tests/test_retrieval_profile_schema.py
git commit -m "feat(retrieval): add recall/coverage retrieval profiles"
```

---

### Task 2: Add Production Retrieval-Only Evidence Endpoint

**Files:**
- Modify: `app/api/v1/rag.py`
- Modify: `app/api/schemas/chat.py` (response schema reuse if needed)
- Test: `tests/test_rag_evidence_endpoint.py` (new)

**Step 1: Write failing endpoint test**

Create `tests/test_rag_evidence_endpoint.py` that:
- Calls `POST /api/v1/rag/retrieve` with `dataset_id` + `query`.
- Asserts response includes `citations`, `has_evidence`, and abstain fields.
- Asserts `dataset_id` is applied (no cross-dataset citations).

Run:
```bash
python -m pytest -q tests/test_rag_evidence_endpoint.py
```
Expected: FAIL (route/schema missing).

**Step 2: Implement endpoint**

In `app/api/v1/rag.py`:
- Add `POST /rag/retrieve` which runs retrieval only (no generation).
- Return citations + retrieval metrics.
- Compute `has_evidence` deterministically (e.g., min top score + min count thresholds).
- Provide explicit abstain signals: `abstain_triggered`, `abstain_reason`.

**Step 3: Verify**

Run:
```bash
python -m pytest -q tests/test_rag_evidence_endpoint.py
python -m pytest -q
```
Expected: PASS.

**Step 4: Commit**

```bash
git add app/api/v1/rag.py app/api/schemas/chat.py tests/test_rag_evidence_endpoint.py
git commit -m "feat(api): add retrieval-only evidence endpoint"
```

---

### Task 3: Documentation + Example Requests

**Files:**
- Modify: `docs/api.md` (or add new `docs/evidence-api.md`)

**Step 1: Document request/response**

Add example payloads for:
- dataset-scoped high recall (`profile=coverage80`)
- strict recall gate (`profile=recall20`, higher thresholds)

**Step 2: Commit**

```bash
git add docs/api.md
git commit -m "docs: add evidence api usage"
```

