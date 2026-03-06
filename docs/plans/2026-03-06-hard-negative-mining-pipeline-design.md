# Wave26-T35 Design: Hard Negative Mining Pipeline (PII-Safe)

Date: 2026-03-06

## Goal

Provide an automated, **PII-safe** way to mine "hard negatives" for LTR training from existing traces:

- Output candidate sets as JSONL (`mimirq.hard_negatives.v1`) keyed by `query_hash`
- Bounded: caps per-case negatives and does not require loading the entire trace file into memory
- Auditable: keeps stable identifiers and retrieval config fingerprint (`retrieval_config_hash`)

## Definition: Hard Negatives

For a given regression case:

- Positives: the case's `reference_sources[].chunk_id`
- Candidate list: trace `citations[]` in ranked order
- A "hard negative" is any citation with `chunk_id` not in positives that appears **before the first positive** (near-miss).

We also cap negatives per `document_id` to avoid overfitting to a single doc.

## Inputs

1. Regression case bundle (`mimirq.regression_cases.v1` or legacy shapes)
2. Metrics JSONL containing `event=rag_trace` records

Optional filters:

- `--retrieval-config-hash`: restrict to one retrieval configuration fingerprint
- `--tenant-id`: restrict to one tenant (important if the metrics log is shared)

## Output

JSONL records (`mimirq.hard_negatives.v1`) containing:

- `query_hash` (SHA256 truncated; no raw query text)
- `retrieval_config_hash`
- `hard_negatives[]`: `{chunk_id, document_id, rank}`
- Optional debugging stats and (bounded) positives list (no text)

## Intended Workflow

1. Run a regression suite / production traffic with metrics logging enabled.
2. Mine hard negatives:
   - `python scripts/mine_hard_negatives_from_traces.py --cases cases.json --traces rag_metrics.jsonl --out hn.jsonl --tenant-id <tenant>`
3. Train LTR using mined hard negatives:
   - `python scripts/train_ltr_from_regression_cases.py --cases cases.json --hard-negatives-jsonl hn.jsonl ...`

