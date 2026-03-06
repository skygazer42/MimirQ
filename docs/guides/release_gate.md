# Release Gate (Regression + SLO + Cost Budget)

This repo already has:
- A deterministic **retrieval-only regression gate** runnable in CI (`scripts/regression_gate.py`)
- A PII-safe **SLO snapshot** surface (`GET /api/v1/observability/slo/snapshot`)
- A PII-safe **cost attribution** surface (`GET /api/v1/observability/rag-metrics/cost-attribution`)

Wave26-T40 adds a small **release gate** wrapper script that combines those signals into a single
pass/fail decision suitable for CI and for pre-release checks in staging.

## What It Gates

1. **Regression**: retrieval-only or RAGAS metrics, gated on thresholds
2. **SLO**: retrieval latency + zero-hit + error rate (1h + 24h windows)
3. **Cost budget**: average token/cost proxies derived from `rag_trace.cost_attribution`

All outputs are PII-safe by construction (numbers, hashes, low-cardinality labels).

## CI Integration

The GitHub Actions workflow runs:
- `retrieval-regression-gate` job (retrieval-only regression gate)
- Then `scripts/release_gate.py --skip-regression` with a small probe traffic to ensure SLO/cost summaries have data.

Budgets live in:
- `ci/release_gate_budgets.v1.json`

## Local / Staging Usage

### 1) Run Retrieval Regression Gate (existing)

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --metrics "" \
  --thresholds ./thresholds.v2.json
```

### 2) Run Release Gate (SLO + Cost)

If you already have traffic/metrics logged, you can run without probe:

```bash
python scripts/release_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --budgets ci/release_gate_budgets.v1.json \
  --skip-regression
```

If you want the script to generate a small amount of deterministic traffic (useful for CI/staging),
provide a cases bundle and `--probe-chat-requests`:

```bash
python scripts/release_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --budgets ci/release_gate_budgets.v1.json \
  --cases ./regression_cases.json \
  --probe-chat-requests 4 \
  --skip-regression
```

## Notes

- `AUTH_MODE=header`: use `--user-id` (and optionally `--tenant-id`).
- `AUTH_MODE=jwt`: use `--bearer` (and `X-Tenant-ID` if your deployment requires it).
- Probe traffic uses `retrieval_mode=keyword` and disables multi-query/alias/rerank to keep it deterministic.

