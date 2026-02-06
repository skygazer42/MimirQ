# Task 27: Task Queueization (Parsing / Re-embed / Sync) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure long-running ingestion “sync” work (connector runs) executes via the Arq task queue when enabled, with per-tenant concurrency limits, best-effort cancellation, and resumability (checkpointed progress).

**Architecture:** Keep API behavior the same, but when `TASK_QUEUE_ENABLED=true`, enqueue connector-run jobs and store `ConnectorRun.task_id`. Worker executes a single `connector_run_job` that dispatches to the existing per-connector executors. Make URL-batch execution idempotent/resumable using `run.stats.cursor` + `ConnectorRunDocument` mappings to avoid duplicating already-processed URLs after retries/restarts.

**Tech Stack:** FastAPI, SQLAlchemy, Arq (Redis), existing `app/tasks/*` helpers.

## Notes / Constraints

- Corridor MCP tool is not available in this environment (no MCP servers/resources configured), so we cannot run Corridor security analysis as requested by `AGENTS.md`.
- Task queue is optional: keep compatibility when `TASK_QUEUE_ENABLED=false`.

## Approaches

1. **(Recommended) Add connector run job to Arq**
   - Pros: minimal changes, uses existing queue infra (`app/tasks/queue.py`, `app/tasks/jobs.py`), works with current deployment model.
   - Cons: connector executors currently live in `app/api/v1/connectors.py` (worker imports API module).

2. Extract connector executors into `app/services/connectors/*`
   - Pros: cleaner layering, worker doesn’t depend on API router module.
   - Cons: larger refactor; higher regression risk for Task 27.

## Implementation Tasks

### Task 1: Tests first (RED)

**Files:**
- Modify: `tests/test_connectors_endpoints.py`
- Modify: `tests/test_connector_run_retry_resume.py`
- Add: `tests/test_connector_run_queueing.py`

**Step 1: Write failing tests**

- Queue enabled: `POST /api/v1/connectors/runs` should set `task_id` (by calling an enqueue helper) instead of relying solely on `BackgroundTasks`.
- Resume safety: URL-batch executor should not reset `cursor` to 0 when a run already has progress.
- Idempotency: if a URL already has a `ConnectorRunDocument` row for the run, the executor should skip re-ingesting it on retry/resume.

**Step 2: Run tests to confirm failures**

Run: `python -m pytest -q tests/test_connector_run_queueing.py`

Expected: FAIL because queue wiring/resume semantics aren’t implemented yet.

### Task 2: Queue plumbing (GREEN)

**Files:**
- Modify: `app/tasks/queue.py`
- Modify: `app/tasks/jobs.py`
- Modify: `app/tasks/worker.py`
- Modify: `app/core/config.py`

**Step 1: Add enqueue helper**

- Add `enqueue_connector_run(...) -> Optional[str]` to `app/tasks/queue.py`.

**Step 2: Add worker job**

- Add `connector_run_job(ctx, tenant_id, run_id, requested_by)` to `app/tasks/jobs.py`.
- Apply per-tenant concurrency limit using Redis semaphore (`tenant_acquire`) with a new setting (e.g. `TASK_TENANT_MAX_CONCURRENCY_CONNECTOR`).

**Step 3: Register job**

- Add `connector_run_job` to `app/tasks/worker.py` functions list.

### Task 3: API wiring (GREEN)

**Files:**
- Modify: `app/api/v1/connectors.py`

**Step 1: Create run**

- When `TASK_QUEUE_ENABLED=true`, enqueue connector run and set `ConnectorRun.task_id`.
- Fallback to `BackgroundTasks` when queue is disabled.

**Step 2: Retry-failed / resume**

- Same behavior: create a new run, then enqueue when queue enabled (otherwise background task).

**Step 3: Cancel**

- Keep DB status flip to `cancelled`.
- When queue enabled and `run.task_id` exists, best-effort `arq.jobs.Job(...).abort()` (similar to document cancel).

### Task 4: Resumability for url_batch executor

**Files:**
- Modify: `app/api/v1/connectors.py` (`_execute_url_batch_run`)

**Step 1: Respect existing cursor**

- If `run.stats.cursor > 0`, start from that index, don’t reset counters blindly.

**Step 2: Skip already-processed URLs**

- If a URL already exists in `ConnectorRun.documents` (source_ref match), skip ingestion and advance cursor.

### Task 5: Verification + tracker + merge

**Files:**
- Modify: `docs/plans/2026-02-06-seq-rag-improvements-tracker.md`

**Step 1: Run verification**

- Targeted: `python -m pytest -q tests/test_connector_run_queueing.py`
- Full: `python -m pytest -q`

**Step 2: Update tracker**

- Mark Task 27 as done.
- Set **Next Up** to Task 28.
- Add pointer to this plan doc.

**Step 3: Commit + merge + push**

- Commit on `feat/seq-rag-task27`.
- Fast-forward merge into `main`.
- `git push origin main`

