# Recall20 Retrieval Profile Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a retrieval-first config preset `recall20` to maximize chunk-level Hit@20: enforce `top_k>=20`, `score_threshold=0.0`, and disable retrieval result trimming that can drop relevant chunks.

**Architecture:** Introduce a `retrieval_profile` field on request-level `ChatRAGConfig` and dataset-level `DatasetRAGDefaults`. Apply profile normalization to compute effective retrieval params (top_k/threshold + retriever trimming knobs). Ensure both retrieval execution paths (legacy engine + LangGraph) honor the profile by passing overrides into `HybridRetriever.model_copy(update=...)`. Make `/rag/retrieve-preview` default to `recall20` when the caller omits `rag_config`.

**Tech Stack:** FastAPI, Pydantic v2, LangChain retriever (`HybridRetriever`), LangGraph, pytest.

## Task 1: Add `retrieval_profile` field (API surface)

**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/api/schemas/dataset.py`
- Test: `tests/test_retrieval_profile_schema.py`

**Step 1: Write the failing test**

Create `tests/test_retrieval_profile_schema.py` asserting:
- `ChatRAGConfig(retrieval_profile="recall20")` forces `top_k >= 20` and `score_threshold == 0.0`.
- `DatasetRAGDefaults(retrieval_profile="recall20")` accepts the value.

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_retrieval_profile_schema.py`
Expected: FAIL because the field/behavior does not exist yet.

**Step 3: Implement minimal schema + normalization**

In `ChatRAGConfig`, add:
- `retrieval_profile: Optional[str] = None` (supported: `recall20`)
- A post-model validator that applies recall20 overrides:
  - `top_k = max(top_k, 20)`
  - `score_threshold = 0.0`

In `DatasetRAGDefaults`, add:
- `retrieval_profile: Optional[str] = None`

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_retrieval_profile_schema.py`
Expected: PASS.

**Step 5: Commit**

Run:
```bash
git add app/api/schemas/chat.py app/api/schemas/dataset.py tests/test_retrieval_profile_schema.py
git commit -m "feat: add retrieval_profile schema and recall20 normalization"
```

## Task 2: Apply recall20 trimming overrides to `HybridRetriever`

**Files:**
- Modify: `app/rag/pipelines/langgraph.py`
- Modify: `app/rag/engine.py`
- Test: `tests/test_recall20_profile_retriever_overrides.py`

**Step 1: Write the failing test**

Add a unit test that:
- Builds a RAG state/config with `retrieval_profile="recall20"`.
- Asserts that the retriever update dict includes:
  - `dedup_enabled=False`
  - `max_chunks_per_doc=0`
  - `min_distinct_docs=0`

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_recall20_profile_retriever_overrides.py`
Expected: FAIL because overrides are not applied yet.

**Step 3: Implement minimal overrides**

Add recall20 detection and apply overrides in both paths:
- `langgraph._retrieve_node`: extend `state` to carry profile + apply update keys.
- `engine` retrieval construction (`hybrid_retriever.model_copy(update=...)`): add the same override keys.

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_recall20_profile_retriever_overrides.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/rag/pipelines/langgraph.py app/rag/engine.py tests/test_recall20_profile_retriever_overrides.py
git commit -m "feat: apply recall20 retriever trimming overrides"
```

## Task 3: Default `/rag/retrieve-preview` to recall20 when `rag_config` omitted

**Files:**
- Modify: `app/api/v1/rag.py`
- Test: `tests/test_retrieve_preview_defaults_to_recall20.py`

**Step 1: Write the failing test**

Create a test that posts to `/api/v1/rag/retrieve-preview` without `rag_config` and asserts:
- Response metrics reflect `top_k >= 20` and `score_threshold == 0.0` (or equivalent returned fields).

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_retrieve_preview_defaults_to_recall20.py`
Expected: FAIL because endpoint currently uses global defaults.

**Step 3: Implement defaulting logic**

In the handler:
- Detect when the request omitted `rag_config` (via `model_fields_set`).
- Set `effective_rag_config = ChatRAGConfig(retrieval_profile="recall20")` as baseline before dataset merges.

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_retrieve_preview_defaults_to_recall20.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/v1/rag.py tests/test_retrieve_preview_defaults_to_recall20.py
git commit -m "feat: default retrieve-preview to recall20 when rag_config omitted"
```

## Task 4: Beads + verification + push

**Files:**
- Modify: `.beads/issues.jsonl` (generated)

**Step 1: Sync beads**

Run: `bd sync`

**Step 2: Run quality gates**

Run: `pytest -q`
Expected: PASS.

**Step 3: Close issue**

Run: `bd close MimirQ-eum`

**Step 4: Push**

Run:
```bash
git pull --rebase
bd sync
git push
git status
```

