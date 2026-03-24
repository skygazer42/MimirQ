# RAG Gap Analysis Remaining Work Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish the still-open items from `plans/rag-gap-analysis.md` without redoing the five gap-closure tasks that are already merged.

**Architecture:** Keep building on the existing LangGraph + retrieval orchestration surfaces rather than introducing parallel implementations. The remaining near-term work splits into three tracks: finish the follow-up suggestions rollout in the generation path, add a real context-compression stage ahead of context assembly, and add chained multi-hop execution on top of the existing decomposition path. The visual workflow builder should be treated as an MVP product slice with a small backend metadata extension plus a frontend editor replacement, not as an all-at-once platform rewrite.

**Tech Stack:** Python, FastAPI, LangGraph, TypeScript, Next.js, React, pytest, Vitest, pnpm

---

## Validated Current State

These items are already done on `main` and must not be re-implemented:

- LangGraph context parity + reorder hook are already shipped in `app/rag/pipelines/langgraph.py` and `app/rag/core/doc_ordering.py`.
- Confidence score aggregation is already shipped in `app/rag/core/confidence.py` and surfaced in API + UI.
- Numbered inline citation UX is already shipped in `app/rag/core/sentence_citations.py` and `web/components/chat/message-item.tsx`.
- Follow-up suggestion UI is already shipped, but only for abstain-derived deterministic suggestions.
- No-retrieval intent bypass is already shipped in `app/rag/policy/intent_router.py` and `app/rag/retrieval/orchestrator.py`.

These items remain open from the original research note:

- General follow-up suggestion generation for non-abstain answers.
- Query-aware context compression before `_build_context()` final formatting.
- Chained multi-hop execution beyond one-shot parallel decomposition.
- Visual workflow editor MVP on the dataset workflow page.
- P2 items remain roadmap-only and are explicitly out of scope for this plan.

## Task 1: Finish General Follow-Up Suggestions Rollout

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/rag/core/text.py`
- Modify: `app/rag/pipelines/langgraph.py`
- Test: `tests/test_faithfulness_score_metrics.py`

**Step 1: Write the failing tests**

Extend `tests/test_faithfulness_score_metrics.py` with a non-abstain generation case:

```python
def test_langgraph_generate_node_extracts_followups_from_answer_tags(monkeypatch):
    import app.rag.engine as engine_mod
    import app.rag.pipelines.langgraph as lg_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()
    monkeypatch.setattr(settings, "RAG_FOLLOWUP_SUGGESTIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings,
        "LLM_MOCK_RESPONSE",
        "Main answer.\n<followup>What exception type is shown?</followup>\n<followup>Which endpoint failed?</followup>",
        raising=False,
    )

    out = lg_mod._generate_node(
        {
            "question": "Summarize the failure",
            "history": [],
            "docs": [],
            "citations": [],
            "metrics": {},
            "structured_output": False,
        }
    )

    assert "<followup>" not in str(out.get("answer") or "")
    metrics = out.get("metrics") or {}
    assert metrics.get("followup_questions") == [
        "What exception type is shown?",
        "Which endpoint failed?",
    ]
```

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_faithfulness_score_metrics.py -k followup`

Expected:
- FAIL because there is no feature-flagged parser for general `<followup>` tags today.

**Step 3: Write minimal implementation**

Implement this in the smallest possible slice:

- Add `RAG_FOLLOWUP_SUGGESTIONS_ENABLED: bool = False` in `app/core/config.py`.
- Add a helper in `app/rag/core/text.py`, for example `extract_followup_questions_from_answer(answer: str, max_items: int = 3) -> tuple[str, list[str]]`.
- The helper must:
  - parse repeated `<followup>...</followup>` blocks deterministically,
  - strip the tags from the returned answer body,
  - deduplicate trimmed questions,
  - cap the list at 3 items,
  - return the cleaned answer plus `list[str]`.
- In `app/rag/pipelines/langgraph.py`, after the final answer text is assembled but before metrics are finalized:
  - if `RAG_FOLLOWUP_SUGGESTIONS_ENABLED` is on and the response is not an abstain path,
  - extract follow-up questions from the answer,
  - store them into `metrics["followup_questions"]`,
  - keep the existing abstain-derived follow-ups as fallback when no tags are present.

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_faithfulness_score_metrics.py -k followup`

Expected:
- PASS
- abstain follow-up test remains green
- non-abstain tagged follow-ups are exposed without leaking `<followup>` tags into the final answer

**Step 5: Commit**

```bash
git add app/core/config.py app/rag/core/text.py app/rag/pipelines/langgraph.py tests/test_faithfulness_score_metrics.py
git commit -m "feat(chat): complete follow-up suggestion rollout"
```

## Task 2: Add Query-Aware Context Compression

**Files:**
- Create: `app/rag/core/context_compression.py`
- Modify: `app/core/config.py`
- Modify: `app/rag/pipelines/langgraph.py:233-292`
- Test: `tests/test_langgraph_context_pipeline.py`

**Step 1: Write the failing tests**

Extend `tests/test_langgraph_context_pipeline.py` with two focused cases:

```python
def test_compress_context_docs_keeps_query_relevant_sentences():
    from langchain_core.documents import Document
    from app.rag.core.context_compression import compress_context_docs

    docs = [
        Document(
            page_content="Noise sentence. API timeout happened on /v1/chat. More unrelated filler.",
            metadata={"source": "ops.md"},
        )
    ]

    out = compress_context_docs(docs, query="Which endpoint timed out?")
    assert len(out) == 1
    assert "/v1/chat" in out[0].page_content
    assert "Noise sentence" not in out[0].page_content


def test_langgraph_build_context_applies_compression_before_render(monkeypatch):
    import app.rag.pipelines.langgraph as lg_mod
    from langchain_core.documents import Document
    from app.core.config import settings

    monkeypatch.setattr(settings, "RAG_CONTEXT_COMPRESSION_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "app.rag.core.context_compression.compress_context_docs",
        lambda docs, query=None: [Document(page_content="COMPRESSED", metadata={"source": "x"})],
    )

    out = lg_mod._build_context([Document(page_content="RAW", metadata={"source": "x"})], query="why")
    assert "COMPRESSED" in out
    assert "RAW" not in out
```

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_langgraph_context_pipeline.py`

Expected:
- FAIL because `app.rag.core.context_compression` does not exist yet.
- FAIL because `_build_context()` has no compression stage.

**Step 3: Write minimal implementation**

Create `app/rag/core/context_compression.py` with a deterministic compression helper:

```python
def compress_context_docs(docs: list[Document], query: str | None = None) -> list[Document]:
    ...
```

Implementation rules:

- Reuse sentence-level extraction logic rather than inventing a separate heavy pipeline.
- Keep this stage deterministic and local-only.
- Start simple:
  - split each doc into sentences,
  - score sentences by lightweight query-term overlap,
  - keep top sentences per doc,
  - preserve metadata,
  - drop docs that compress to empty content.
- Add `RAG_CONTEXT_COMPRESSION_ENABLED: bool = False` to `app/core/config.py`.
- In `app/rag/pipelines/langgraph.py`, update `_build_context()` pipeline order to:
  - `denoise_context_docs()`
  - optional `compress_context_docs()`
  - optional `reorder_docs_for_generation()`
  - final formatting / budget enforcement

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_langgraph_context_pipeline.py`

Expected:
- PASS
- `_build_context()` still respects existing char/token budgets
- compression is optional and feature-flagged

**Step 5: Commit**

```bash
git add app/core/config.py app/rag/core/context_compression.py app/rag/pipelines/langgraph.py tests/test_langgraph_context_pipeline.py
git commit -m "feat(rag): add context compression stage"
```

## Task 3: Add Chained Multi-Hop Decomposition Execution

**Files:**
- Create: `app/rag/retrieval/decomposition_chain.py`
- Modify: `app/core/config.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Reuse: `app/rag/workflows/planner_worker.py`
- Test: `tests/test_query_decomposition_chain.py`

**Step 1: Write the failing tests**

Create `tests/test_query_decomposition_chain.py`:

```python
from __future__ import annotations

import pytest


def test_run_retrieval_chains_decomposed_queries_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", True, raising=False)
    monkeypatch.setattr(settings, "RAG_DECOMPOSITION_CHAIN_ENABLED", True, raising=False)

    captured_queries: list[str] = []

    class _Retriever:
        _last_debug_metrics = {}

        def model_copy(self, **_kwargs):
            return self

        def invoke(self, query):
            captured_queries.append(str(query))
            return []

    monkeypatch.setattr(orch, "hybrid_retriever", _Retriever(), raising=True)
    monkeypatch.setattr(orch, "_decompose_query", lambda *args, **kwargs: ["subquestion one", "subquestion two"], raising=False)

    orch.run_retrieval({"question": "complex question", "history": []})

    assert len(captured_queries) >= 2
    assert "subquestion one" in captured_queries[0]
    assert "subquestion one" in captured_queries[1]
```

Add one metrics assertion in the same file:

```python
def test_run_retrieval_marks_decomposition_chain_metrics(monkeypatch):
    ...
    out = orch.run_retrieval({...})
    metrics = out.get("metrics") or {}
    assert metrics.get("decompose_chain_used") is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_query_decomposition_chain.py`

Expected:
- FAIL because there is no chain-execution helper today.
- FAIL because orchestrator only does one-shot decomposition, not sequential state carry-forward.

**Step 3: Write minimal implementation**

Create `app/rag/retrieval/decomposition_chain.py` with two small helpers:

- `build_chained_query(subquestion: str, prior_findings: list[str]) -> str`
- `summarize_chain_step(citations: list[dict[str, Any]]) -> str`

Implementation rules:

- Keep the first shipped version deterministic.
- Do not call a second planner.
- Do not replace the existing decomposition path.
- Gate everything behind `RAG_DECOMPOSITION_CHAIN_ENABLED: bool = False`.
- In `app/rag/retrieval/orchestrator.py`:
  - after decomposition output is available,
  - run subquestions sequentially when the flag is on,
  - build each next query from the prior findings summary,
  - merge docs/citations into the final fused result,
  - emit metrics such as `decompose_chain_enabled`, `decompose_chain_used`, `decompose_chain_steps`, `decompose_chain_elapsed_sec`.
- Reference `PlannerWorkerWorkflow` only as the dependency model to keep the execution order simple; do not replace orchestrator with that workflow class in this task.

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_query_decomposition_chain.py`

Then run the intent/router regression bundle to protect nearby behavior:

Run: `pytest -q tests/test_intent_router.py tests/test_self_rag_intent_router.py`

Expected:
- PASS
- chain execution is opt-in and leaves current retrieval behavior unchanged when disabled

**Step 5: Commit**

```bash
git add app/core/config.py app/rag/retrieval/decomposition_chain.py app/rag/retrieval/orchestrator.py tests/test_query_decomposition_chain.py
git commit -m "feat(rag): add chained multi-hop decomposition"
```

## Task 4: Add Workflow Layout Metadata to Dataset Config Export/Import

**Files:**
- Modify: `app/api/schemas/dataset.py:333-366`
- Modify: `app/api/v1/datasets.py:978-1020`
- Modify: `web/types/index.ts:1519-1539`
- Test: `tests/test_dataset_config_workflow_layout.py`

**Step 1: Write the failing tests**

Create `tests/test_dataset_config_workflow_layout.py`:

```python
from __future__ import annotations


def test_dataset_config_bundle_accepts_workflow_layout() -> None:
    from app.api.schemas.dataset import DatasetConfigBundle

    bundle = DatasetConfigBundle(
        workflow_layout={
            "schema": "mimirq.workflow_layout.v1",
            "nodes": [{"id": "retrieve", "x": 120, "y": 80}],
            "edges": [],
        }
    )

    assert bundle.workflow_layout is not None
    assert bundle.workflow_layout["schema"] == "mimirq.workflow_layout.v1"
```

Add an export helper regression in the same file:

```python
def test_build_dataset_config_bundle_preserves_workflow_layout_metadata():
    ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_dataset_config_workflow_layout.py`

Expected:
- FAIL because `DatasetConfigBundle` has no workflow-layout field today.

**Step 3: Write minimal implementation**

Modify `app/api/schemas/dataset.py`:

- Add `workflow_layout: dict[str, Any] | None = None` to `DatasetConfigBundle`.
- Keep it optional and opaque in v1.

Modify `app/api/v1/datasets.py`:

- Update `_build_dataset_config_bundle()` to read `workflow_layout` from dataset metadata when present.
- Make import/export preserve the field round-trip.

Modify `web/types/index.ts`:

- Add `workflow_layout?: Record<string, any> | null` to `DatasetConfigBundle`.

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_dataset_config_workflow_layout.py`

Expected:
- PASS
- export/import types are round-trip safe without changing existing dataset config users

**Step 5: Commit**

```bash
git add app/api/schemas/dataset.py app/api/v1/datasets.py web/types/index.ts tests/test_dataset_config_workflow_layout.py
git commit -m "feat(workflow): persist workflow layout metadata"
```

## Task 5: Replace the Read-Only Workflow Graph with a React Flow MVP Editor

**Files:**
- Create: `web/components/workflow/workflow-editor.tsx`
- Modify: `web/app/datasets/[id]/workflow/page.tsx:220-340`
- Modify: `web/types/index.ts:1519-1539`
- Test: `web/components/workflow/workflow-editor.source.test.ts`

**Step 1: Write the failing tests**

Create `web/components/workflow/workflow-editor.source.test.ts`:

```ts
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('workflow editor source', () => {
  it('uses React Flow editor primitives for editable workflow layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'workflow-editor.tsx'), 'utf8')
    expect(src).toContain('@xyflow/react')
    expect(src).toContain('ReactFlow')
    expect(src).toContain('onNodesChange')
    expect(src).toContain('onEdgesChange')
  })
})
```

Add a page-level source assertion if needed:

```ts
expect(pageSrc).toContain('WorkflowEditor')
```

**Step 2: Run tests to verify they fail**

Run: `cd web && pnpm vitest run components/workflow/workflow-editor.source.test.ts`

Expected:
- FAIL because there is no workflow editor component yet.

**Step 3: Write minimal implementation**

Build an MVP only:

- Create `web/components/workflow/workflow-editor.tsx` using `@xyflow/react`.
- The editor must support:
  - initial nodes/edges from `workflow_layout`,
  - dragging nodes,
  - connecting edges,
  - notifying the page when layout changes.
- Update `web/app/datasets/[id]/workflow/page.tsx` so:
  - the left pane uses `WorkflowEditor` instead of the read-only `GraphViewer`,
  - the right pane remains the JSON/details inspector,
  - export/import keep working,
  - there is a save action that persists `workflow_layout` through the existing dataset config endpoints.
- Keep the current force-graph components untouched for other views; this task only swaps the dataset workflow page.

**Step 4: Run tests to verify they pass**

Run: `cd web && pnpm vitest run components/workflow/workflow-editor.source.test.ts`

Then run: `cd web && pnpm run typecheck`

Expected:
- PASS
- workflow page compiles with the new editor component
- no existing graph components are removed or broken

**Step 5: Commit**

```bash
git add web/components/workflow/workflow-editor.tsx web/app/datasets/[id]/workflow/page.tsx web/types/index.ts web/components/workflow/workflow-editor.source.test.ts
git commit -m "feat(workflow): add editable workflow builder mvp"
```

## Explicit Non-Goals for This Plan

- Do not redo the five tasks already landed from `docs/plans/2026-03-24-rag-gap-analysis-execution-plan.md`.
- Do not batch-enable all existing feature flags as part of this work.
- Do not attempt the full visual workflow platform beyond the dataset workflow page MVP.
- Do not start P2 items here: Late Chunking, proposition extraction, embedding fine-tuning, DSPy, Matryoshka/quantization, or multimodal LLM support.

## Verification Bundle Before Shipping Any Task

Backend:

```bash
pytest -q tests/test_faithfulness_score_metrics.py tests/test_langgraph_context_pipeline.py tests/test_query_decomposition_chain.py tests/test_dataset_config_workflow_layout.py
```

Routing regressions:

```bash
pytest -q tests/test_intent_router.py tests/test_self_rag_intent_router.py
```

Frontend:

```bash
cd web && pnpm vitest run components/chat/message-item.source.test.ts components/workflow/workflow-editor.source.test.ts
cd web && pnpm run typecheck
```

If workflow page response shapes change:

```bash
cd web && pnpm run build
```
