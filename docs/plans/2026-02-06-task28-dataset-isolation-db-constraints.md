# Task 28: Dataset Isolation DB Constraints (Unique / FK / Composite Index) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enforce dataset isolation at the database layer by requiring dataset-scoped rows to reference a dataset within the same tenant, via composite unique indexes + composite foreign keys, plus the hot-path composite indexes.

**Architecture:** Use SQLAlchemy model constraints so new deployments get the correct schema from `Base.metadata.create_all()`. For existing PostgreSQL databases, extend `app/core/migrations.py` with best-effort DDL (unique indexes first, then `ALTER TABLE ... ADD CONSTRAINT` composite FKs) to harden schemas without requiring Alembic.

**Tech Stack:** FastAPI, SQLAlchemy ORM, PostgreSQL, runtime migrations (`app/core/migrations.py`).

## Notes / Constraints

- Corridor MCP tool is not available in this environment (no MCP servers/resources configured), so we cannot run Corridor security analysis as requested by `AGENTS.md`.
- `apply_runtime_migrations()` is **PostgreSQL-only** and **best-effort** (errors ignored). Model-level constraints remain the source of truth for fresh DBs.
- Composite FKs that include `tenant_id` cannot use `ON DELETE SET NULL` because `tenant_id` is `NOT NULL`. Prefer `CASCADE` for dataset-owned tables; keep `RESTRICT/NO ACTION` semantics where we explicitly do not want implicit deletes (e.g., `documents`).

## Approaches

1. **(Recommended) Composite FKs for dataset-owned tables**
   - Add `UNIQUE (tenant_id, id)` on `datasets` and use `FOREIGN KEY (tenant_id, dataset_id) -> datasets(tenant_id, id)` for dataset-owned tables (permissions/configs/runs/scans/catalog/docs).
   - Pros: strong tenant+dataset isolation; minimal behavior change; aligns with Task 28 wording.
   - Cons: requires touching multiple models + best-effort runtime DDL for existing DBs.

2. Single-column FKs + application checks
   - Pros: smaller change.
   - Cons: does not guarantee tenant isolation at DB layer (main objective of Task 28).

## Implementation Tasks

### Task 1: Tests first (RED)

**Files:**
- Add: `tests/test_task28_dataset_isolation_db_constraints.py`

**Step 1: Write failing tests**

- Assert `datasets` has `UNIQUE (tenant_id, id)` and `UNIQUE (tenant_id, name)`.
- Assert dataset-scoped tables have composite FK `(tenant_id, dataset_id)` referencing `datasets(tenant_id, id)`:
  - `dataset_permissions`
  - `connector_configs`
  - `connector_runs`
  - `db_catalog_tables`
  - `dataset_profile_scan_runs`
  - `dataset_precheck_scan_runs`
  - `documents` (nullable `dataset_id` is allowed; constraint enforces when non-null)
- Assert dataset category memberships are tenant-safe with composite FKs:
  - `(tenant_id, dataset_id) -> datasets(tenant_id, id)`
  - `(tenant_id, category_id) -> dataset_categories(tenant_id, id)`
- Assert dataset category parent linkage is tenant-safe:
  - `(tenant_id, parent_id) -> dataset_categories(tenant_id, id)`

**Step 2: Run tests to confirm failures**

Run: `PYTHONPATH=. python -m pytest -q tests/test_task28_dataset_isolation_db_constraints.py`

Expected: FAIL because composite constraints are not implemented yet.

### Task 2: SQLAlchemy model constraints (GREEN)

**Files:**
- Modify: `app/models/dataset.py`
- Modify: `app/models/document.py`
- Modify: `app/models/connector_config.py`
- Modify: `app/models/connector.py`
- Modify: `app/models/db_catalog.py`
- Modify: `app/models/dataset_profile_scan.py`
- Modify: `app/models/dataset_precheck_scan.py`
- Modify: `app/models/dataset_category.py`

**Step 1: Add supporting unique constraints**

- `datasets`: add `UNIQUE (tenant_id, id)` and `UNIQUE (tenant_id, name)`.
- `dataset_categories`: add `UNIQUE (tenant_id, id)` to support composite references.

**Step 2: Replace single-column dataset FKs with composite FKs**

- Use `ForeignKeyConstraint(["tenant_id", "dataset_id"], ["datasets.tenant_id", "datasets.id"], ondelete=...)`.
- Keep column types/indexes the same; remove `ForeignKey("datasets.id", ...)` from `dataset_id` columns.

**Step 3: Tenant-safe category relationships**

- Replace `parent_id` single-column FK with composite FK on `(tenant_id, parent_id)`.
- Replace membership FKs with composite FKs on `(tenant_id, dataset_id)` and `(tenant_id, category_id)`.

**Step 4: Re-run unit tests**

Run: `PYTHONPATH=. python -m pytest -q tests/test_task28_dataset_isolation_db_constraints.py`

Expected: PASS.

### Task 3: Runtime migrations for existing Postgres DBs (GREEN)

**Files:**
- Modify: `app/core/migrations.py`

**Step 1: Add unique indexes required for composite FKs**

- `CREATE UNIQUE INDEX IF NOT EXISTS ix_datasets_tenant_id_id ON datasets (tenant_id, id);`
- `CREATE UNIQUE INDEX IF NOT EXISTS ix_datasets_tenant_name ON datasets (tenant_id, name);`
- `CREATE UNIQUE INDEX IF NOT EXISTS ix_dataset_categories_tenant_id_id ON dataset_categories (tenant_id, id);`

**Step 2: Add composite FK constraints (best-effort)**

- Add `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY (tenant_id, dataset_id) REFERENCES datasets (tenant_id, id)` for the dataset-owned tables listed above.
- Add tenant-safe category constraints:
  - `dataset_category_memberships (tenant_id, dataset_id) -> datasets (tenant_id, id)`
  - `dataset_category_memberships (tenant_id, category_id) -> dataset_categories (tenant_id, id)`
  - `dataset_categories (tenant_id, parent_id) -> dataset_categories (tenant_id, id)`

**Step 3: Add missing composite indexes (if any)**

- Ensure each dataset-owned table has a composite index `(tenant_id, dataset_id)` for common joins/filters.

### Task 4: API comment + behavior check

**Files:**
- Modify: `app/api/v1/datasets.py`

**Step 1: Update stale comment**

- Replace "Document.dataset_id is not a DB FK" comment with wording that DB enforces tenant+dataset consistency, while API check remains for friendly error messaging.

### Task 5: Verification + tracker + merge

**Files:**
- Modify: `docs/plans/2026-02-06-seq-rag-improvements-tracker.md`

**Step 1: Run verification**

- Targeted: `PYTHONPATH=. python -m pytest -q tests/test_task28_dataset_isolation_db_constraints.py`
- Full: `PYTHONPATH=. python -m pytest -q`

**Step 2: Update tracker**

- Mark Task 28 as done.
- Set **Next Up** to Task 29.
- Add pointer to this plan doc.

**Step 3: Commit + merge + push**

- Commit on `seq-rag-task28`.
- Fast-forward merge into `main`.
- `git push origin main`

