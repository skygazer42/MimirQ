# Wave26-T34 Design: LTR Feature Schema + Run Lineage

Date: 2026-03-06

## Goal

Make LTR training and evaluation runs reproducible and versioned by default:

- **Feature schema is explicit and stable** (feature order/count drift is detectable).
- **Run lineage is recorded** for offline training/eval artifacts (dataset version, retrieval config version, model version).
- **PII-safe by construction**: no raw queries or document text is written into lineage payloads.

## Options Considered

1. **Bump manifest schema to v2** and require new fields.
   - Pros: explicit breaking-change boundary.
   - Cons: high friction; breaks existing artifacts and registry validation.

2. **Keep manifest schema v1**, add nested *versioned* objects.
   - Pros: backwards compatible; incremental adoption; safer rollout.
   - Cons: schema evolution happens inside optional sub-objects.

3. **Separate lineage artifacts** (train/eval JSON) without touching manifests/registry.
   - Pros: no registry changes.
   - Cons: lineage is easy to lose when uploading/registering models.

## Chosen Approach

Option 2: keep `mimirq.ltr_model_manifest.v1` and add nested, versioned payloads:

- `feature_spec`: `mimirq.ltr_feature_spec.v1` with a stable `hash`
- `lineage`: `mimirq.ltr_run_lineage.v1` with PII-safe run identifiers (dataset id + hashes + retrieval_config fingerprint)

This keeps existing models working while enabling reproducible provenance for new runs.

## Lineage Fields (PII-Safe)

`mimirq.ltr_run_lineage.v1` stores only low-cardinality identifiers and hashes:

- `dataset_id`
- `cases_sha256` (hash of the cases bundle bytes)
- `cases_schema` (when present)
- `pipeline_hashes` (from case bundle reference sources when available)
- `retrieval_config` / `retrieval_config_hash` (from backend `retrieval_trace.retrieval_config`)
- `hard_negatives_sha256` (optional, when a hard-negatives JSONL file is provided)
- `kind`: `"train"` or `"eval"`

## Storage / Surfaces

- Training script writes lineage into the sidecar manifest so it survives registry upload.
- Registry stores a sanitized allowlist of optional fields (`created_at`, `objective`, `training`, `feature_spec`, `lineage`, etc).
- Offline LTR evaluation script outputs a versioned result schema (`mimirq.ltr_offline_eval.v1`) including `lineage`.

## Testing

Unit tests lock the versioned schemas and key lineage fields:

- `build_ltr_feature_spec_fingerprint` is stable and versioned.
- Training manifest builder includes `mimirq.ltr_run_lineage.v1`.
- Registry preserves lineage (sanitized) when registering models.
- Offline eval summary builder includes lineage fields.

