# E2E RAG Load Test Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a runnable end-to-end load test for `ingest -> retrieve -> answer`, reporting throughput and latency percentiles (P95 in particular).

**Architecture:** A single Python CLI script under `scripts/` that orchestrates API calls against a running backend and prints + (optionally) saves a JSON summary. Keep the core math helpers pure so they can be unit-tested.

**Tech Stack:** Python 3.10+, `httpx`, `asyncio`, stdlib.

## Notes / Constraints

- Corridor MCP tool is not available in this environment (no MCP servers/resources configured), so we cannot run Corridor security analysis as requested by `AGENTS.md`.
- Prefer API-level load testing (not internal function benchmarks) to capture real ingestion + retrieval + LLM latency.

## Approaches

1. **(Recommended) Python asyncio + httpx script**
   - Pros: zero new deps, consistent with existing scripts (`scripts/api_smoke.py`, `scripts/regression_gate.py`), easy to run in dev/prod.
   - Cons: not as feature-rich as Locust/k6 (no distributed runners, fewer charts).

2. **Locust scenario**
   - Pros: good concurrency control + reporting UI.
   - Cons: adds deps and operational complexity.

3. **k6 script**
   - Pros: stable, high-performance load generator.
   - Cons: adds a new runtime/tooling path (Go binary) and separate scripting language.

## Implementation Tasks

### Task 1: Add unit tests for percentile + summary helpers

**Files:**
- Create: `tests/test_rag_e2e_load_test.py`

**Step 1: Write the failing test**

- Add tests that:
  - assert `scripts/rag_e2e_load_test.py` exists
  - load the module by file path
  - verify `summarize_latencies_ms()` and `percentile_ms()` behavior on small fixed datasets

**Step 2: Run test to verify it fails**

Run: `python -m pytest -q tests/test_rag_e2e_load_test.py`

Expected: FAIL because `scripts/rag_e2e_load_test.py` does not exist yet.

### Task 2: Implement minimal helper functions (GREEN)

**Files:**
- Create: `scripts/rag_e2e_load_test.py`

**Step 1: Write minimal implementation**

- Implement pure helpers:
  - `percentile_ms(values_ms: list[int], p: int) -> int`
  - `summarize_latencies_ms(values_ms: list[int]) -> dict[str, int | float]` (count, min, max, mean, p50/p90/p95/p99)
  - `throughput_per_sec(count: int, elapsed_ms: int) -> float`

**Step 2: Run tests**

Run: `python -m pytest -q tests/test_rag_e2e_load_test.py`

Expected: PASS.

### Task 3: Implement the end-to-end load test runner

**Files:**
- Modify: `scripts/rag_e2e_load_test.py`

**Step 1: Ingest phase**

- Create dataset (`POST /datasets/`).
- Upload N documents (`POST /documents/upload`) with concurrency limit.
- Poll status until `completed`/`failed` (`GET /documents/{id}/status`).
- Record:
  - upload request latency
  - end-to-end ingestion latency (upload start -> completed)

**Step 2: Retrieve phase**

- Call retrieval-only endpoint (`POST /rag/retrieve-preview`) repeatedly with concurrency limit.
- Record request latency and success/error counts.

**Step 3: Answer phase**

- Call non-streaming chat (`POST /chat`) repeatedly with concurrency limit.
- Record request latency and success/error counts.

**Step 4: Output**

- Print per-phase summary (throughput + latency percentiles).
- Optionally write a JSON report under `runs/loadtest/` (timestamped) when `--out` is set.

### Task 4: Verification + docs/tracker

**Files:**
- Modify: `docs/plans/2026-02-06-seq-rag-improvements-tracker.md`

**Step 1: Run verification**

- Targeted: `python -m pytest -q tests/test_rag_e2e_load_test.py`
- Full: `python -m pytest -q`

**Step 2: Update tracker**

- Mark Task 26 as done.
- Set **Next Up** to Task 27.
- Add pointer to this plan doc.

**Step 3: Commit + merge + push**

- Commit on `feat/seq-rag-task26`.
- Merge (fast-forward) into `main`.
- `git push origin main`

