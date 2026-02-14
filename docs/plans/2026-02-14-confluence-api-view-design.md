# Confluence Connector: REST body.view Ingestion Mode Design

Date: 2026-02-14

## Goal

Extend the existing `confluence_space` connector with an ingestion mode that fetches Confluence page HTML via REST:

- `GET /rest/api/content/{id}?expand=body.view`

and ingests it without relying on the Confluence web UI URL session.

This improves reliability for Confluence Cloud setups where API tokens work for REST API calls but the web UI requires a browser session/cookies.

## Non-Goals

- Changing the existing incremental cursor semantics (`state.last_modified`)
- Attachments/blogposts/comments ingestion
- Permission mapping from Confluence users/groups to MimirQ accounts
- Content-hash based dedup across connector runs (existing behavior creates a new document per page per run)

## Configuration Schema

Add a new field to `ConfluenceSpaceConnectorConfig`:

- `ingest_method` (enum): `api_view|webui`
  - Default: `api_view`
  - `api_view`: fetch per-page HTML via REST `body.view`
  - `webui`: current behavior (ingest page web UI URL via URL ingestion pipeline)

Auth stays the same (`WebCrawlAuthConfig`), and `api_view` must work with `basic|bearer` without cookies.

## Data Flow

Listing (unchanged):

1. Executor lists pages via `GET {api_base}/content/search` using CQL ordered by `lastmodified ASC` (`expand=version`).
2. Cursoring uses `version.when` (preferred) and persists the max observed timestamp to `connector_configs.state.last_modified`.

Per page:

### ingest_method=webui (existing)

- Build `page_url` from `_links.base` + `_links.webui` (or `tinyui`)
- Ingest via `_ingest_url_upload_request(url=page_url, fetch_headers=auth_headers, ...)`

### ingest_method=api_view (new)

1. Fetch REST content:
   - `GET {api_base}/content/{page_id}?expand=body.view,version`
2. Build a complete `.html` document:
   - Minimal `<html><head>...</head><body>...</body></html>` skeleton
   - Insert `<h1>{title}</h1>` at the top of `<body>` so the title is searchable even if Confluence returns an HTML fragment
   - Add `<base href="{page_url}">` to help relative links resolve during parsing/preprocessing
3. Ingest the generated HTML as a local file via a new internal helper in `app/api/v1/documents.py`:
   - Writes to `UPLOAD_DIR/<tenant_id>/<uuid>.html`
   - Creates `documents` row with required pipeline metadata (`pipeline_hash`, etc.)
   - Enqueues processing when queue is enabled; otherwise processes inline (connector context)

Connector metadata:

- Both modes attach `doc_metadata.connector`:
  - `connector_id=confluence_space`
  - `base_url`, `space_key`, `page_id`, `page_title`, `page_url`, `last_modified`, `run_id`, `mode`
  - Add `ingest_method` to make the source type explicit

## Security Notes

- Keep existing behavior: `confluence_space` runs remain gated by `URL_INGEST_ENABLED` for now (no change to connector allowlist logic).
- Secrets remain encrypted at rest via `encrypt_connector_config_secrets` and redacted in API output via `redact_secrets`.

## Errors / Observability

- REST fetch failures (4xx/5xx/timeouts) are recorded per page into `run.stats.errors` and increment `failed`.
- Failures do not stop the run; execution continues to the next page.

## Tests

Add/update unit tests to cover:

- Default `ingest_method` is `api_view` in `ConfluenceSpaceConnectorConfig`
- Creating a `confluence_space` run still redacts `auth.*` secrets and includes the default `ingest_method`

