# Connector Reconcile

This guide documents the single-node reconcile workflow for connector-managed documents.

## Stable Source Identity

New connector-created documents now persist a stable identity block in `documents.metadata.connector`:

- `connector_id`
- `run_id`
- `dataset_id`
- `config_id` when the document came from a saved connector config
- `source_ref`
- `source_id`

These fields are written for URL-style connectors and preserved on Confluence / Jira documents in addition to their connector-specific metadata.

## Endpoint

`POST /api/v1/connectors/configs/{config_id}/reconcile`

Query parameters:

- `apply=false` (default): dry-run only
- `apply=true`: disable stale documents and re-enable matching disabled documents
- `sample_limit`: number of sample refs returned for each diff bucket

This endpoint uses the **last known local source set**:

- `url_batch`, `drive_files`: current config URL list
- `github_repo`, `minio_bucket`, `web_crawl`: persisted `source_manifest`

If no safe local source set is available, the endpoint returns `400` instead of guessing.

## Diff Semantics

The reconcile report uses `schema = mimirq.connector_reconcile.v1` and includes:

- `desired_source_refs`
- `active_source_refs`
- `disabled_source_refs`
- `stale_source_refs` + sample
- `reenable_source_refs` + sample
- `missing_source_refs` + sample
- `disabled_documents`
- `reenabled_documents`
- `documents_without_identity`

Interpretation:

- `stale_source_refs`: active docs no longer present in the desired local source set
- `reenable_source_refs`: disabled docs that should be active again
- `missing_source_refs`: refs expected by the desired local source set but not currently present in the corpus

## Operational Use

Recommended workflow:

1. Run dry-run first.
2. Inspect `stale_source_refs_sample` / `missing_source_refs_sample`.
3. Run again with `apply=true` only when the source set is trustworthy.

Reconcile is intentionally conservative:

- it never hard-deletes documents
- it only toggles `disabled_at`
- every dry-run/apply writes an audit event for observability
