# Connector Sync Lifecycle Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Introduce a shared connector sync-state foundation so saved connector configs can persist checkpoint state consistently and selected connectors can resume from `_state.cursor` instead of always restarting from zero.

**Architecture:** Extract pure sync-state helpers into a small service module so the lifecycle rules are testable without importing the heavy connector API module. Then wire `app/api/v1/connectors.py` to consume that module in three places: connector capability declaration, run->config state persistence, and bounded cursor resume for connector executors that already emit `cursor` stats (`web_crawl`, `github_repo`, `drive_files`, `minio_bucket`). Keep the external API shape stable for this slice; focus on shared state semantics first, not a new UI contract.

**Tech Stack:** Python, FastAPI, SQLAlchemy ORM objects, pytest.

---

### Task 1: Add pure connector sync-state helpers

**Files:**
- Create: `app/services/connector_sync_state.py`
- Test: `tests/test_connector_sync_state.py`

**Steps:**
1. Write failing tests for:
   - extracting a non-negative resume cursor from `_state`
   - slicing a listed item sequence by cursor
   - building persisted config state from run stats for `url_batch`, `web_crawl`, `github_repo`, `drive_files`, `minio_bucket`, `confluence_space`
2. Implement:
   - `ConnectorSyncPolicy` dataclass
   - registry keyed by `connector_id`
   - `get_resume_cursor(...)`
   - `slice_items_from_cursor(...)`
   - `build_persisted_state(...)`
3. Keep helpers pure and bounded; no DB/session imports.

Run: `pytest tests/test_connector_sync_state.py -q`

---

### Task 2: Wire connector state persistence through the shared helper

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_confluence_connector_unit.py`

**Steps:**
1. Write a failing integration test showing `_sync_connector_config_from_run(...)` persists `cursor` for a non-Confluence connector (for example `github_repo`) and still preserves existing Confluence `last_modified` behavior.
2. Update `connectors.py` so `_sync_connector_config_from_run(...)` delegates connector-specific state extraction to `build_persisted_state(...)`.
3. Keep `last_error` / `last_run_at` semantics unchanged.

Run: `pytest tests/test_confluence_connector_unit.py -q`

---

### Task 3: Apply shared cursor resume to selected connector executors

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_connector_sync_state.py`

**Steps:**
1. Write failing helper-level tests for sequence slicing that describe resume semantics.
2. Update executor flows to read `_state.cursor` and resume from that index for:
   - `web_crawl`
   - `github_repo`
   - `drive_files`
   - `minio_bucket`
3. Add small stats fields where useful (`cursor_in`, `resumed_from_state`, or equivalent) only if needed for operator clarity; do not expand the public schema unnecessarily.
4. Ensure cursor application is bounded and fail-safe: invalid state must fall back to zero.

Run: `pytest tests/test_connector_sync_state.py -q`

---

### Task 4: Refactor connector registry usage without changing API shape

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_connectors_endpoints.py`

**Steps:**
1. Keep `/api/v1/connectors` response shape unchanged.
2. Replace duplicated capability declarations with a shared internal registry or helper-backed construction so lifecycle support is defined once.
3. Add/adjust tests only if the list ordering or capability values change.

Run: `pytest tests/test_connectors_endpoints.py -q`

---

### Task 5: Verify and land

**Steps:**
1. Run focused tests:
   - `pytest tests/test_connector_sync_state.py tests/test_confluence_connector_unit.py tests/test_connectors_endpoints.py -q`
2. Run one broader connector slice if the focused tests are green:
   - `pytest tests/test_connector_schedule_due.py tests/test_connector_run_retry_resume.py -q`
3. Update issue status:
   - `bd close MimirQ-4ey9`
4. Sync + push:
   - `git pull --rebase`
   - `bd sync`
   - `git push`
   - `git status`
