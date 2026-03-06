# Multi-Query Diversification Channel (Design)

Date: 2026-03-06

## Problem

Multi-query expansion improves recall by generating multiple alternative retrieval queries (`mq` variants), but naive fusion can cause two issues:

- **Unbounded dominance**: when many `mq` variants exist, RRF fusion can select mostly `mq`-sourced candidates in the final `top_k`, pushing out main-query candidates.
- **Hard to evaluate**: without explicit budget knobs and trace counters, it is difficult to gate, compare, and rollback the behavior.

## Goals

- Budgeted: provide a hard cap on how many final top_k items may come from `mq` variants.
- Observable: emit metrics/trace counters showing whether the cap was applied and how many candidates were selected from each pool.
- Rollback: safe default is OFF; turning it off returns to legacy RRF fusion behavior.

## Non-Goals (Defer)

- Full experiment management / rollout percentages (handled in Wave26-T38).
- Variant-aware quality scoring beyond the cap (still uses existing RRF + per-doc caps).

## Approach

### Query Variant Fusion (Budgeted)

When enabled, after running retrieval for all query variants (main + expansions), we:

1. Build a fused list across all variants (`docs_fused_all`) via deterministic RRF.
2. Build two additional fused lists:
   - `docs_non_mq`: RRF across all non-`mq` variants
   - `docs_mq`: RRF across `mq` variants only
3. Select final `top_k` with a cap:
   - reserve `top_k - mq_budget` slots for `docs_non_mq`
   - reserve `mq_budget` slots for `docs_mq`
   - deduplicate by `(document_id, chunk_index)` (stable doc key)
   - fill remaining slots from `docs_fused_all` (best-effort)

This ensures the main retrieval channel retains a stable share while still allowing controlled diversification.

### Configuration

New settings (safe defaults):

- `MULTI_QUERY_DIVERSIFY_ENABLED=false`
- `MULTI_QUERY_DIVERSIFY_BUDGET=0`

When enabled, `budget` is clamped to `[0, top_k]`.

### Observability

Emit the following PII-safe counters:

- `multi_query_diversify_enabled`, `multi_query_diversify_budget`
- `multi_query_diversify_used`
- `multi_query_diversify_selected_mq`, `multi_query_diversify_selected_non_mq`
- `multi_query_diversify_fill_from_fused`

Also embed the knob into `retrieval_config_hash` under `multi_query.diversify` so runs can be grouped correctly.

## Testing

- Orchestrator: with many `mq` queries, ensure final top_k caps `mq` role to the configured budget.
- Engine: same behavior for the chat engine path.
- Fingerprinting: `retrieval_config_hash` changes when diversification knobs change.

