# Task Queue Ops

This guide documents the single-node task queue observability additions for background jobs.

## Job Result Envelope

Worker jobs now return a stable envelope with `schema = mimirq.task_job_result.v1`.

Common fields:

- `job_name`
- `ok`
- `reason`
- `elapsed_sec`
- `finished_at`
- `progress`

Scope fields are attached when available:

- `tenant_id`
- `dataset_id`
- `document_id`
- `run_id`
- `scan_run_id`
- `suite_id`
- `connector_id`

When a job is skipped because an idempotency lock is already held, the payload keeps `ok=true` and records:

- `reason = "locked"`
- `skipped = "locked"`
- `progress.stage = "locked"`

This keeps retry/skip behavior machine-readable for the API layer and for operators.

## Observability Snapshot

Admin endpoint:

`GET /api/v1/observability/task-queue/snapshot`

Snapshot fields include:

- broker health
- queue depth
- active worker count from heartbeat registry
- heartbeat interval / TTL
- `recent_job_outcomes`: bounded recent job results captured from workers

`recent_job_outcomes` is best-effort. It is intended for single-node operations debugging, not for durable audit storage.

## Operational Notes

- Redis locks still act as the idempotency guardrail for repeated submissions.
- Tenant and dataset semaphores remain the concurrency limiter for document / KG-heavy jobs.
- The snapshot is intentionally bounded and PII-safe enough for admin dashboards: it carries ids, reason codes, and progress metadata, but not raw document content.
