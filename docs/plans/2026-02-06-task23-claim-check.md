# Task 23: Post-Generation Claim Check (Evidence Coverage Enforcement)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce hallucinations by verifying each atomic claim in the draft answer is supported by retrieved evidence; unsupported claims are removed or downgraded into uncertainty.

**Architecture:** Add an optional post-processing stage after generation:
- Split answer into atomic claims (sentence-level, plus simple list item splitting).
- For each claim, verify coverage against the already-built context/citations (prefer deterministic checks first; optionally use a fast LLM judge with strict “only evidence” rubric).
- Produce a cleaned answer + a structured report in metrics/trace for replay.

Keep it gated by settings and bounded (max claims, max judge tokens).

**Tech Stack:** Python, RAG engine (`app/rag/engine.py`), text helpers (`app/rag/core/text.py`), pytest.

**Status:** DONE (2026-02-06)

## Task 1: Add claim-splitting helper

**Files:**
- Modify: `app/rag/core/text.py`
- Test: `tests/test_claim_check.py`

**Step 1: Write failing tests**

- Splits paragraphs into sentence claims.
- Splits Markdown lists into item claims.
- Keeps order; filters empty; bounds to `max_claims`.

**Step 2: Implement minimal**

- Add `split_into_claims(text: str, *, max_claims: int = 24) -> list[str]`.

**Step 3: Run**

Run: `python -m pytest -q tests/test_claim_check.py`

## Task 2: Add evidence-coverage checker (deterministic baseline)

**Files:**
- Modify: `app/rag/core/text.py`
- Test: `tests/test_claim_check.py`

**Step 1: Write failing tests**

- Claim with strong token overlap with evidence -> supported.
- Claim with no overlap -> unsupported.
- Always treat “unknown/insufficient evidence” phrasing as supported (do not delete).

**Step 2: Implement minimal**

- Add `is_claim_supported(claim: str, evidence: str) -> bool` (token overlap + thresholds).

**Step 3: Run**

Run: `python -m pytest -q tests/test_claim_check.py`

## Task 3: Wire claim-check into `stream_chat` (optional)

**Files:**
- Modify: `app/rag/engine.py`
- Modify: `app/core/config.py`
- Test: `tests/test_claim_check.py`

**Step 1: Write failing test**

- With `RAG_CLAIM_CHECK_ENABLED=True`, unsupported claims are removed from the final `done` answer.
- `done.metrics.claim_check_removed` reports count.

**Step 2: Implement**

- Add settings (default OFF):
  - `RAG_CLAIM_CHECK_ENABLED`
  - `RAG_CLAIM_CHECK_MAX_CLAIMS`
- Apply claim-check right after generation and before emitting `done`.
- Record structured stats into `rag_trace`.

**Step 3: Run**

Run: `python -m pytest -q tests/test_claim_check.py`

## Verify

Run:
- `python -m pytest -q`
