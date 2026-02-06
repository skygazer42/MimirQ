# Task 21: Recall Strategy Buckets (Question Type → Retriever/Threshold)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route retrieval settings by question type (definition / procedure / numeric / schema / policy) so recall strategy is more predictable, and thresholds can be tightened/loosened intentionally.

**Architecture:** Add a lightweight, deterministic classifier (heuristics) that produces a `recall_bucket`. When enabled and `retrieval_mode=auto`, apply bucket-specific defaults (mode, weights, score_threshold, reranker knobs) while still allowing explicit API overrides. Record the chosen bucket in `rag_trace` and `done.metrics` for replay/debug.

**Tech Stack:** Python, RAG engine (`app/rag/engine.py`), heuristics utilities (`app/rag/core/text.py`), pytest.

**Status:** DONE (2026-02-06)

## Notes

- Setting: `RAG_RECALL_BUCKETS_ENABLED` (default OFF)
- Output/Trace: `done.metrics.recall_bucket` + `rag_trace.retrieval.recall_bucket`

## Task 1: Add a deterministic `recall_bucket` classifier

**Files:**
- Modify: `app/rag/core/text.py`
- Test: `tests/test_recall_bucket_routing.py`

**Step 1: Write failing tests**

- `guess_recall_bucket("...字段/column...") == "schema"`
- `guess_recall_bucket("...how to / 步骤 / 流程...") == "procedure"`
- `guess_recall_bucket("...多少/ count / sum...") == "numeric"`
- `guess_recall_bucket("...条例/ policy / regulation...") == "policy"`
- `guess_recall_bucket("...是什么/ define ...") == "definition"`

**Step 2: Implement minimal heuristics**

- Add `guess_recall_bucket(query: str) -> str` with bounded regex/keywords.
- Keep it stable and language-agnostic (basic CN + EN triggers).

**Step 3: Run**

Run: `python -m pytest -q tests/test_recall_bucket_routing.py`

## Task 2: Apply bucket defaults in `stream_chat` (auto mode only)

**Files:**
- Modify: `app/rag/engine.py`
- Modify: `app/core/config.py`
- Test: `tests/test_recall_bucket_routing.py`

**Step 1: Write failing test**

- When `RAG_RECALL_BUCKETS_ENABLED=True` and `retrieval_mode="auto"`, the engine:
  - emits `done.metrics.recall_bucket`
  - applies bucket-specific weights (e.g. schema -> keyword heavier)

**Step 2: Implement minimal routing**

- Add settings (default OFF):
  - `RAG_RECALL_BUCKETS_ENABLED`
  - (Optional) per-bucket knobs (keep minimal; start with a hardcoded mapping).
- If enabled and `retrieval_mode=auto`, compute `recall_bucket` and apply defaults for:
  - `mode_used`, `alpha_val`, `vec_w`, `kw_w`, `rerank_on`, `score_threshold`
- Record into `rag_trace.retrieval.recall_bucket` and `done.metrics.recall_bucket`.

**Step 3: Run**

Run: `python -m pytest -q tests/test_recall_bucket_routing.py`

## Verify

Run:
- `python -m pytest -q`
