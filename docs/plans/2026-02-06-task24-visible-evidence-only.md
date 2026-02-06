# Task 24: Visible-Evidence-Only Grounding ("不可见即不存在")

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure the assistant only answers using *visible* retrieved evidence (citations/context); when evidence is missing/weak, abstain as a normal success path (no errors).

**Architecture:** Add a single "strict grounding" toggle that forces evidence gates:
- Force the abstain gate even if `RAG_ABSTAIN_ENABLED=false` (using existing thresholds).
- Force post-generation claim-check (non-structured only) so unsupported claims are removed.
- Avoid feeding hidden/non-cited context (e.g., KG event summaries) into the model in strict mode.

**Tech Stack:** Python, settings (`app/core/config.py`), LangChain engine (`app/rag/engine.py`), LangGraph pipeline (`app/rag/pipelines/langgraph.py`), pytest.

**Status:** DONE (2026-02-06)

## Task 1: Add strict grounding setting

**Files:**
- Modify: `app/core/config.py`

**Step 1: Write failing test**

Add to `tests/test_visible_evidence_only.py`:

```python
def test_settings_has_visible_evidence_only_toggle(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", True, raising=True)
```

Expected: fails because setting is missing.

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: FAIL with "has no field".

**Step 3: Implement minimal**

Add to `Settings`:

```python
RAG_VISIBLE_EVIDENCE_ONLY_ENABLED: bool = False
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: PASS.

## Task 2: Force abstain gate when strict grounding enabled (LangChain engine)

**Files:**
- Modify: `app/rag/engine.py`
- Modify: `app/rag/core/text.py` (shared abstain message helper/constant)
- Test: `tests/test_visible_evidence_only.py`

**Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_strict_mode_abstains_when_no_citations(monkeypatch):
    # RAG_VISIBLE_EVIDENCE_ONLY_ENABLED=True, RAG_ABSTAIN_ENABLED=False
    # retriever returns []
    # expects done.metrics.generation_elapsed_sec == 0.0
    # expects answer == "Unable to answer this question based on the available materials."
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: FAIL (assistant answers / no abstain).

**Step 3: Implement minimal**

In `engine.stream_chat`, treat strict mode as enabling abstain:

```python
strict = bool(settings.RAG_VISIBLE_EVIDENCE_ONLY_ENABLED)
abstain_enabled = bool(settings.RAG_ABSTAIN_ENABLED) or strict
```

Also standardize abstain message via shared helper (same phrase as the prompt requirement).

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: PASS.

## Task 3: Force claim-check when strict grounding enabled

**Files:**
- Modify: `app/rag/engine.py`
- Test: `tests/test_visible_evidence_only.py`

**Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_strict_mode_forces_claim_check(monkeypatch):
    # strict on, claim_check setting off
    # LLM outputs 2 claims, only 1 supported by evidence
    # expects unsupported claim removed and metrics claim_check_removed == 1
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: FAIL (Bananas claim still present).

**Step 3: Implement minimal**

Treat strict mode as enabling claim-check:

```python
claim_check_configured = bool(settings.RAG_CLAIM_CHECK_ENABLED) or strict
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: PASS.

## Task 4: Apply strict grounding to LangGraph pipeline

**Files:**
- Modify: `app/rag/pipelines/langgraph.py`
- Test: `tests/test_visible_evidence_only.py`

**Step 1: Write failing test**

Call `_retrieve_node` / `_generate_node` directly with a minimal state and verify:
- strict mode triggers abstain even if `RAG_ABSTAIN_ENABLED=false`
- strict mode forces claim-check removal (non-structured only)

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: FAIL.

**Step 3: Implement minimal**

Same logic as LangChain engine:
- `abstain_enabled = settings.RAG_ABSTAIN_ENABLED or strict`
- apply claim-check after `answer = chain.invoke(...)` when strict/claim-check enabled

**Step 4: Run test to verify it passes**

Run: `python -m pytest -q tests/test_visible_evidence_only.py`
Expected: PASS.

## Verify

Run:
- `python -m pytest -q tests/test_visible_evidence_only.py`
- `python -m pytest -q`

## Commit

```bash
git add app/core/config.py app/rag/core/text.py app/rag/engine.py app/rag/pipelines/langgraph.py tests/test_visible_evidence_only.py docs/plans/2026-02-06-task24-visible-evidence-only.md
git commit -m "feat(rag): strict visible-evidence-only grounding"
```
