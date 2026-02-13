# Field-Level Security (FLS) / Redacted Views (Structured Sources)

Date: 2026-02-13

## Goal

Introduce field-level redaction policies for structured sources so that users can keep dataset access while specific sensitive fields are masked on server responses (not UI-only). This is a "redacted view" feature intended for enterprise/security use cases.

Scope for v1:

- Table store (TAG): mask table sample rows and query results by column name.
- DB catalog: mask column metadata (name/comment) by column name.
- Emit an audit log event when FLS redaction is applied.

Out of scope (follow-up):

- Server-side OIDC code exchange (handled in a separate issue).
- Applying FLS to RAG retrieval/indexes (virtual schema docs, chunk metadata).
- A dedicated UI/editor for authoring policies.

## Policy Storage

Store policy in `datasets.metadata` (JSONB) under key `fls_policy`.

Rationale:

- Avoids introducing new API routes and web API-client wiring.
- Allows policy to be transported via existing dataset config export/import.

## Policy Schema (v1)

`fls_policy` is a JSON object:

- `version`: `"1"`
- `rules`: list of rules

Each rule:

- `id`: stable string id
- `name`: display name
- `enabled`: boolean
- `sources`: list of `"table_store"` and/or `"db_catalog"`
- `column_name_regex`: regex string applied to the column name
- `allow_roles`: list of tenant roles allowed to see the field unredacted
- `allow_account_ids`: optional explicit allowlist
- `mask`: optional override mask string (default `"[REDACTED]"`)

Semantics:

- If a rule matches a column name for a given source and the current user is NOT allowed by role/account id, the field is redacted.
- Redaction mode is "keep the field/column but replace values with mask" (stable response shape).

Validation:

- Strict allowlists for `sources`.
- Regex length caps and basic nested-quantifier guard (best-effort ReDoS hardening).
- Require `allow_roles` or `allow_account_ids` to be non-empty.

## Enforcement Points

### Table Store (TAG)

Endpoints:

- `GET /api/v1/datasets/{dataset_id}/tables/{table_id}` (sample_rows)
- `GET /api/v1/datasets/{dataset_id}/tables/{table_id}/preview` (rows)
- `POST /api/v1/datasets/{dataset_id}/tables/{table_id}/query` (rows)
- `POST /api/v1/datasets/{dataset_id}/tables/{table_id}/ask` (data.rows)
- `POST /api/v1/datasets/{dataset_id}/tables/{table_id}/lotus/sem-filter` (rows)

Implementation:

- Compute a redaction mask per column based on the dataset policy and current user's tenant role/account id.
- Apply masks:
  - `sample_rows`: dict keys preserved; values replaced with mask.
  - `rows`: list-of-lists; replace cells at redacted column indices with mask.

### DB Catalog

Endpoint:

- `GET /api/v1/datasets/{dataset_id}/db-catalog/tables/{table_id}`

Implementation:

- For each returned column, if policy denies access:
  - Set `name` to mask string.
  - Set `comment` to mask string (or null if empty).

## Audit Logging

Emit one audit event per response where FLS redaction is applied.

Action: `fls.redaction_applied`

Details (PII-minimal):

- `dataset_id`
- `source` (`table_store` or `db_catalog`)
- `table_id` (when available)
- `redacted_columns_count`
- `redacted_columns` (bounded list)

Audit logging remains best-effort and must never block product flows.

## Testing

Add unit tests that cover:

- Non-privileged role sees masked values for matched columns.
- Privileged role sees raw values.
- Audit event is emitted only when redaction actually occurs.

