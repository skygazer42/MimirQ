# Training Export

This guide documents the dataset-scoped training export built from feedback rows and evidence items.

## Endpoint

`GET /api/v1/evidence/training-export`

Query parameters:

- `dataset_id` (required): target dataset UUID
- `format`: `jsonl` or `csv` (`jsonl` default)
- `include_feedback`: include `message_feedback` rows with stored retrieval trace snapshots
- `include_evidence`: include `evidence_items`
- `include_archived_evidence`: include archived evidence rows when `true`
- `max_rows_per_source`: per-source cap, default `2000`

The export is intentionally dataset-scoped so downstream LTR/rerank experiments can stay aligned with one corpus/version boundary.

## Row Schema

Every row uses `schema = mimirq.training_export_row.v1`.

Stable fields:

- `source_type`: `feedback` or `evidence_item`
- `source_id`: source row UUID
- `dataset_id`
- `status`
- `question`
- `expected_answer`
- `tags`
- `reference_sources`
- `trace_snapshot`
- `rag_config_snapshot`
- `source_metadata`
- `created_at`
- `updated_at`

`jsonl` returns one JSON object per line.

`csv` flattens nested structures into JSON string columns:

- `tags_json`
- `reference_sources_json`
- `trace_snapshot_json`
- `rag_config_snapshot_json`
- `source_metadata_json`

## Feedback Snapshot Fields

When feedback is submitted through `POST /api/v1/feedback/messages`, the server now persists a stable snapshot in `message_feedback.extra`:

- `dataset_id`
- `retrieval_trace_request_id`
- `retrieval_trace`
- `rag_config_snapshot`

This lets later exports recover the exact retrieval trace payload and the retrieval config fingerprint that produced the answer the user rated.

## Downstream Use

Recommended usage:

1. Export `jsonl` for model training / offline feature generation.
2. Use `source_type`, `source_metadata.rating`, and `status` to derive labels.
3. Use `reference_sources` as positive grounding references.
4. Use `trace_snapshot` + `rag_config_snapshot` to segment experiments by retrieval policy or config hash.

The export is designed for single-node workflows: reproducible enough for LTR/rerank iteration, without introducing a separate training data service.
