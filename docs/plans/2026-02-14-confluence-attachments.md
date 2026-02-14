# Confluence Connector: Attachments Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend `confluence_space` to optionally ingest Confluence page attachments (PDF/DOCX/etc) via URL ingestion and attach metadata linking each attachment to its parent page.

**Architecture:** Keep existing page listing + page ingestion unchanged. When `include_attachments=true`, list attachments via Confluence REST (`/content/{page_id}/child/attachment`) with bounded limits, ingest each attachment via `_ingest_url_upload_request`, and patch `doc_metadata.connector` with attachment fields.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy, pytest, httpx (via `HTTPClientPool`).

---

### Task 1: Add config schema fields (bounded) + API test

**Files:**
- Modify: `app/api/schemas/connector.py`
- Test: `tests/test_connectors_endpoints.py`

**Step 1: Write the failing test**

Add a new test that asserts `include_attachments=true` survives schema validation and response redaction:

```python
def test_connectors_create_confluence_run_supports_include_attachments(monkeypatch):
    ...
    res = client.post("/api/v1/connectors/runs", json={
        "connector_id": "confluence_space",
        "dataset_id": str(dataset_id),
        "config": {
            "base_url": "https://example.atlassian.net/wiki",
            "space_key": "DOCS",
            "auth": {"type": "bearer", "token": "secret-token"},
            "include_attachments": True,
            "max_pages": 1,
        },
    })
    assert res.status_code == 201
    cfg = (res.json() or {}).get("config") or {}
    assert cfg.get("auth", {}).get("token") == "<redacted>"
    assert cfg.get("include_attachments") is True
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_supports_include_attachments -v`

Expected: FAIL because `include_attachments` is missing from response config (extra field ignored by schema).

**Step 3: Implement minimal schema changes**

In `ConfluenceSpaceConnectorConfig` add:

- `include_attachments: bool = False`
- `max_attachments_per_page: int = Field(default=10, ge=1, le=50)`
- `max_total_attachments: int = Field(default=200, ge=1, le=2000)`

**Step 4: Re-run test to verify it passes**

Run: `pytest -q tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_supports_include_attachments -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/schemas/connector.py tests/test_connectors_endpoints.py
git commit -m "feat(connectors): add confluence attachment config flags"
```

---

### Task 2: Add small pure helpers + unit tests (URL building + clamping)

**Files:**
- Modify: `app/api/v1/connectors.py`
- Test: `tests/test_confluence_connector_unit.py`

**Step 1: Write failing unit tests**

Add tests for:

- Clamping attachment limits from a raw config dict
- Building an attachment download URL from `_links.base` + `_links.download`

**Step 2: Run unit tests to verify they fail**

Run: `pytest -q tests/test_confluence_connector_unit.py -v`

Expected: FAIL (helpers not implemented).

**Step 3: Implement minimal helpers**

In `app/api/v1/connectors.py` add:

- `_confluence_attachment_limits(cfg: dict) -> tuple[bool, int, int]`
- `_confluence_attachment_download_url(*, base: str, download: str) -> str` (can reuse `_confluence_join_webui`)

**Step 4: Re-run unit tests**

Run: `pytest -q tests/test_confluence_connector_unit.py -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add app/api/v1/connectors.py tests/test_confluence_connector_unit.py
git commit -m "test(connectors): add confluence attachment helpers"
```

---

### Task 3: Implement attachments ingestion in `_execute_confluence_space_run`

**Files:**
- Modify: `app/api/v1/connectors.py`

**Step 1: Add bounded attachment config parsing**

Inside `_execute_confluence_space_run`, parse + clamp:

- `include_attachments`
- `max_attachments_per_page`
- `max_total_attachments`

Initialize attachment counters in `run.stats`.

**Step 2: List attachments per page (best-effort, retrying)**

For each successfully ingested page (has `page_id`):

- Call `GET {api_base}/content/{page_id}/child/attachment` using `pool.request_with_retry`
- Respect `max_attachments_per_page` (limit) and paginate only as needed
- Stop when reaching `max_total_attachments`

**Step 3: Ingest attachments via URL ingestion**

For each attachment:

- Compute `download_url`
- Determine `filename` from attachment `title` (best-effort)
- Optional: skip quickly if extension clearly not in `settings.allowed_extensions_list`
- Call `_ingest_url_upload_request(...)`
- Patch `doc_metadata.connector` with:
  - `connector_id=confluence_space`, `base_url`, `space_key`, `run_id`, `mode`
  - `page_id`, `page_title`, `page_url`
  - `attachment_id`, `filename`, `download_url`, `doc_kind="attachment"`

Record `ConnectorRunDocument` rows for created attachment docs using `source_ref=attachment_id|download_url`.

**Step 4: Manual verification**

Run: `pytest -q tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_supports_include_attachments -v`
Run: `pytest -q tests/test_confluence_connector_unit.py -v`

**Step 5: Commit**

```bash
git add app/api/v1/connectors.py
git commit -m "feat(connectors): ingest confluence page attachments"
```

---

### Task 4: Quality gates

Run:

- `pytest -q tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_redacts_auth -v`
- `pytest -q tests/test_connectors_endpoints.py::test_connectors_create_confluence_run_supports_include_attachments -v`
- `pytest -q tests/test_confluence_connector_unit.py -v`
- `ruff check app/api/schemas/connector.py app/api/v1/connectors.py tests/test_connectors_endpoints.py tests/test_confluence_connector_unit.py`

Expected: all PASS / no lint issues.

---

### Task 5: Close issue + sync beads + push

```bash
bd close MimirQ-qto.7
bd sync
git push -u origin feat/confluence-attachments
```
