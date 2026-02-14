# Confluence Connector: api_view Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `ingest_method=api_view` to `confluence_space` so pages can be ingested via Confluence REST `body.view` (no web UI cookies), while preserving cursor semantics and secret handling.

**Architecture:** Keep Confluence listing unchanged; branch per page on `ingest_method`. For `api_view`, fetch `content/{id}?expand=body.view` and ingest a generated local `.html` file via a new internal helper in `app/api/v1/documents.py`.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, httpx (via `HTTPClientPool`), pytest.

---

### Task 1: Add `ingest_method` to connector schema (default api_view)

**Files:**
- Modify: `app/api/schemas/connector.py`
- Test: `tests/test_connectors_endpoints.py`

**Step 1: Write failing test**

Update `test_connectors_create_confluence_run_redacts_auth` to assert:
- response `config.ingest_method == "api_view"`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_redacts_auth -v`  
Expected: FAIL because `ingest_method` is missing.

**Step 3: Minimal implementation**

In `ConfluenceSpaceConnectorConfig`, add:
- `ingest_method: Literal["api_view","webui"] = "api_view"`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_redacts_auth -v`  
Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/schemas/connector.py tests/test_connectors_endpoints.py
git commit -m "feat(connectors): default confluence ingest_method=api_view"
```

---

### Task 2: Add internal local-HTML ingestion helper

**Files:**
- Modify: `app/api/v1/documents.py`

**Step 1: Write a minimal unit test**

Add a new test file to validate the helper creates a `Document` row and enqueues/inline-process path can be invoked with `background_tasks=None`:
- Create: `tests/test_documents_local_html_ingest_unit.py`

Test should:
- monkeypatch `enqueue_document_processing` to return `None` (force inline)
- monkeypatch `document_processor.process_document` to a no-op coroutine
- monkeypatch `_resolve_writable_dataset` to return a dummy dataset with `id`
- call the helper with small HTML and assert:
  - returns a `DBDocument` with `file_type == "html"`
  - `doc_metadata.source_url` equals the provided page URL
  - `doc_metadata.pipeline_hash` exists

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_documents_local_html_ingest_unit.py -v`  
Expected: FAIL because helper does not exist.

**Step 3: Minimal implementation**

Add an internal async helper to `app/api/v1/documents.py`:
- Name: `_ingest_local_html_request`
- Responsibilities:
  - write HTML bytes to `UPLOAD_DIR/<tenant>/<uuid>.html` (bounded by `MAX_FILE_SIZE`)
  - apply dataset ingestion policy (same matching rules as URL ingest for `parser_backend/chunk_strategy/pipeline`)
  - create `DBDocument` row with required pipeline metadata and `source_url`
  - enqueue processing if possible; otherwise inline-process when `background_tasks is None`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_documents_local_html_ingest_unit.py -v`  
Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/v1/documents.py tests/test_documents_local_html_ingest_unit.py
git commit -m "feat(documents): ingest local html for connectors"
```

---

### Task 3: Implement confluence_space `api_view` execution path

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_confluence_connector_unit.py`

**Step 1: Add a unit test for defaulting behavior**

Extend `tests/test_confluence_connector_unit.py` with a small unit test for ingest_method normalization:
- If `cfg["ingest_method"]` missing, executor should treat it as `api_view` (default).

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_confluence_connector_unit.py -v`  
Expected: FAIL (no normalization behavior yet).

**Step 3: Minimal implementation**

Update `_execute_confluence_space_run`:
- Read `ingest_method` from decrypted config; normalize to `api_view|webui` (default `api_view`)
- For `api_view`:
  - fetch `content/{id}?expand=body.view,version` using `HTTPClientPool.request_with_retry`
  - build HTML skeleton + `<h1>{title}</h1>` + `<base href="{page_url}">`
  - ingest via `_ingest_local_html_request(...)`
- Attach `doc_metadata.connector.ingest_method`

**Step 4: Run tests**

Run:
- `pytest tests/test_confluence_connector_unit.py -v`
- `pytest tests/test_connectors_endpoints.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/v1/connectors.py tests/test_confluence_connector_unit.py
git commit -m "feat(connectors): confluence api_view ingestion via body.view"
```

---

### Task 4: Quality gates + ship

**Files:**
- (none)

**Step 1: Run full test suite (or bounded suite if slow)**

Run: `pytest -q`  
Expected: PASS.

**Step 2: Update bd + push**

Run:
```bash
bd close MimirQ-qto.6
git pull --rebase
bd sync
git push
git status -sb
```

