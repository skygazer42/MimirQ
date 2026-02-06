# Task 17: Table/Schema Specialized Chunks (TAG + Virtual Schema Doc)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure table-like data is handled by TAG (structured table store) while DB schemas are indexed via a digest-only “virtual schema document” (structure + safe aggregates only).

**Architecture:** Leverage the existing ingestion short-circuit for `.csv/.xls/.xlsx` into `table_store` (TAG) plus the existing DB catalog “virtual schema doc” generator/indexer. Close gaps by making routing decisions auditable and ensuring the virtual schema doc remains digest-only (no raw values). Avoid schema migrations by using document/chunk JSON metadata.

**Tech Stack:** Python, FastAPI ingestion pipeline, SQLAlchemy, existing `table_store_service` + `table_routing`, existing `db_catalog_schema_doc_service`.

**Status:** DONE (2026-02-06)

## What Already Exists (Observed)

- TAG ingestion path for table-like files behind pipeline flags (`table_store_enabled`, optional `table_store_auto_route`) in `app/parsing/processors/processor.py`.
- Digest-only virtual schema doc generator/indexer created earlier in `app/services/db_catalog_schema_doc_service.py` and wired into DB catalog execution.

## Open Decision (Confirm With Product/Owner)

- Default policy: keep TAG for tables as opt-in (current), or enable auto-route by default for table-like files.

## Task 1: Verify “virtual schema doc” is digest-only and stable

**Files:**
- Review: `app/services/db_catalog_schema_doc_service.py`
- Tests (should already exist): `tests/test_db_catalog_schema_doc_renderer.py`, `tests/test_db_catalog_schema_diff.py`

**Steps:**
1. Run: `python -m pytest -q tests/test_db_catalog_schema_doc_renderer.py tests/test_db_catalog_schema_diff.py`
2. Confirm renderer allowlists only safe profile keys and never includes sample/raw values.

## Task 2: Make TAG routing auditable + inspectable

**Files:**
- Review/modify: `app/parsing/processors/processor.py`
- Review/modify: `app/services/table_routing.py`
- (Optional) API/UI: `app/api/v1/documents.py`, `web/components/ingestion/ingestion-detail-dialog.tsx`
- Test: `tests/test_table_routing_decision_persisted.py` (new if gaps found)

**Steps:**
1. Ensure routing decision is persisted into `documents.doc_metadata.table_routing` with `route/reason/stats`.
2. Ensure TAG-imported docs are clearly labeled for downstream retrieval/UI (e.g., `parser_backend="table_store"`, `chunk_strategy="none"`).
3. Add a small UI surface to show routing decision and table_store summary in the ingestion detail dialog if not already present.

## Task 3 (Optional): Default-on auto-routing for table-like files

**Goal:** When enabled, large/complex tables go TAG; small tables stay RAG.

**Files:**
- Modify: `app/services/pipeline_config.py` (default resolution)
- Modify: `app/core/config.py` (settings default, if needed)
- Test: `tests/test_pipeline_effective_table_defaults.py`

**Steps:**
1. Decide desired default (global env default vs. per-dataset profile).
2. Add tests asserting the default behavior for `.csv/.xls/.xlsx`.
3. Implement minimal logic to match the tests.

## Verify

Run:
- `python -m pytest -q`
- `pnpm -C web run typecheck`
