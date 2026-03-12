# Parse Quality -> Retrieval Diagnostics

This guide describes the retrieval-side diagnostics that close the parsing-quality feedback loop.

## Goal

When documents are parsed poorly, retrieval quality drops even if embeddings/reranker are healthy.
The retrieval orchestrator now emits parse-quality risk signals so operators can quickly answer:

- Is low parse quality likely causing current recall misses?
- How large is the risk tail in current top candidates?
- Should we reparse, prioritize cleanup, or continue with current corpus?

## Settings

Use the following settings to tune alert sensitivity:

- `RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD` (default `0.35`)
- `RETRIEVAL_PARSE_QUALITY_ALERT_RATIO` (default `0.5`)

Interpretation:

- A candidate is considered "low parse quality" if `score < LOW_THRESHOLD`.
- An alert is raised when `low_count / considered >= ALERT_RATIO`.

## Metrics Contract

`run_retrieval` now emits:

- `metrics.parse_quality`
- `metrics.parse_quality_low_threshold`
- `metrics.parse_quality_alert_ratio`
- `metrics.parse_quality_alert`
- `metrics.parse_quality_low_ratio`
- `metrics.parse_quality_considered`
- `metrics.parse_quality_recommendation`

`metrics.parse_quality` payload includes:

- `considered`: number of candidates with parse-quality metadata
- `low_count`: number below low threshold
- `low_ratio`: `low_count / considered`
- `avg_score`: average score over considered candidates
- `alert`: boolean alert signal
- `recommendation`: deterministic next-step hint
- `low_samples`: bounded examples for debugging

## Retrieval Trace

The stable trace now includes:

- `retrieval_trace.parse_quality`

This mirrors the metrics payload and is safe for offline analysis / replay pipelines.

## Metadata Source

Document-level `doc_metadata.parse_quality.score` is propagated into retrieval candidate metadata as:

- `doc_parse_quality_score`

Orchestrator diagnostics read parse quality from:

- `doc_parse_quality_score`
- `parse_quality_score`
- `parse_quality.score`

## Recommendation Codes

Current deterministic recommendations:

- `no_parse_quality_metadata`
- `parse_quality_healthy`
- `monitor_parse_quality_tail`
- `medium_parse_risk_prioritize_low_quality_docs`
- `high_parse_risk_reparse_documents`

These are intentionally machine-friendly and stable for alerting pipelines.
