# Knowledge Asset Retention Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend retention coverage from audit logs and regression runs to archived/disabled knowledge assets, while reusing the existing document delete lifecycle so documents, chunks, KG rows, vectors, and object assets are purged through one bounded and auditable flow.

**Architecture:** Add a new retention helper in `app/services/retention_jobs.py` that plans eligible documents by tenant and cutoff, then optionally executes bounded deletion through `app.api.v1.documents._delete_document_lifecycle`. Expose the job in `scripts/run_retention_jobs.py` with safe defaults (`dry-run` unless `--execute`) and document CronJob/failure-handling guidance in deployment docs.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres, MinIO, vector store abstraction, Python CLI runners, pytest.

---

### Task 1: Add knowledge-asset retention service

**Files:**
- Modify: `app/services/retention_jobs.py`
- Test: `tests/test_retention_jobs_knowledge_assets.py`

**Step 1: Write the failing test**

```python
async def test_run_knowledge_asset_retention_dry_run(monkeypatch):
    from app.services import retention_jobs

    monkeypatch.setattr(retention_jobs, "plan_knowledge_asset_purge", lambda *_a, **_k: [...])
    monkeypatch.setattr(retention_jobs, "_delete_document_lifecycle", fail_if_called)

    out = await retention_jobs.run_knowledge_asset_retention(...)
    assert out["dry_run"] is True
    assert out["eligible"] == 2
    assert out["deleted"] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_retention_jobs_knowledge_assets.py -q`
Expected: FAIL because `run_knowledge_asset_retention` / planner helpers do not exist yet.

**Step 3: Write minimal implementation**

```python
def plan_knowledge_asset_purge(...): ...

async def run_knowledge_asset_retention(...):
    rows = plan_knowledge_asset_purge(...)
    if not dry_run:
        for row in rows:
            await _delete_document_lifecycle(...)
    audit_log_event(...)
    return summary
```

Include:
- tenant-scoped filtering
- bounded ordering by lifecycle timestamp
- support for `archived`, `disabled`, or `either`
- PII-safe audit summary + artifact coverage metadata

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_retention_jobs_knowledge_assets.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/retention_jobs.py tests/test_retention_jobs_knowledge_assets.py
git commit -m "feat: add knowledge asset retention job"
```

### Task 2: Expose the job through the retention runner and ops docs

**Files:**
- Modify: `scripts/run_retention_jobs.py`
- Modify: `docs/deployment/runbook.md`
- Modify: `docs/deployment/db_maintenance.md`
- Test: `tests/test_run_retention_jobs_cli.py`

**Step 1: Write the failing test**

```python
def test_run_retention_jobs_supports_knowledge_assets(monkeypatch):
    import scripts.run_retention_jobs as runner

    monkeypatch.setattr(runner, "run_knowledge_asset_retention", fake_job)
    rc = runner.main(["--knowledge-assets", "--tenant-id", str(TENANT_ID), "--dry-run"])
    assert rc == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_retention_jobs_cli.py -q`
Expected: FAIL because CLI flags / job dispatch are missing.

**Step 3: Write minimal implementation**

```python
p.add_argument("--knowledge-assets", action="store_true", help="Run archived/disabled document retention")
p.add_argument("--dataset-id", ...)
p.add_argument("--lifecycle-state", choices=["archived", "disabled", "either"], default="either")
...
if args.knowledge_assets:
    res = asyncio.run(run_knowledge_asset_retention(...))
```

Docs should describe:
- dry-run first
- tenant/all-tenant scope
- failure counting semantics (`conflicts`, `errors`)
- that actual asset cleanup is delegated to the document lifecycle

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_retention_jobs_cli.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/run_retention_jobs.py docs/deployment/runbook.md docs/deployment/db_maintenance.md tests/test_run_retention_jobs_cli.py
git commit -m "feat: expose knowledge asset retention runner"
```

### Task 3: Verify the bounded purge path

**Files:**
- Test: `tests/test_retention_jobs_knowledge_assets.py`
- Test: `tests/test_dataset_purge_endpoint.py`

**Step 1: Write the failing test**

```python
async def test_run_knowledge_asset_retention_executes_document_delete_lifecycle(...):
    ...
    assert deleted_ids == [...]
    assert out["artifact_scopes"] == ["documents", "chunks", "kg", "vectors", "object_assets"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_retention_jobs_knowledge_assets.py::test_run_knowledge_asset_retention_execute -q`
Expected: FAIL until summary / audit payload is wired correctly.

**Step 3: Write minimal implementation**

Make the execute path:
- call `_delete_document_lifecycle` with `enforce_permissions=False`
- count `deleted/not_found/denied/conflicts/errors`
- keep dry-run and execute summaries shape-stable

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_retention_jobs_knowledge_assets.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add app/services/retention_jobs.py tests/test_retention_jobs_knowledge_assets.py
git commit -m "test: verify knowledge asset purge path"
```

### Task 4: Final verification

**Files:**
- Modify: none (verification only)

**Step 1: Run focused tests**

Run:

```bash
pytest -q \
  tests/test_retention_jobs_audit_logs.py \
  tests/test_retention_jobs_regression_runs.py \
  tests/test_retention_jobs_knowledge_assets.py \
  tests/test_run_retention_jobs_cli.py \
  tests/test_dataset_purge_endpoint.py
```

Expected: PASS

**Step 2: Run lint on touched files**

Run:

```bash
ruff check \
  app/services/retention_jobs.py \
  scripts/run_retention_jobs.py \
  tests/test_retention_jobs_knowledge_assets.py \
  tests/test_run_retention_jobs_cli.py
```

Expected: PASS

**Step 3: Commit**

```bash
git add app/services/retention_jobs.py scripts/run_retention_jobs.py docs/deployment/runbook.md docs/deployment/db_maintenance.md tests/test_retention_jobs_knowledge_assets.py tests/test_run_retention_jobs_cli.py
git commit -m "feat: extend retention to knowledge assets"
```
