# Wave26-T40 Design: Release Gate (Regression + SLO + Cost Budget)

Date: 2026-03-06

## Goal

Provide a single, scriptable **release gate** that combines:

1. **Regression quality** signals (retrieval-only or RAGAS)
2. **SLO/SLI** signals (latency, zero-hit rate, error rate)
3. **Cost budget** signals (token/cost proxies; PII-safe)

This gate must be:
- **Documented** (how to run locally/staging; what it checks)
- **Runnable in CI** (deterministic fixture + bounded probe traffic)
- **PII-safe by default** (no raw queries/docs emitted in gate outputs)

## Existing Building Blocks

The repo already contains:
- `scripts/regression_gate.py`: offline regression gate (CI-friendly)
- `GET /api/v1/observability/slo/snapshot`: SLO snapshot (Prometheus preferred; metrics JSONL fallback)
- `GET /api/v1/observability/rag-metrics/cost-attribution`: cost aggregates from metrics JSONL

Wave26-T40 should not re-invent these, but should stitch them into a cohesive workflow.

## Options Considered

1. **Doc-only checklist** (no code)
   - Pros: low effort
   - Cons: not enforceable; easy to drift; no CI signal

2. **CI-only gate** implemented directly in `.github/workflows/ci.yml`
   - Pros: fast to wire
   - Cons: logic trapped in YAML; hard to reuse in staging/prod; hard to test locally

3. **Thin wrapper script** that calls existing gate + hits observability endpoints (Chosen)
   - Pros: reusable, testable, CI-friendly, minimal new logic
   - Cons: requires a small “probe traffic” mechanism to guarantee metrics exist in CI

## Chosen Design

Implement:

- `scripts/release_gate.py`
  - Optional: invoke `scripts/regression_gate.py` (subprocess) for regression enforcement
  - Optional: generate **bounded probe traffic** via `POST /api/v1/chat` (LLM mock mode in CI)
  - Poll `/api/v1/observability/rag-metrics/summary` to avoid async metrics flush races
  - Gate SLO via `/api/v1/observability/slo/snapshot`
  - Gate cost via `/api/v1/observability/rag-metrics/cost-attribution`
  - Emit a compact JSON report (`mimirq.release_gate_report.v1`) for artifacts

- `ci/release_gate_budgets.v1.json`
  - Defines:
    - SLO thresholds per window (60m, 24h)
    - Cost thresholds on derived averages (e.g. `llm_total_tokens_avg`)
    - Minimum sample sizes and an “insufficient data” policy (`fail|warn`)

- Documentation:
  - `docs/guides/release_gate.md` describes the workflow, CLI usage, and CI integration.

## CI Integration

In the existing `retrieval-regression-gate` GitHub Actions job:

1. Enable metrics JSONL (`ENABLE_METRICS_LOG=true`, `METRICS_LOG_PATH=artifacts/rag_metrics.jsonl`)
2. Enable LLM mock (`LLM_MOCK_ENABLED=true`) to avoid external network calls
3. After retrieval regression gate passes, run:
   - `python scripts/release_gate.py --skip-regression --probe-chat-requests N --budgets ci/release_gate_budgets.v1.json`

This ensures:
- Regression metrics remain enforced
- Release gate script remains executable and stable
- SLO/cost budget logic is exercised on every PR

## Testing / Verification

- CI: `retrieval-regression-gate` job runs the full workflow end-to-end.
- Local: run `scripts/release_gate.py` against a local backend with metrics enabled.

