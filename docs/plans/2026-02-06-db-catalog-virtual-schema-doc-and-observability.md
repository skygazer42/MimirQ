# DB Catalog Virtual Schema Doc + Observability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** After each DB catalog sync, generate a digest-only “virtual schema document” (tables/columns + safe aggregates) and index it into the existing vector/BM25 pipeline; add first-class observability for catalog sync + schema doc generation.

**Architecture:** Add a small service that (1) reads `db_catalog_*` tables, (2) renders a deterministic markdown document with strong structure (headings per table/column), and (3) upserts a stable “virtual” `documents` row + `document_parsed_contents`, then reindexes chunks via the existing `Indexer`. Extend the DB catalog connector execution path to call this service and log structured metrics.

**Tech Stack:** FastAPI background tasks, SQLAlchemy, existing `Indexer` (vector + BM25), LangChain `Document` + existing chunkers, JSONL `log_metrics`.

---

### Task 1: Add renderer for digest-only virtual schema markdown

**Files:**
- Create: `app/services/db_catalog_schema_doc_service.py`
- Test: `tests/test_db_catalog_schema_doc_renderer.py`

**Step 1: Write failing tests (renderer output shape + safety)**

```python
from app.services.db_catalog_schema_doc_service import render_virtual_schema_markdown

def test_render_virtual_schema_markdown_includes_tables_and_columns():
    md = render_virtual_schema_markdown(
        dataset_id="00000000-0000-0000-0000-000000000000",
        tables=[
            {
                "engine": "mysql",
                "db_name": "demo",
                "schema_name": None,
                "table_name": "users",
                "table_type": "table",
                "comment": "user table",
                "columns": [
                    {"ordinal": 1, "name": "id", "data_type": "int", "nullable": False, "comment": None},
                    {"ordinal": 2, "name": "email", "data_type": "varchar", "nullable": True, "comment": None},
                ],
                "profile": {"row_count_estimate": 123},
            }
        ],
        generated_at_iso="2026-02-06T00:00:00+00:00",
    )
    assert "# Virtual DB Schema" in md
    assert "## demo.users" in md
    assert "`id`" in md and "`email`" in md
    assert "row_count_estimate" in md

def test_render_virtual_schema_markdown_is_digest_only_no_raw_values():
    md = render_virtual_schema_markdown(
        dataset_id="00000000-0000-0000-0000-000000000000",
        tables=[
            {
                "engine": "mysql",
                "db_name": "demo",
                "schema_name": None,
                "table_name": "t",
                "table_type": "table",
                "comment": None,
                "columns": [{"ordinal": 1, "name": "ssn", "data_type": "varchar", "nullable": True, "comment": None}],
                "profile": {"sample_values": ["123-45-6789"]},
            }
        ],
        generated_at_iso="2026-02-06T00:00:00+00:00",
    )
    assert "123-45-6789" not in md
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_db_catalog_schema_doc_renderer.py -q`
Expected: FAIL (module/function missing)

**Step 3: Implement minimal renderer**

- Deterministic ordering: engine/db/schema/table/ordinal/name.
- Markdown structure:
  - H1 document header
  - Per table: H2 `db.schema.table` (or `db.table`)
  - Column list as a markdown table (name/type/nullable/comment)
  - “Safe profile” section: only allowlisted keys (e.g. `row_count_estimate`) to avoid leaking raw values.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db_catalog_schema_doc_renderer.py -q`
Expected: PASS

---

### Task 2: Upsert a stable virtual schema Document and (re)index it

**Files:**
- Modify: `app/services/db_catalog_schema_doc_service.py`
- (Optional integration test): `tests/test_db_catalog_schema_doc_upsert_integration.py`

**Step 1: Write failing unit tests for “virtual doc identity” helpers**

- Add a helper like `virtual_schema_file_path(dataset_id)` returning `virtual://db_catalog/schema/<dataset_id>`.
- Test that it is stable and does not include secrets/config.

**Step 2: Implement document upsert + reindex**

Implement a service function:

- Inputs: `db`, `tenant_id`, `dataset_id`, `requested_by`, and optional `connector_run_id`
- Query `DbCatalogTable` + `DbCatalogColumn` (+ latest `DbProfileSnapshot` per table, best-effort)
- Render markdown via Task 1 renderer
- Upsert `documents` row:
  - `file_type="md"`, `filename="db_schema_<dataset_id>.md"`, `file_path=virtual://...`
  - `status="completed"`, `current_stage="completed"`, `processed_at=now`
  - `doc_metadata` includes `doc_type_kwd="db_schema"`, `source="db_catalog"`, `virtual_schema=true`
- Upsert `document_parsed_contents` with the markdown content
- Delete old `document_chunks` rows for that document + call `Indexer(db).delete_chunk_indexes(...)`
- Chunk markdown using an existing markdown-aware chunker (e.g. `markdown_outline`)
- Call `Indexer(db).index_chunks(...)` to write new chunks + update BM25/vector

**Step 3: Add integration test (skipped by default)**

If `MIMIRQ_INTEGRATION_TESTS=1`, validate:
- Running upsert creates exactly one virtual schema document per dataset
- Re-running updates same document id and replaces chunks

---

### Task 3: Wire schema doc generation into DB catalog connector execution + add observability

**Files:**
- Modify: `app/api/v1/connectors.py`
- Modify (optional): `app/connectors/db/catalog_runner.py`

**Step 1: Write failing tests for metrics emission helpers (unit)**

Extract a small helper that takes `connector_id`, `dataset_id`, `elapsed_sec`, `result`, `success`, `error` and calls `log_metrics`.

**Step 2: Implement wiring**

In `_execute_db_catalog_run`:
- Measure elapsed time for catalog sync and schema doc generation separately
- On success:
  - `log_metrics` event `db_catalog.sync.completed` with counts + elapsed
  - Generate schema doc + index; `log_metrics` event `db_catalog.schema_doc.completed` with doc_id/chunk_count/elapsed
- On failure:
  - `log_metrics` event `db_catalog.sync.failed` with error class/message

Also ensure metrics context includes `tenant_id`, `dataset_id`, `connector_id`, `run_id`.

**Step 3: Run relevant unit tests**

Run: `pytest -q`
Expected: PASS

