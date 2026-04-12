# Parsing Proof Workflow

This guide covers the repo's deterministic parsing-impact proof workflow for RAG ingestion.

## What It Proves

The parsing-proof lane is meant to answer:

1. Does stronger parsing improve retrieval?
2. Does stronger parsing preserve better evidence for extraction?
3. Can those improvements be tracked deterministically over time?

## Entry Points

### Local sample run

```bash
make parsing-proof-sample
```

This writes a broader sample proof run under:

- `runs/parsing_proof_broader_sample/parsing_proof_batch.spec.json`
- `runs/parsing_proof_broader_sample/batch.report.json`
- `runs/parsing_proof_broader_sample/rollout.json`
- `runs/parsing_proof_broader_sample/summary.json`
- `runs/parsing_proof_broader_sample/report.json`
- `runs/parsing_proof_broader_sample/gate.json`
- `runs/parsing_proof_broader_sample/diff.json`
- `runs/parsing_proof_broader_sample/diff.md`
- `runs/parsing_proof_broader_sample/review.md`

Current committed bounded sample:

- `16-case / 32-query`
- includes noisy `line_chart` and noisy `diagram` fixtures
- includes `multilingual`, `formula`, and two `handwriting` note cases
- `summary.json` / `report.json` now surface `query_count_total` plus sample composition counts by family/category

### File-driven run

```bash
python scripts/run_parsing_retrieval_proof_from_file.py \
  --input-file tests/fixtures/parsing_golden_broader/cross_page_table_pdf/input/sample.pdf \
  --queries-json tests/fixtures/parsing_retrieval_proof/queries/cross_page_table.json \
  --fixture-out runs/parsing_file_proof.fixture.json \
  --report-out runs/parsing_file_proof.report.json \
  --parser-backend basic
```

### Batch run from a manifest-derived spec

```bash
python scripts/build_parsing_retrieval_proof_batch_spec.py \
  --manifest-json tests/fixtures/parsing_golden_broader/manifest.json \
  --case-queries-json tests/fixtures/parsing_retrieval_proof/broader_case_queries.sample.json \
  --out runs/parsing_proof_batch.spec.json

python scripts/run_parsing_retrieval_proof_batch.py \
  --spec-json runs/parsing_proof_batch.spec.json \
  --out-dir runs/parsing_proof_batch
```

## Repo-owned Sample Inputs

Broader parser corpus:

- `tests/fixtures/parsing_golden_broader/manifest.json`

Sample query map:

- `tests/fixtures/parsing_retrieval_proof/broader_case_queries.sample.json`

Thresholds:

- `ci/parsing_retrieval_proof_thresholds.v1.json`

Baseline summary:

- `ci/parsing_retrieval_proof_summary_baseline.v1.json`

Rollout policy:

- `ci/parsing_retrieval_proof_rollout.v1.json`

## CI / Workflow Surfaces

Current non-blocking surfaces:

- `.github/workflows/ci.yml`
- `.github/workflows/rag-quality-gate.yml`
- `.github/workflows/parsing-proof-sample.yml`

These publish parsing-proof artifacts but do not yet hard-fail on parsing-proof drift.

## Review Order

When reviewing a parsing-proof run, read artifacts in this order:

1. `rollout.json`
2. `summary.json`
   Check `query_count_total` and `sample_composition` first so you know what the bounded sample currently covers.
3. `report.json`
4. `gate.json`
5. `diff.json`
6. `diff.md`
7. `review.md`

## Current Policy

For the policy and promotion path from informational to blocking, see:

- `docs/guides/parsing_proof_policy.md`
