# Retrieval Excellence: Evidence API + Coverage Profiles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Add a production retrieval-only “Evidence API” (no generation) and expand retrieval profiles beyond `recall20` to support high-recall/coverage presets for “does the corpus contain this information?” workflows.

**Architecture:** Reuse the existing retrieval core (`app.rag.pipelines.langgraph._retrieve_node`) and request schema (`ChatRAGConfig`). Add additional retrieval profiles as deterministic presets that can override request fields (contract), and expose a stable API response with explicit `has_evidence` + `abstain_triggered` signals for downstream systems.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, LangChain/LangGraph, pytest.

---

### Task 1: Expand Retrieval Profiles (Coverage Presets)

**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/rag/pipelines/langgraph.py`
- Test: `tests/test_retrieval_profile_schema.py`

**Step 1: Write failing tests for new profiles**

Add tests asserting the preset overrides (top_k/threshold and any additional toggles you introduce):

Run:
```bash
python -m pytest -q tests/test_retrieval_profile_schema.py
```
Expected: FAIL with `ValueError` (profile not recognized) or mismatched assertions.

**Step 2: Implement minimal profile support**

Implement new values like:
- `recall50` (top_k >= 50, score_threshold = 0.0)
- `coverage80` (top_k >= 80, score_threshold = 0.0)

Keep it deterministic and “override allowed” (preset is a contract).

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

Create a unit test that:
- Calls the new handler function directly (monkeypatching `build_rag_state` + `_retrieve_node`)
- Asserts response includes `citations`, `metrics`, `has_evidence`, `abstain_triggered`
- Asserts default behavior when `rag_config` omitted uses a recall-first profile (e.g., `recall50`)

Run:
```bash
python -m pytest -q tests/test_rag_evidence_endpoint.py
```
Expected: FAIL (endpoint missing).

**Step 2: Implement endpoint**

Add:
- Request: `query`, `history`, `dataset_id`/`document_ids`, optional `rag_config`
- Response: `query_for_retrieval`, `citations`, `metrics`, `has_evidence`, `abstain_triggered`, `abstain_reason`

Implementation guidance:
- Reuse the existing access control logic from `/retrieve-preview`.
- Call `build_rag_state(...)` then `_retrieve_node(state)`.
- Derive `has_evidence` from non-empty citations and `abstain_triggered == False`.

**Step 3: Verify tests pass**

Run:
```bash
python -m pytest -q tests/test_rag_evidence_endpoint.py
python -m pytest -q
```
Expected: PASS.

**Step 4: Commit**

```bash
git add app/api/v1/rag.py tests/test_rag_evidence_endpoint.py
git commit -m "feat(api): add retrieval-only evidence endpoint"
```

---

### Task 3: Document The Retrieval-Only Contract

**Files:**
- Add: `docs/guides/evidence_api.md`

**Step 1: Write docs**

Include:
- What “Evidence API” is (retrieval-only)
- Response contract fields
- Recommended profile defaults (`recall50`/`coverage80`)
- How downstream answering systems should use `has_evidence` / `abstain_triggered`

**Step 2: Commit**

```bash
git add docs/guides/evidence_api.md
git commit -m "docs: add evidence api guide"
```

