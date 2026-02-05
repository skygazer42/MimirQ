# MySQL + SQLServer Connectors & Data Catalog Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add enterprise-grade MySQL + SQLServer data connectors that ingest a searchable catalog (schemas/tables/columns + safe profiling) with strict permissions, auditability, and UI visibility of data distribution. No raw DB rows are ever sent to the LLM; only digests.

**Architecture:** ConnectorConfig/Run -> DB introspection + profiling -> catalog storage (Postgres) -> optional “virtual schema documents” indexed into Milvus/BM25 -> retrieval + (later) safe query execution -> digest-only egress -> audit-only SQL visibility.

**Tech Stack:** FastAPI, SQLAlchemy(Postgres), background tasks / queue (optional), Next.js 14, Tailwind/shadcn/ui.

---

## Hard Requirements (from product constraints)

- **Connectors:** support **MySQL + SQLServer** first.
- **Permissions:** **per-user / row-level** by default.
  - SQLServer: integrate with **RLS + `SESSION_CONTEXT`** (set per request).
  - MySQL: **view/role mapping**; allow execution with credentials chosen by `entitlement_hash` (role set), not per-user.
- **Caching:** profiling/stat caching may be keyed by `entitlement_hash` (acceptable).
- **LLM egress:** **digest-only**; never send raw rows to the LLM.
- **SQL visibility:** hidden by default; only visible in Audit/Observability for dataset owner + auditor role.

---

## Baseline Verification (run once before starting implementation)

Run:
```bash
pytest -q
cd web && pnpm -s lint && pnpm -s typecheck
```
Expected: PASS.

---

## Data Model (New Tables)

We will store catalog + profiling results in Postgres (new SQLAlchemy models). New tables are created automatically by `Base.metadata.create_all()` at startup.

Proposed models (minimal first iteration):
- `db_catalog_tables`
  - `tenant_id`, `dataset_id`, `connector_config_id`
  - `engine` (`mysql|sqlserver`)
  - `db_name`, `schema_name`, `table_name`, `table_type` (`table|view`)
  - `comment` (optional), `fingerprint` (stable hash)
  - `last_seen_at`
- `db_catalog_columns`
  - `table_id` FK, `ordinal`, `name`, `data_type`, `nullable`, `comment` (optional)
- `db_profile_snapshots`
  - `table_id` FK
  - `entitlement_hash` (string)
  - `profile` JSON (safe aggregates only)
  - `sample_meta` JSON (how it was computed; no raw rows)
  - `created_at`

---

## API Surface (New/Extended)

- Extend connector configs/runs to support new connector IDs:
  - `mysql_catalog`
  - `sqlserver_catalog`
- New dataset-scoped catalog endpoints:
  - `GET /api/v1/datasets/{dataset_id}/db-catalog/tables`
  - `GET /api/v1/datasets/{dataset_id}/db-catalog/tables/{table_id}`
  - `GET /api/v1/datasets/{dataset_id}/db-catalog/profiles?table_id=...` (scoped by entitlement_hash)

---

## Task Plan

### Task 1: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-05-mysql-sqlserver-connectors-and-catalog.md`

**Steps:**
1. Add the plan file (this document).
2. Commit.

**Commit:**
```bash
git add docs/plans/2026-02-05-mysql-sqlserver-connectors-and-catalog.md
git commit -m "docs(plans): add mysql/sqlserver connectors & catalog plan"
```

---

### Task 2: Add connector config schemas for MySQL and SQLServer (with secret handling)

**Files:**
- Modify: `app/api/schemas/connector.py`
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_connectors_endpoints.py`

**Step 1: Write failing tests**

Add to `tests/test_connectors_endpoints.py`:
```python
def test_connectors_accept_mysql_catalog_config(client, auth_headers):
    payload = {
        "connector_id": "mysql_catalog",
        "dataset_id": "00000000-0000-0000-0000-000000000000",
        "config": {
            "host": "localhost",
            "port": 3306,
            "database": "demo",
            "username": "svc",
            "password": "secret",
        },
    }
    res = client.post("/api/v1/connectors/runs", json=payload, headers=auth_headers)
    assert res.status_code in (201, 400)  # dataset permissions may block in unit env
```

**Step 2: Run test to verify it fails**
```bash
pytest -q tests/test_connectors_endpoints.py -k mysql_catalog
```
Expected: FAIL (unsupported connector_id).

**Step 3: Implement schemas + endpoint wiring**
- In `app/api/schemas/connector.py`, add:
  - `MySQLCatalogConnectorConfig`
  - `SQLServerCatalogConnectorConfig`
  - Include safe fields only; store passwords encrypted via `encrypt_connector_config_secrets()`.
- In `app/api/v1/connectors.py`, extend `create_connector_run()` to accept the new connector IDs and schedule background tasks.

**Step 4: Run tests**
```bash
pytest -q tests/test_connectors_endpoints.py -k 'mysql_catalog or sqlserver_catalog'
```
Expected: PASS (at least validation/unsupported env behavior is stable).

**Step 5: Commit**
```bash
git add app/api/schemas/connector.py app/api/v1/connectors.py tests/test_connectors_endpoints.py
git commit -m "feat(connectors): add mysql/sqlserver catalog connector configs"
```

---

### Task 3: Introduce catalog + profile storage models (Postgres)

**Files:**
- Create: `app/models/db_catalog.py`
- Modify: `app/models/__init__.py` (export for clarity)
- Modify: `app/main.py` (import model so `create_all()` sees it)
- Test: `tests/test_db_catalog_models_importable.py`

**Step 1: Write failing test**

`tests/test_db_catalog_models_importable.py`
```python
def test_db_catalog_models_importable():
    import app.models.db_catalog  # noqa: F401
```

**Step 2: Run to confirm fail**
```bash
pytest -q tests/test_db_catalog_models_importable.py
```
Expected: FAIL (module missing).

**Step 3: Implement models**
- Use UUID PKs.
- Ensure `tenant_id` + `dataset_id` indexed.
- Add a stable `fingerprint` column for (engine, db, schema, table) identity.

**Step 4: Run tests**
```bash
pytest -q tests/test_db_catalog_models_importable.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/models/db_catalog.py app/main.py app/models/__init__.py tests/test_db_catalog_models_importable.py
git commit -m "feat(catalog): add db catalog + profile models"
```

---

### Task 4: Implement DB introspection helpers (no network tests yet)

**Files:**
- Create: `app/connectors/db/introspection.py`
- Test: `tests/test_db_introspection_sql_generation.py`

**Step 1: Write failing test**

`tests/test_db_introspection_sql_generation.py`
```python
from app.connectors.db.introspection import mysql_list_tables_sql, sqlserver_list_tables_sql


def test_mysql_introspection_sql_is_select_only():
    sql = mysql_list_tables_sql(database="demo")
    assert "select" in sql.lower()
    assert ";" not in sql


def test_sqlserver_introspection_sql_is_select_only():
    sql = sqlserver_list_tables_sql(database="demo")
    assert "select" in sql.lower()
    assert ";" not in sql
```

**Step 2: Run failing test**
```bash
pytest -q tests/test_db_introspection_sql_generation.py
```
Expected: FAIL (module missing).

**Step 3: Implement minimal helpers**
- Return parameterized SQL templates only (no string interpolation of identifiers beyond allowlisted patterns).
- Keep output semicolon-free to simplify downstream validators.

**Step 4: Run test**
```bash
pytest -q tests/test_db_introspection_sql_generation.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/connectors/db/introspection.py tests/test_db_introspection_sql_generation.py
git commit -m "feat(catalog): add mysql/sqlserver introspection SQL helpers"
```

---

### Task 5: Implement connector run executors that populate catalog tables (stubbed DB access)

**Files:**
- Create: `app/connectors/db/catalog_runner.py`
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_db_catalog_runner_calls_introspection.py`

**Step 1: Write failing test (using monkeypatch)**

`tests/test_db_catalog_runner_calls_introspection.py`
```python
import uuid


def test_catalog_runner_calls_introspection(monkeypatch):
    from app.connectors.db import catalog_runner

    called = {"mysql": 0, "sqlserver": 0}

    def _fake_mysql(*_a, **_k):
        called["mysql"] += 1
        return []

    def _fake_sqlserver(*_a, **_k):
        called["sqlserver"] += 1
        return []

    monkeypatch.setattr(catalog_runner, "_introspect_mysql", _fake_mysql, raising=False)
    monkeypatch.setattr(catalog_runner, "_introspect_sqlserver", _fake_sqlserver, raising=False)

    catalog_runner.run_catalog_sync(
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        connector_id="mysql_catalog",
        config={"host": "x"},
    )
    assert called["mysql"] == 1
```

**Step 2: Run failing test**
```bash
pytest -q tests/test_db_catalog_runner_calls_introspection.py
```
Expected: FAIL (module missing).

**Step 3: Implement runner skeleton**
- `run_catalog_sync(...)` chooses implementation by connector_id.
- No DB network calls yet; it just demonstrates wiring + metrics structure.

**Step 4: Run test**
```bash
pytest -q tests/test_db_catalog_runner_calls_introspection.py
```
Expected: PASS.

**Step 5: Commit**
```bash
git add app/connectors/db/catalog_runner.py app/api/v1/connectors.py tests/test_db_catalog_runner_calls_introspection.py
git commit -m "feat(connectors): add db catalog runner wiring (stub)"
```

---

### Task 6: Add catalog read endpoints (tables + profiles) and UI stub

**Files:**
- Create: `app/api/v1/db_catalog.py`
- Modify: `app/api/v1/__init__.py`
- Create: `web/app/datasets/[id]/db-catalog/page.tsx` (or place under existing dataset detail)
- Modify: `web/lib/api-client.ts`
- Test: `tests/test_db_catalog_endpoints_contract.py`

**Notes:**
- Enforce dataset membership permission.
- For profiles: accept `entitlement_hash` and enforce it matches the caller’s current entitlement (future work).

---

### Task 7: Add “virtual schema documents” indexing (optional, behind a flag)

**Why:** Makes table/column knowledge retrievable via the existing RAG pipeline without exposing rows.

**Approach:**
- For each table, create a virtual document with content like:
  - table name + comment
  - list of columns: name, type, comment
  - profile digest summary (safe aggregates)
- Index these into Milvus/BM25 with metadata: engine/db/schema/table/fingerprint/entitlement_hash.

---

### Task 8: Observability + Audit hooks

- Record connector runs, errors, and elapsed time.
- In audit log: record that a catalog sync ran and which connector config was used (redacted).
- In metrics: counts of catalog tables/columns, latest sync time, profile snapshot counts.

