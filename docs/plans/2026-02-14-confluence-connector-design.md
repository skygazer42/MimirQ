# Confluence Connector (MVP) Design

Date: 2026-02-14

## Goal

Add a Confluence connector that can ingest pages from a space into a dataset with:

- Bounded page limits per run
- Incremental sync cursor
- Best-effort retries for external API calls
- Encrypted secret storage + redaction in API responses

## Non-Goals (MVP)

- Perfect permission mapping from Confluence users/groups to MimirQ accounts
- Attachments/blogposts/comments ingestion
- Rich delete detection for incremental-only runs
- Deduplication by content hash for URL-ingested HTML (current URL ingest does not compute sha256)

## Connector ID

`confluence_space`

Appears in `GET /api/v1/connectors` with `supports_incremental=true`.

## Configuration Schema

Pydantic model (API validated):

- `base_url` (string): Confluence base URL. Examples:
  - Cloud: `https://<site>.atlassian.net/wiki`
  - On-prem: `https://confluence.example.com` (or with a context path)
- `space_key` (string): Confluence space key
- `auth` (object, optional): reuse `WebCrawlAuthConfig` (`none|cookie|bearer|basic`)
- `sync_mode` (enum): `auto|full|incremental`
  - `auto`: incremental if `state.last_modified` exists, else full
- `max_pages` (int): hard cap per run
- `page_size` (int): API page size (bounded)
- `soft_delete` (bool): when `true` and running in `full` mode, disable connector-managed docs not present in the latest full listing (best-effort)
- Ingestion options (same pattern as other URL connectors):
  - `user_agent`
  - `parser_backend`, `chunk_strategy`, `pipeline`
  - `access` (document ACL override; best-effort)

Secrets:
- `auth.cookie`, `auth.token`, `auth.password` are encrypted at rest and redacted in API responses via existing secret handling.

## Incremental State / Cursor

Persisted in `connector_configs.state` (best-effort):

- `last_modified` (RFC3339 string): max page modified timestamp observed/processed
- (optional) `start` (int): reserved for full-scan pagination repair/resume

Run config created from a saved config includes `_state` attached by the API layer (existing pattern).

## Data Flow

1. Operator creates a run (`POST /api/v1/connectors/runs`) or runs a saved config (`POST /api/v1/connectors/configs/{id}/run`).
2. Worker dispatches to `_execute_confluence_space_run`.
3. Executor:
   - Lists pages in the space (full or incremental)
   - For each page, builds a web URL from Confluence `_links.base` + `_links.webui`
   - Ingests the page HTML via existing URL ingestion (`_ingest_url_upload_request`)
   - Applies optional `access` override
   - Adds `connector` metadata to document JSONB (`page_id`, `space_key`, `base_url`, `last_modified`, `run_id`)
4. Run stats are updated incrementally for observability.
5. When run finishes, `_sync_connector_config_from_run` persists cursor back to the originating saved config (if any).

## External API Calls + Retries

Confluence REST calls use the global `HTTPClientPool.request_with_retry`:

- Retries on timeout/network errors
- Retries on HTTP 5xx / 429
- Honors `Retry-After` for 429

Per-page ingestion errors are recorded into `run.stats.errors` and `run.stats.failed_urls` (bounded samples).

## Soft Delete (Best-Effort)

When `sync_mode=full` and `soft_delete=true`:

- Collect the set of page IDs observed in the full listing
- Query existing dataset documents that were previously created by this connector (match `doc_metadata.connector.connector_id`, `space_key`, `base_url`)
- For any connector-managed document whose `page_id` is not in the observed set, set `documents.disabled_at = now` (best-effort)

This is intentionally conservative and does not run during incremental sync.

## Permission Mapping (Where Feasible)

MVP supports:

- Dataset permission inheritance (default)
- Optional connector-level `access` override applied per ingested document (existing behavior)

Confluence user/group restrictions are not mapped to MimirQ accounts in MVP.

## Security Notes

- Secrets are encrypted at rest by the API layer and redacted in API responses.
- URL ingestion is gated by `URL_INGEST_ENABLED` and subject to SSRF protections. On-prem Confluence may require explicit allowlist/private-IP enablement in URL ingest settings.

## Future Work

- Attachments ingestion (download attachment URLs and ingest files)
- Better resume/retry endpoints for `confluence_space`
- Robust permission mapping by integrating Confluence identity to MimirQ accounts
- Content-hash based dedup for URL-ingested pages

