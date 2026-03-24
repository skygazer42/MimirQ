# RAG Gap Analysis Execution Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the research note in `plans/rag-gap-analysis.md` into an execution-ready plan that closes the real RAG pipeline gaps without re-implementing behavior that already exists.

**Architecture:** Reuse the current retrieval and generation signals instead of adding parallel logic. Phase 1 brings the LangGraph generation path to parity with the classic engine context pipeline. Phase 2 promotes already-computed confidence and citation signals into the API and chat UI. Phase 3 adds new UX behavior only where there is no existing surface.

**Tech Stack:** Python, FastAPI, LangGraph, Pydantic, TypeScript, Next.js, Vitest, pytest

---

## Validated Baseline

These points were verified against the current codebase before writing this plan:

- `app/rag/pipelines/langgraph.py` already calls `extract_evidence_text()` inside `_build_context()` when `RAG_CONTEXT_EVIDENCE_ENABLED` is on. The missing parity versus `app/rag/engine.py` is `denoise_context_docs()`, not evidence extraction.
- `app/rag/pipelines/langgraph.py` already computes `claim_evidence`, `faithfulness_score`, and sentence-citation render output in `_generate_node()`.
- `app/rag/retrieval/orchestrator.py` already computes `detect_evidence_gap()` during contextual follow-up hops. Confidence work should reuse this signal instead of wiring a second gap detector.
- `web/components/chat/message-item.tsx` already has a diagnostics surface for `message_metadata`, `claim_evidence`, and citations, but none of these signals are promoted into the primary assistant message UI.
- `app/services/prompt_resolver.py` selects prompt templates. It is not the first place to change if inline-citation output format needs to move from `[doc:...|chunk:...]` to numbered references.

## Delivery Order

1. LangGraph context parity and deterministic ordering hook.
2. Confidence score aggregation and API/UI surfacing.
3. Inline citation UX completion using the already-rendered backend data.
4. Follow-up suggestions staged rollout.
5. Self-RAG retrieval bypass as a later P1 task.

## Task 1: LangGraph Context Parity and Ordering Hook

**Files:**
- Create: `app/rag/core/doc_ordering.py`
- Modify: `app/rag/pipelines/langgraph.py:233-297`
- Reuse: `app/rag/core/context_denoise.py`
- Test: `tests/test_faithfulness_score_metrics.py`
- Test: `tests/test_langgraph_context_pipeline.py`

**Step 1: Write the failing tests**

Create `tests/test_langgraph_context_pipeline.py` with two focused cases:

```python
from langchain_core.documents import Document


def test_langgraph_build_context_applies_denoise_before_formatting(monkeypatch):
    import app.rag.pipelines.langgraph as lg_mod

    docs = [
        Document(page_content="keep", metadata={"source": "a"}),
        Document(page_content="drop", metadata={"source": "b"}),
    ]

    monkeypatch.setattr(
        "app.rag.core.context_denoise.denoise_context_docs",
        lambda incoming: [incoming[0]],
    )

    out = lg_mod._build_context(docs, query="why")
    assert "keep" in out
    assert "drop" not in out


def test_reorder_docs_for_generation_interleaves_high_and_low_ranked_docs():
    from app.rag.core.doc_ordering import reorder_docs_for_generation

    docs = ["d1", "d2", "d3", "d4", "d5"]
    assert reorder_docs_for_generation(docs) == ["d1", "d3", "d5", "d4", "d2"]
```

Extend `tests/test_faithfulness_score_metrics.py` with a regression check that LangGraph still preserves `extract_evidence_text()` behavior after the denoise insertion.

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_langgraph_context_pipeline.py tests/test_faithfulness_score_metrics.py`

Expected:
- `_build_context()` test fails because LangGraph does not call `denoise_context_docs()`.
- ordering helper import fails because `app/rag/core/doc_ordering.py` does not exist yet.

**Step 3: Write minimal implementation**

Implement `app/rag/core/doc_ordering.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def reorder_docs_for_generation(items: Sequence[T]) -> list[T]:
    ordered = list(items)
    if len(ordered) < 3:
        return ordered
    front = ordered[::2]
    back = list(reversed(ordered[1::2]))
    return front + back
```

Modify `app/rag/pipelines/langgraph.py` so `_build_context()`:
- first applies `denoise_context_docs(docs)` with a fail-safe fallback to the original list
- then optionally applies the ordering helper behind a new feature flag such as `RAG_CONTEXT_REORDER_ENABLED`
- keeps the current `extract_evidence_text()` path untouched

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_langgraph_context_pipeline.py tests/test_faithfulness_score_metrics.py`

Expected:
- PASS
- existing LangGraph faithfulness/sentence-citation tests remain green

**Step 5: Commit**

```bash
git add app/rag/core/doc_ordering.py app/rag/pipelines/langgraph.py tests/test_langgraph_context_pipeline.py tests/test_faithfulness_score_metrics.py
git commit -m "feat(rag): add langgraph context parity hooks"
```

## Task 2: Confidence Score Surfacing from Existing Signals

**Files:**
- Create: `app/rag/core/confidence.py`
- Modify: `app/rag/pipelines/langgraph.py:709-755`
- Modify: `app/api/schemas/chat.py:566-583`
- Modify: `app/api/v1/chat.py:1320-1344`
- Modify: `web/types/index.ts:1860-1870`
- Modify: `web/components/chat/message-item.tsx:217-230`
- Modify: `web/components/chat/message-item.tsx:590-662`
- Test: `tests/test_faithfulness_score_metrics.py`
- Test: `tests/test_evidence_gap.py`
- Test: `web/components/chat/message-item.source.test.ts`

**Step 1: Write the failing tests**

Add a backend unit test for the aggregation function:

```python
def test_compute_confidence_score_combines_faithfulness_gap_and_claim_coverage():
    from app.rag.core.confidence import compute_confidence_score

    out = compute_confidence_score(
        faithfulness_score=0.75,
        claim_total=4,
        claim_supported=3,
        evidence_gap={"has_gap": False, "severity": "none"},
    )

    assert out["score"] == 0.8
    assert out["band"] == "high"
```

Add a source-level UI guard in `web/components/chat/message-item.source.test.ts`:

```ts
expect(src).toContain('confidence_score')
expect(src).toContain('置信度')
```

Extend `tests/test_faithfulness_score_metrics.py` so LangGraph generation metrics must include a top-level `confidence_score` payload when confidence inputs are available.

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_faithfulness_score_metrics.py tests/test_evidence_gap.py`

Run: `cd web && pnpm vitest run components/chat/message-item.source.test.ts`

Expected:
- backend tests fail because there is no `app.rag.core.confidence`
- UI source test fails because the main message UI does not mention confidence yet

**Step 3: Write minimal implementation**

Create `app/rag/core/confidence.py` with a deterministic aggregator:

```python
def compute_confidence_score(*, faithfulness_score, claim_total, claim_supported, evidence_gap):
    # reuse existing pipeline signals only
    ...
    return {"score": score, "band": band, "reasons": reasons}
```

Wire it in `app/rag/pipelines/langgraph.py` by combining:
- `faithfulness_score`
- supported vs total claim counts
- retrieval-layer `evidence_gap` or `iterative_pass` gap metadata already returned in `state["metrics"]`

Promote the result through:
- `app/api/schemas/chat.py` as `confidence_score: float | None = None`
- `app/api/v1/chat.py` non-stream response payload
- `web/types/index.ts`

Render a small assistant-only confidence badge in `web/components/chat/message-item.tsx` above the diagnostics section. Do not force users to open the diagnostics dialog to see it.

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_faithfulness_score_metrics.py tests/test_evidence_gap.py`

Run: `cd web && pnpm vitest run components/chat/message-item.source.test.ts`

Expected:
- PASS
- confidence score appears in both API schema and main UI source

**Step 5: Commit**

```bash
git add app/rag/core/confidence.py app/rag/pipelines/langgraph.py app/api/schemas/chat.py app/api/v1/chat.py web/types/index.ts web/components/chat/message-item.tsx tests/test_faithfulness_score_metrics.py tests/test_evidence_gap.py web/components/chat/message-item.source.test.ts
git commit -m "feat(rag): surface answer confidence score"
```

## Task 3: Inline Citation UX Completion Without Rebuilding the Backend

**Files:**
- Modify: `app/rag/core/sentence_citations.py:6-142`
- Modify: `app/rag/pipelines/langgraph.py:644-707`
- Modify: `web/components/chat/message-item.tsx:80-110`
- Modify: `web/components/chat/message-item.tsx:236-263`
- Modify: `web/components/chat/message-item.tsx:598-628`
- Test: `tests/test_faithfulness_score_metrics.py`
- Test: `web/components/chat/message-item.source.test.ts`

**Step 1: Write the failing tests**

Add a renderer-level test:

```python
def test_render_sentence_citations_inline_uses_numbered_markers():
    from app.rag.core.sentence_citations import render_sentence_citations_inline

    text, count = render_sentence_citations_inline(
        [{"claim": "Sky is blue.", "evidence": [{"document_id": "d1", "chunk_id": "c1"}]}]
    )
    assert count == 1
    assert "[1]" in text
    assert "doc:d1" not in text
```

Add a UI source test that the markdown renderer contains a dedicated citation handler instead of relying only on generic `<a>` rendering.

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_faithfulness_score_metrics.py`

Run: `cd web && pnpm vitest run components/chat/message-item.source.test.ts`

Expected:
- inline citation test fails because the current format is `[doc:... | chunk:...]`
- UI source test fails because there is no numbered-citation mapping in `message-item.tsx`

**Step 3: Write minimal implementation**

Change `app/rag/core/sentence_citations.py` to emit numbered markers and side metadata:

```python
def render_sentence_citations_inline(...):
    # map each evidence item to [1], [2], ...
    ...
```

Keep the backend generation flow in `app/rag/pipelines/langgraph.py`. Do not move this work into `prompt_resolver.py`.

Update `web/components/chat/message-item.tsx` so numbered references in markdown:
- resolve against the current message citation list
- open the correct document/evidence span when clicked
- still preserve the existing citation cards below the answer

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_faithfulness_score_metrics.py`

Run: `cd web && pnpm vitest run components/chat/message-item.source.test.ts`

Expected:
- PASS
- message content and citation cards stay consistent

**Step 5: Commit**

```bash
git add app/rag/core/sentence_citations.py app/rag/pipelines/langgraph.py web/components/chat/message-item.tsx tests/test_faithfulness_score_metrics.py web/components/chat/message-item.source.test.ts
git commit -m "feat(chat): add numbered inline citation UX"
```

## Task 4: Follow-up Suggestions as a Staged Rollout

**Files:**
- Modify: `app/rag/pipelines/langgraph.py:70-134`
- Modify: `app/api/schemas/chat.py:566-583`
- Modify: `app/api/v1/chat.py:1320-1344`
- Modify: `web/types/index.ts:1860-1870`
- Modify: `web/components/chat/message-item.tsx:590-662`
- Reuse: `app/rag/core/text.py:868-930`
- Test: `web/components/chat/message-item.source.test.ts`

**Step 1: Write the failing tests**

Add a source test that the assistant message UI renders follow-up chips when follow-up data exists:

```ts
expect(src).toContain('followup_questions')
expect(src).toContain('继续追问')
```

Add a backend unit test that LangGraph can carry a deterministic follow-up list through the response payload.

**Step 2: Run tests to verify they fail**

Run: `pytest -q tests/test_faithfulness_score_metrics.py`

Run: `cd web && pnpm vitest run components/chat/message-item.source.test.ts`

Expected:
- no `followup_questions` field exists in the API schema or UI

**Step 3: Write minimal implementation**

Stage this in two passes:

Pass A:
- reuse the existing deterministic `abstain_followup` signal from retrieval metadata
- expose it as `followup_questions` only when the assistant abstains

Pass B:
- expand `RAGState` with `followup_questions`
- add general follow-up generation after the answer is finalized
- keep the general generation behind a feature flag such as `RAG_FOLLOWUP_SUGGESTIONS_ENABLED`

Render the suggestions as clickable chips in `web/components/chat/message-item.tsx` beneath the answer and above the citation cards.

**Step 4: Run tests to verify they pass**

Run: `pytest -q tests/test_faithfulness_score_metrics.py`

Run: `cd web && pnpm vitest run components/chat/message-item.source.test.ts`

Expected:
- abstain follow-up suggestions are visible without opening diagnostics
- schema/types stay aligned

**Step 5: Commit**

```bash
git add app/rag/pipelines/langgraph.py app/api/schemas/chat.py app/api/v1/chat.py web/types/index.ts web/components/chat/message-item.tsx web/components/chat/message-item.source.test.ts tests/test_faithfulness_score_metrics.py
git commit -m "feat(chat): surface follow-up suggestions"
```

## Task 5: Self-RAG Retrieval Bypass as a P1 Follow-up

**Files:**
- Modify: `app/rag/policy/intent_router.py`
- Modify: `app/rag/retrieval/orchestrator.py`
- Test: `tests/test_self_rag_intent_router.py`

**Step 1: Write the failing test**

```python
def test_intent_router_marks_greetings_as_no_retrieval():
    from app.rag.policy.intent_router import route_intent

    out = route_intent("hello")
    assert out["skip_retrieval"] is True
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_self_rag_intent_router.py`

Expected:
- fail because there is no no-retrieval path today

**Step 3: Write minimal implementation**

Add a lightweight no-retrieval intent path for greetings, thanks, and small talk, then early-exit retrieval in `app/rag/retrieval/orchestrator.py`.

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_self_rag_intent_router.py`

Expected:
- PASS

**Step 5: Commit**

```bash
git add app/rag/policy/intent_router.py app/rag/retrieval/orchestrator.py tests/test_self_rag_intent_router.py
git commit -m "feat(rag): skip retrieval for no-retrieval intents"
```

## Explicit Non-Goals for This Plan

- Do not overwrite `plans/rag-gap-analysis.md`. Treat it as a research note, not the execution artifact.
- Do not rebuild sentence-citation backend logic from scratch. The backend path already exists.
- Do not use `app/services/prompt_resolver.py` as the first implementation point for citation formatting changes.
- Do not start the visual workflow editor, late chunking, DSPy, fine-tuning, or multimodal work in this wave. Those belong in separate design and execution plans.

## Verification Bundle Before Shipping Any Task

Backend:

```bash
pytest -q tests/test_langgraph_context_pipeline.py tests/test_faithfulness_score_metrics.py tests/test_evidence_gap.py
```

Frontend:

```bash
cd web && pnpm vitest run components/chat/message-item.source.test.ts
cd web && pnpm run typecheck
```

If API or UI response shapes change:

```bash
cd web && pnpm run build
```

## Suggested Commit Boundaries

1. `feat(rag): add langgraph context parity hooks`
2. `feat(rag): surface answer confidence score`
3. `feat(chat): add numbered inline citation UX`
4. `feat(chat): surface follow-up suggestions`
5. `feat(rag): skip retrieval for no-retrieval intents`
