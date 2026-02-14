# Confluence Connector: Attachments Ingestion Design

Date: 2026-02-14

## Goal

Extend the existing `confluence_space` connector to optionally ingest page attachments (PDF/DOCX/etc) in addition to page HTML.

Attachments must be linked back to their parent page via document metadata so UIs and downstream processing can trace provenance.

## Non-Goals

- Perfect attachment-level soft delete (detecting removed attachments while a page remains)
- Permission mapping from Confluence users/groups to MimirQ accounts
- Ingesting blogposts/comments/inline media beyond the attachments API
- Content-hash based dedup across connector runs (existing behavior creates new documents)

## Configuration Schema

Add bounded, opt-in flags to `ConfluenceSpaceConnectorConfig`:

- `include_attachments` (bool)
  - Default: `false`
  - If true, list and ingest page attachments via Confluence REST.
- `max_attachments_per_page` (int)
  - Default: `10`
  - Clamp to a safe range (e.g. `1..50`).
- `max_total_attachments` (int)
  - Default: `200`
  - Clamp to a safe range (e.g. `1..2000`).

The connector continues to rely on the existing file-type allowlist (`settings.allowed_extensions_list`) and URL ingestion safety controls.

## Data Flow

Page listing and page ingestion are unchanged:

1. List pages via `GET {api_base}/content/search` ordered by `lastmodified ASC` (`expand=version`).
2. Ingest each page either via:
   - `ingest_method=api_view`: `GET {api_base}/content/{id}?expand=body.view` then local HTML ingest, or
   - `ingest_method=webui`: URL ingest of `_links.webui`/`tinyui`.

When `include_attachments=true`, per page:

1. List attachments:
   - `GET {api_base}/content/{page_id}/child/attachment?start=0&limit=<...>`
   - Use `_links.base` and attachment `_links.download` to build an absolute `download_url`.
2. For each attachment (bounded by both `max_attachments_per_page` and `max_total_attachments`):
   - Best-effort filter based on filename extension to avoid obvious unsupported types.
   - Ingest via existing URL ingestion pipeline:
     - `_ingest_url_upload_request(url=download_url, filename=<attachment filename>, fetch_headers=auth_headers, ...)`
3. Patch `doc_metadata.connector` on the attachment document:
   - Required: `page_id`, `attachment_id`, `filename`, `download_url`
   - Also include: `connector_id=confluence_space`, `base_url`, `space_key`, `run_id`, `mode`, and best-effort `page_url` / `page_title`
   - Optional: `doc_kind="attachment"` to make downstream handling explicit

## Security Notes

- Because attachments ingestion uses URL ingestion, it remains gated by `URL_INGEST_ENABLED` and subject to existing SSRF protections.
- Secrets remain encrypted at rest in connector configs and redacted in API output (no new secret fields added).

## Errors / Observability

- Confluence REST calls for attachment listing use `HTTPClientPool.request_with_retry`.
- Failures are best-effort:
  - A failed attachment listing does not fail the whole run.
  - A failed attachment download/ingest does not stop the run.
- Extend `run.stats` with attachment counters and per-item errors:
  - `processed_attachments`, `created_attachments`, `failed_attachments`, `skipped_attachments`

## Tests

Add/update tests to cover:

- Creating a `confluence_space` run with `include_attachments=true` still redacts `auth.*` secrets.
- Attachment listing URL construction and bounded limits (unit-testable helper preferred).
