# Confluence Connector (MVP) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a `confluence_space` connector that ingests Confluence pages from a space into a dataset with bounded page limits, incremental cursor, retries, and secret encryption/redaction.

**Architecture:** API validates/normalizes config via Pydantic, encrypts secrets at rest, and dispatches runs to a background executor. The executor calls Confluence REST to list pages (full/incremental), then ingests each page via existing URL ingestion. Cursor/state is persisted back to saved connector configs.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, httpx, existing URL ingestion pipeline.

---

### Task 1: Add Connector Config Schema

**Files:**
- Modify: `app/api/schemas/connector.py`
- Test: `tests/test_connectors_endpoints.py`

**Step 1: Write failing test**

Add a unit test that creating a `confluence_space` run redacts `auth.token` in API output (same pattern as `web_crawl` test).

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_redacts_auth`
Expected: FAIL with "Unsupported connector_id" or schema error.

**Step 3: Implement schema**

Add `ConfluenceSpaceConnectorConfig` with fields:

```python
class ConfluenceSpaceConnectorConfig(BaseModel):
    base_url: str = Field(..., max_length=2000)
    space_key: str = Field(..., max_length=255)
    auth: Optional[WebCrawlAuthConfig] = None
    sync_mode: Literal["auto", "full", "incremental"] = "auto"
    max_pages: int = Field(default=50, ge=1, le=500)
    page_size: int = Field(default=25, ge=1, le=100)
    soft_delete: bool = False
    user_agent: Optional[str] = Field(default=None, max_length=200)
    parser_backend: str = Field(default="auto")
    chunk_strategy: str = Field(default="langchain_recursive")
    pipeline: Optional[DocumentPipelineOptions] = None
    access: Optional[DocumentAccessUpdateRequest] = None
```

Normalize:
- Trim `base_url` / `space_key`
- Ensure `base_url` starts with `http://` or `https://`

**Step 4: Run test**

Run: `pytest -q tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_redacts_auth`
Expected: Still failing until API accepts connector id.

**Step 5: Commit**

Run:
```bash
git add app/api/schemas/connector.py tests/test_connectors_endpoints.py
git commit -m "feat(connectors): add confluence_space config schema"
```

---

### Task 2: Register Connector in API Registry + Validation

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_connectors_endpoints.py`

**Step 1: Write failing test**

Extend `test_connectors_list_contains_url_batch` to assert `confluence_space` exists.

**Step 2: Run test**

Run: `pytest -q tests/test_connectors_endpoints.py::test_connectors_list_contains_url_batch`
Expected: FAIL because connector not listed.

**Step 3: Implement**

- Add to `list_connectors()` a `ConnectorInfo(id="confluence_space", ..., supports_incremental=True)`
- Extend `_validate_connector_schema()` to accept `"confluence_space"` and validate via `ConfluenceSpaceConnectorConfig`
- Extend `create_connector_run()` to accept `"confluence_space"` and encrypt secrets
- Add `"confluence_space"` to `url_connectors` sets in:
  - `create_connector_run`
  - `run_connector_config`
  - `scheduled_tick`

**Step 4: Run tests**

Run: `pytest -q tests/test_connectors_endpoints.py`
Expected: PASS for registry + create run redaction tests.

**Step 5: Commit**

```bash
git add app/api/v1/connectors.py tests/test_connectors_endpoints.py
git commit -m "feat(connectors): register confluence_space connector"
```

---

### Task 3: Add Worker Dispatch + Executor Skeleton

**Files:**
- Modify: `app/tasks/jobs.py`
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_task29_security_audit_defaults.py` (optional coverage) or a new unit test

**Step 1: Write failing test**

Add a minimal unit test that `connector_run_job` dispatch supports `"confluence_space"` by ensuring it does not hit `unsupported_connector_id` for that id (monkeypatch executor).

**Step 2: Run test (fail)**

Run: `pytest -q tests/test_connector_run_queueing.py::...` (or the new test)
Expected: FAIL because `"confluence_space"` is unsupported.

**Step 3: Implement**

- Add `async def _execute_confluence_space_run(...)` placeholder in `app/api/v1/connectors.py`
- Add dispatch branches in:
  - `create_connector_run` background task selection
  - `run_connector_config` background task selection
  - `app/tasks/jobs.py:connector_run_job`

**Step 4: Run test (pass)**

**Step 5: Commit**

```bash
git add app/tasks/jobs.py app/api/v1/connectors.py tests/<new test file>
git commit -m "feat(connectors): add confluence_space executor dispatch"
```

---

### Task 4: Implement Confluence Listing + Ingestion + Stats

**Files:**
- Modify: `app/api/v1/connectors.py`
- Modify: `app/api/v1/connectors.py` (state sync helper)
- Test: `tests/test_connectors_endpoints.py` (schema/run path)
- Test: add `tests/test_confluence_connector_unit.py` (new, http client mocked)

**Step 1: Write failing unit tests (no network)**

Create `tests/test_confluence_connector_unit.py` to cover:

- Building page URLs from `_links.base` + `_links.webui` keeps `/wiki` prefix.
- Incremental `cql` includes `lastmodified > "<cursor>"` and `ORDER BY lastmodified ASC`.
- `_sync_connector_config_from_run` persists `state.last_modified` for `confluence_space`.

**Step 2: Run failing tests**

Run: `pytest -q tests/test_confluence_connector_unit.py`
Expected: FAIL (helpers not implemented).

**Step 3: Implement**

In `_execute_confluence_space_run`:
- Decrypt config (`decrypt_connector_config_secrets`)
- Determine effective sync mode from `cfg["_state"]` + `sync_mode`
- Use `app.core.http_client.get_http_client_pool().request_with_retry(...)` for Confluence REST calls:
  - Full: `GET {api_base}/content` with `spaceKey`, `type=page`, `status=current`, `expand=version`, paging via `start/limit`
  - Incremental: `GET {api_base}/content/search` with `cql=...`, paging via `start/limit`
- For each page:
  - Build web URL (prefer response `_links.base` + result `_links.webui`)
  - Ingest via `_ingest_url_upload_request` with `fetch_headers=_build_auth_headers(cfg)`
  - Apply `_apply_document_access_from_config`
  - Patch `doc.doc_metadata["connector"]` with connector fields (do not touch pipeline_hash)
  - Create `ConnectorRunDocument(source_ref=page_id)`
- Update `run.stats` frequently:
  - `total_pages`, `processed_pages`, `cursor`, `created`, `failed`, `last_modified`
  - `errors`/`failed_urls` via `_append_connector_error`

Extend `_sync_connector_config_from_run`:
- When `connector_id == "confluence_space"`:
  - Persist `state["last_modified"]` from `run.stats["last_modified"]`
  - Persist `state["last_run_id"]`

**Step 4: Run tests**

Run: `pytest -q tests/test_confluence_connector_unit.py`
Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/v1/connectors.py tests/test_confluence_connector_unit.py
git commit -m "feat(connectors): implement confluence_space sync + cursor"
```

---

### Task 5: Implement Soft Delete (Best-Effort)

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_confluence_connector_unit.py`

**Step 1: Write failing test**

Add a unit test for the soft-delete selection logic:
- Given a set of observed page_ids, compute which documents (with matching doc_metadata.connector.page_id) should be disabled.

**Step 2: Implement**

In full sync when `soft_delete=true`:
- Query `documents` for the dataset where `doc_metadata["connector"]["connector_id"] == "confluence_space"` and `space_key/base_url` match.
- For missing page IDs: set `disabled_at = now` (best-effort).

**Step 3: Run tests**

Run: `pytest -q tests/test_confluence_connector_unit.py`

**Step 4: Commit**

```bash
git add app/api/v1/connectors.py tests/test_confluence_connector_unit.py
git commit -m "feat(connectors): confluence_space soft-delete (full sync)"
```

---

### Task 6: Quality Gates + Close Issue

**Files:**
- Modify: `.beads/issues.jsonl` (bd close)

**Step 1: Run quality gates**

Run:
- `python -m pytest -q`
- `python -m ruff check .`

Expected: all PASS.

**Step 2: Close bd issue**

Run:
- `bd close MimirQ-qto.4`
- `bd sync`

**Step 3: Push**

Run:
```bash
git pull --rebase
git push
git status -sb
```
Expected: working tree clean and `up to date with origin/main`.

