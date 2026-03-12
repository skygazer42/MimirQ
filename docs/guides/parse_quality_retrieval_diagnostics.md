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
- `RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED` (default `false`)
- `RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO` (default `0.5`)
- `RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED` (default `3`)
- `RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS` (default `100`)

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
- `metrics.parse_risk`
- `metrics.parse_risk_level`
- `metrics.parse_risk_score`
- `metrics.parse_risk_reason`
- `metrics.parse_risk_hardcase_eligible`

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
- `retrieval_trace.parse_risk`

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

## Remediation Playbook

When `parse_risk_level` is `high` or `medium`, run this deterministic loop:

1. Confirm signal quality
- Check `metrics.parse_quality_considered` is not near zero.
- If considered is too low, treat this as metadata coverage work, not parser degradation.

2. Confirm impact scope
- Inspect `metrics.parse_quality.low_samples` for representative low-score chunks.
- Cross-check `retrieval_trace.parse_risk` and `retrieval_trace.parse_quality` in the same request.

3. Enable parse-risk hardcase emission (optional but recommended)
- Set `RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED=true`.
- Keep `RETRIEVAL_HARDCASE_EMIT_ENABLED` as-is; parse-risk emission is additive and only triggers when eligible.
- Watch for `metrics.hardcase_candidate.reason=parse_risk_tail`.

4. Build dataset-level remediation scope
- Generate/refresh dataset report and inspect `parse_risk_summary`.
- Use `parse_risk_summary.top_low_quality_documents` as initial repair candidates.

5. Generate reparse execution plan
- Run:
```bash
python scripts/plan_parse_quality_reparse.py \
  --report runs/dataset_report.json \
  --out runs/parse_quality_reparse_plan.json
```
- Optional:
```bash
python scripts/plan_parse_quality_reparse.py \
  --report runs/dataset_report.json \
  --max-docs 50 \
  --max-score 0.30 \
  --out runs/parse_quality_reparse_plan.json
```

6. Execute reparse + verify closure
- Reparse planned documents with improved parser/chunk settings.
- Re-run retrieval diagnostics and verify:
  - `parse_risk_level` moves from `high/medium` to `low/healthy`
  - `parse_quality_low_ratio` drops
  - CI diff artifact shows parse-risk-tail contraction (`parse_risk_tail_drift`)

## CI Artifact Notes

`scripts/diff_queryset_health_snapshots.py` now emits `parse_risk_tail_drift`:

- `baseline_count` / `current_count`
- `added_document_ids`
- `removed_document_ids`
- `retained_document_ids`

This enables PR-time review of whether parse-risk tail is shrinking after remediation.
