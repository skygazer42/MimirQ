# Query Rewrite Versioning + Evaluation Gate (Design)

Date: 2026-03-06

## Problem

Query rewrite is prompt-tuned and can materially change retrieval outcomes, but prior to this change:

- The rewrite prompt/version was not explicitly versioned.
- Stable grouping keys (`retrieval_config_hash`) did not include rewrite strategy/version.
- The same rewrite logic existed in multiple code paths (Evidence API retrieval orchestrator and the chat engine),
  making it easy to drift and hard to measure changes reliably.

This makes regression gating and rollback harder than it needs to be.

## Goals

- Configurable: select a rewrite strategy/version via configuration (safe, low-cardinality).
- Measurable: traces and `retrieval_config_hash` must reflect which rewrite strategy is active so evaluation runs can be grouped correctly.
- Safe defaults: query rewrite remains off by default; unknown strategy ids fall back to a safe baseline.
- PII-safe: do not emit raw prompt text into traces/fingerprints.

## Non-Goals (Defer)

- Full experiment management / rollout percentages (handled by the Experiment/Rollout task).
- Per-request arbitrary prompt injection (must remain allowlisted).
- A new online gate runner: we rely on existing regression suites and the stable config hash to make changes gateable.

## Design

### Strategy Registry + Fingerprint

Introduce a small in-code strategy registry:

- Strategy id is versioned and low-cardinality (e.g. `kb_followup.v1`, `kb_followup.v2`).
- A `strategy_hash` is computed as a stable hash of the strategy definition (including the prompt template text),
  but only the hash is emitted downstream (no prompt text leaks).
- Unknown strategy ids fall back to the baseline strategy id (`kb_followup.v1`).

### Trace + Config Hash Plumbing

1. Retrieval trace (`mimirq.retrieval_trace_pass.v1`) is extended with:
   - `rewrite.strategy_id`
   - `rewrite.strategy_hash`
   - `rewrite.temperature`, `rewrite.max_chars`

2. Stable retrieval config fingerprint (`retrieval_config_hash`) now includes a new low-cardinality section:

```json
{
  "query_rewrite": {
    "enabled": true,
    "strategy_id": "kb_followup.v1",
    "strategy_hash": "…",
    "temperature": 0.2,
    "max_chars": 120
  }
}
```

This makes rewrite changes measurable and gateable via existing regression dashboards and replay tooling.

### Rollback

Rollback is a config-only operation:

- Set `ENABLE_QUERY_REWRITE=false` to disable entirely, or
- Switch `QUERY_REWRITE_STRATEGY` back to a previous strategy id.

## Implementation Notes

- New setting: `QUERY_REWRITE_STRATEGY` (default `kb_followup.v1`).
- Strategy helpers live in `app/rag/core/query_rewrite_strategy.py`.
- Both code paths (retrieval orchestrator + chat engine) use the shared registry for prompt selection and strategy metadata.
- Regression leaderboard config hash builder also includes rewrite strategy knobs so leaderboard rows group correctly.

## Testing

- Orchestrator: `retrieval_config_hash` changes when `QUERY_REWRITE_STRATEGY` changes.
- Orchestrator: stable retrieval trace includes `rewrite.strategy_id` and `rewrite.strategy_hash`.
- Engine: rewrite stream event includes `strategy_id` and `strategy_hash`.
- Engine: metrics-log `retrieval_config_hash` changes with strategy id (captured via monkeypatched logger).
- Regression leaderboard: config hash changes with strategy id.

