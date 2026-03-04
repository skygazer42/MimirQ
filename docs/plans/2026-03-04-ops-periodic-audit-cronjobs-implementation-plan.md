# Periodic Audit CronJobs (Index + Evidence Drift) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide bounded, PII-safe periodic jobs that run (1) dataset index-audit and (2) evidence reference drift audit, write a small summary to audit logs, and ship Helm CronJob templates + docs for production ops.

**Architecture:** Follow the existing “job helper + CLI runner” pattern used by `retention_jobs.py` and `stale_report_jobs.py`. Implement two tenant-scoped job helpers that:
- list target datasets in a bounded way (most-recently-updated first; optional explicit dataset_ids),
- run the existing bounded audits per dataset,
- aggregate into a small per-tenant summary (counts + top offenders only),
- optionally write exactly one audit log event per tenant per day (dedupe by `resource_id=YYYY-MM-DD`, with `--force` override).

Provide Helm `CronJob` templates that run the CLI runner inside the same image and load env from the chart’s Secret.

**Tech Stack:** Python (argparse + SQLAlchemy Session), FastAPI service helpers, pytest, Helm, Kubernetes CronJob.

---

### Task 1: Implement job helpers (service module)

**Files:**
- Create: `app/services/periodic_audit_jobs.py`
- Modify (optional): `app/services/index_audit_service.py` (only if needed to add an internal/system-safe entrypoint)

**Steps:**
1. Add helper `_dt_to_json(...)` and `_audit_already_written(...)` (copy pattern from `stale_report_jobs.py`).
2. Add `_list_dataset_ids(...)` (bounded + stable ordering).
3. Implement `run_daily_index_audit_report(...)`:
   - Inputs: `tenant_id`, `max_datasets`, `max_check_ids`, `milvus_list_limit`, `sample_limit`, `execute`, `force`, `now`
   - For each dataset, call the existing index audit logic and keep only safe fields.
   - Aggregate totals + “top N” datasets by issue severity; keep samples bounded.
   - If `execute`, write audit event `observability.index_audit.daily` with `resource_type="index_audit_report"`, `resource_id=<report_date>`.
4. Implement `run_daily_evidence_drift_audit_report(...)`:
   - List datasets that have non-archived evidence suites (bounded).
   - For each dataset, run dataset drift audit (bounded to 10k items per dataset like API).
   - Aggregate totals + reasons across datasets; keep bounded “top drift datasets”.
   - If `execute`, write audit event `evidence.drift_audit.daily` with `resource_type="evidence_drift_report"`, `resource_id=<report_date>`.

**Test-first:** write failing tests that monkeypatch the per-dataset audit calls and assert:
- bounded dataset iteration works,
- dedupe behavior skips when already written (unless `force`),
- audit payload is PII-safe (no raw content fields; ids + counts only),
- event action/resource keys are stable.

---

### Task 2: Add CLI runner script (CronJob-friendly)

**Files:**
- Create: `scripts/run_periodic_audit_jobs.py`

**Steps:**
1. Follow the structure of `scripts/run_retention_jobs.py`.
2. Support:
   - `--index-audit` and/or `--evidence-drift-audit`
   - scope: `--tenant-id` / `--all-tenants` / default tenant
   - mode: `--dry-run` (default) vs `--execute`
   - bounds: `--max-datasets`, plus per-audit bounds (`--max-check-ids`, `--milvus-list-limit`, `--sample-limit`, `--details-limit`, `--slice-top-n`)
   - `--force` to bypass daily dedupe
3. Output a single JSON blob for automation logs: `{"ok": bool, "ran_at": "...", "results": [...]}`.

---

### Task 3: Tests for job helpers

**Files:**
- Create: `tests/test_periodic_audit_jobs.py`

**Steps:**
1. Unit-test the dedupe logic by inserting a fake `AuditLog` row (or monkeypatching the query helper).
2. Unit-test both reports with monkeypatched dataset listing + audit runner to avoid DB/vector dependencies.
3. Verify summaries are bounded: top lists capped, no unbounded payload growth.

Run: `pytest tests/test_periodic_audit_jobs.py -v`

---

### Task 4: Helm CronJob templates + values

**Files:**
- Create: `deploy/helm/mimirq/templates/cronjob-index-audit.yaml`
- Create: `deploy/helm/mimirq/templates/cronjob-evidence-drift-audit.yaml`
- Modify: `deploy/helm/mimirq/values.yaml`

**Template behavior:**
- Gated by values, default disabled.
- Uses the same image + `envFrom.secretRef` as api/worker deployments.
- Reasonable defaults: `concurrencyPolicy: Forbid`, small history limits, `restartPolicy: Never`.
- Command example:
  - `python scripts/run_periodic_audit_jobs.py --index-audit --all-tenants --execute --max-datasets 50`

---

### Task 5: Docs updates

**Files:**
- Modify: `docs/deployment/runbook.md`

**Steps:**
- Add a small “Periodic audits (CronJob)” section:
  - how to run the scripts manually (dry-run + execute)
  - what audit actions to search for in `/api/v1/audit/logs`
  - recommended schedules + bounds.

---

### Task 6: Verify and land

**Steps:**
- Run: `make enterprise-checks`
- Update issue status: `bd close MimirQ-eh26.35`
- Sync + push:
  - `git pull --rebase origin main`
  - `bd sync`
  - `git push`
  - `git status` (must show up-to-date)

