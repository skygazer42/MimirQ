# RAG KG Runtime Quality Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make KG/retrieval improvements measurable and controllable in the DeepDoc quality gate.

**Architecture:** Add request-level KG controls to `ChatRAGConfig` and RAG state, implement a bounded deterministic KG boost after KG chunk injection, and extend the DeepDoc gate with runtime/governance diagnostics. Keep defaults conservative; tests exercise opt-in behavior.

**Tech Stack:** FastAPI/Pydantic, LangChain `Document`, pytest, DeepDoc live gate script.

---

### Task 1: DeepDoc Runtime And Governance Diagnostics

**Files:**
- Modify: `scripts/deepdoc_quality_gate.py`
- Test: `tests/test_deepdoc_quality_gate.py`

**Steps:**
1. Add tests for extracting nested response metrics into row fields.
2. Add tests for summarizing server retrieval latency, API overhead, KG usage, and diagnostics payload.
3. Implement metric extraction and optional diagnostics fetches from dataset ingestion, KG stats, and KG quality endpoints.
4. Run `pytest tests/test_deepdoc_quality_gate.py -q`.

### Task 2: Request-Level KG Controls

**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/api/v1/rag.py`
- Modify: `app/rag/pipelines/langgraph.py`
- Test: add/extend RAG state or endpoint tests.

**Steps:**
1. Add failing tests proving `rag_config` can carry KG injection/boost overrides into RAG state.
2. Add bounded nullable fields to `ChatRAGConfig`.
3. Thread fields through `build_rag_state` callers.
4. Run targeted schema/state tests.

### Task 3: Deterministic KG Boost

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Modify: `app/rag/engine.py` if chat path needs parity.
- Test: add/extend KG ranking propagation tests.

**Steps:**
1. Add failing tests where a KG-injected candidate is promoted only when boost is enabled.
2. Implement bounded score blending with metadata/metrics showing promoted count and top-change.
3. Ensure boost is opt-in and non-KG candidates retain stable order when boost is disabled.
4. Run KG/retrieval targeted pytest.

### Task 4: Verification

**Files:**
- No new production files unless required by tests.

**Steps:**
1. Run targeted pytest for DeepDoc gate, RAG config, KG ranking, and existing changed tests.
2. Run Ruff on modified files.
3. Run `git diff --check`.
4. If a local API service is available, run DeepDoc retrieve/chat/KG comparison with KG boost enabled and summarize accuracy/latency.
