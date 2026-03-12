# Hardcase Feedback Automation

This guide describes how to use retrieval-emitted hardcase candidates to automate feedback loops.

## Why

Low-evidence retrieval failures are usually repetitive. Instead of triaging one-by-one, we emit
a deterministic candidate payload that can be deduplicated and exported to evaluation pipelines.

## Enable

Set:

- `RETRIEVAL_HARDCASE_EMIT_ENABLED=true`

Optional companion settings:

- `RETRIEVAL_HARD_FALLBACK_ENABLED=true`
- `RETRIEVAL_CONTRACT_MODE=deterministic_recall`

## Payload Contract

When retrieval has no usable citations (or abstains), metrics include:

- `metrics.hardcase_candidate`

Schema:

- `schema`: `mimirq.hardcase_candidate.v1`
- `reason`: `no_citations` | `abstain`
- `query_hash`: stable query hash
- `retrieval_mode`
- `retrieval_profile`
- `retrieval_config_hash` (when available)
- `dedupe_key`: stable key for grouping duplicates
- `ts_ms`

The same payload is also exported in:

- `retrieval_trace.hardcase_candidate`

## Dedupe Strategy

Use `dedupe_key` as the primary grouping key.

Recommended aggregation dimensions:

- `reason`
- `retrieval_mode`
- `retrieval_profile`
- `retrieval_config_hash`

## Suggested Automation Pipeline

1. Collect `hardcase_candidate` from metrics logs / traces.
2. Group by `dedupe_key`.
3. Keep most recent `request_id` sample per group.
4. Join with user feedback events and evaluation outcomes.
5. Prioritize groups by:
   - frequency
   - recentness
   - business impact
6. Feed top groups into regression/evaluation suites.
