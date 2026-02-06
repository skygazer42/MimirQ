# Pipeline Provenance + Version Diff Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make preprocessing/ingestion pipeline runs reproducible by recording per-step transform hashes, and provide an API (+ lightweight UI) to diff two document pipeline versions.

**Architecture:** Persist a small per-`pipeline_hash` provenance snapshot in `documents.metadata` (JSONB), keyed by pipeline version. Expose a version diff endpoint that compares chunk multisets by `content_hash` and returns counts + provenance deltas, without shipping large text blobs.

**Tech Stack:** FastAPI, SQLAlchemy, Postgres JSONB (best-effort fallbacks), Next.js/React (existing admin UI).

## Task 1: Add Provenance/Hashing Helper

**Files:**
- Create: `app/services/pipeline_provenance_service.py`
- Test: `tests/test_pipeline_provenance_service.py`

**Steps:**
1. Write failing unit test for canonical hashing and upsert/cap behaviour (max versions).
2. Implement `canonical_json_sha256()` + `build_pipeline_transform_snapshot()` + `upsert_pipeline_provenance_version()`.
3. Run: `pytest tests/test_pipeline_provenance_service.py -q`

## Task 2: Persist Provenance During Ingestion

**Files:**
- Modify: `app/parsing/processors/processor.py`
- Test: `tests/test_pipeline_provenance_persisted_on_complete.py`

**Steps:**
1. Write failing test by simulating doc metadata patch and verifying provenance entry is stored for the current `pipeline_hash`.
2. Add best-effort provenance write to the completion metadata patch (do not fail ingest on provenance errors).
3. Run: `pytest tests/test_pipeline_provenance_persisted_on_complete.py -q`

## Task 3: Document Version Diff Endpoint

**Files:**
- Modify: `app/api/v1/documents.py`
- Modify: `app/api/schemas/document.py`
- Test: `tests/test_document_version_diff_integration.py`

**Steps:**
1. Write failing integration test for `/documents/{id}/versions/diff`.
2. Implement endpoint:
   - validate `from`/`to` hashes
   - permission checks
   - compute chunk multiset diff using `DocumentChunk.metadata.content_hash` (fallback to chunk id when missing)
   - attach provenance snapshots when present
3. Run: `pytest tests/test_document_version_diff_integration.py -q`

## Task 4: Lightweight UI Exposure (Ops)

**Files:**
- Modify: `web/lib/api-client.ts`
- Modify: `web/types/index.ts`
- Modify: `web/components/ingestion/ingestion-detail-dialog.tsx`

**Steps:**
1. Add `documentApi.diffVersions(...)` client + types.
2. Add a “版本对比” section:
   - load version list
   - select from/to
   - render counts + changed transform hashes (if present)
3. Run: `pnpm -C web run typecheck`

## Task 5: Verify

**Steps:**
1. Run targeted tests: `pytest -q`
2. Run web typecheck: `pnpm -C web run typecheck`

