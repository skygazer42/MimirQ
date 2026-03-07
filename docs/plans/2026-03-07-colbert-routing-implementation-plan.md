# ColBERT Reranker And Adaptive Routing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Productionize the advanced retrieval stack by adding a real opt-in ColBERT late-interaction reranker provider, config-driven intent routing overlays, and offline evaluation artifacts that show when the stronger path helps and when it should stay off.

**Architecture:** Reuse the existing deterministic ColBERT scaffold as the fail-safe fallback, then add an HF-backed token embedder path behind explicit config. Extend the existing `ChatRAGConfig` / dataset defaults / RAG config template pipeline so routing can consume tenant-configurable policy overlays without introducing a new storage system. Upgrade the offline rerank-pipeline evaluator to expose ColBERT provider controls and per-case win/loss summaries.

**Tech Stack:** Python, FastAPI/Pydantic schemas, local reranker services, existing retrieval orchestration, pytest, ruff.

---

### Task 1: Add ColBERT provider plumbing

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/rag/reranker/colbert.py`
- Modify: `app/rag/reranker/factory.py`
- Test: `tests/test_colbert_reranker_scaffold.py`

**Step 1: Write the failing test**

Add tests that prove:
- `ColBERTReranker` can use an injected HF-like token embedder for real late-interaction scoring
- the factory resolves a configured ColBERT provider while preserving deterministic fallback

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_colbert_reranker_scaffold.py`

**Step 3: Write minimal implementation**

Add:
- provider-aware `ColBERTReranker`
- deterministic token embedder fallback
- lazy HF token embedder path
- factory caching/config wiring

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_colbert_reranker_scaffold.py`

### Task 2: Add tenant-configurable intent routing overlays

**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/api/schemas/dataset.py`
- Modify: `app/rag/policy/intent_router.py`
- Modify: `app/rag/pipelines/langgraph.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/rag/engine.py`
- Test: `tests/test_intent_router.py`
- Test: `tests/test_rag_config_template_helpers.py`

**Step 1: Write the failing test**

Add tests that prove:
- dataset/template patches can carry `intent_router` and `intent_router_policy`
- policy rules can override retrieval/rerank knobs for matched phrases
- routing metadata stays bounded and PII-safe

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_intent_router.py tests/test_rag_config_template_helpers.py`

**Step 3: Write minimal implementation**

Add:
- schema fields for routing policy transport
- bounded policy validation and rule matching
- orchestrator / engine / LangGraph state propagation

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_intent_router.py tests/test_rag_config_template_helpers.py`

### Task 3: Strengthen offline rerank evaluation evidence

**Files:**
- Modify: `scripts/eval_rerank_pipeline_offline.py`
- Modify: `docs/guides/reranking_colbert.md`
- Modify: `scripts/README.md`
- Test: `tests/test_eval_rerank_pipeline_offline.py`

**Step 1: Write the failing test**

Add tests that prove:
- the script can build a ColBERT reranker with provider config
- summary output includes win/loss/tie counts so operators can see when the stronger path should stay off

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_eval_rerank_pipeline_offline.py`

**Step 3: Write minimal implementation**

Add:
- ColBERT provider CLI options
- summary delta/win-loss reporting
- docs for opt-in rollout and interpretation

**Step 4: Run test to verify it passes**

Run:
- `pytest -q tests/test_eval_rerank_pipeline_offline.py`
- `ruff check app/rag/reranker/colbert.py app/rag/reranker/factory.py app/rag/policy/intent_router.py scripts/eval_rerank_pipeline_offline.py tests/test_colbert_reranker_scaffold.py tests/test_intent_router.py tests/test_rag_config_template_helpers.py tests/test_eval_rerank_pipeline_offline.py`

