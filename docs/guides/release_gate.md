# Release Gate (Regression + SLO + Cost Budget)

This repo already has:
- A deterministic **retrieval-only regression gate** runnable in CI (`scripts/regression_gate.py`)
- A PII-safe **SLO snapshot** surface (`GET /api/v1/observability/slo/snapshot`)
- A PII-safe **cost attribution** surface (`GET /api/v1/observability/rag-metrics/cost-attribution`)

Wave26-T40 adds a small **release gate** wrapper script that combines those signals into a single
pass/fail decision suitable for CI and for pre-release checks in staging.

Wave40 extends it with an optional **retrieval leaderboard drift gate** that can consume
`leaderboard.json` artifacts (for example from `scripts/retrieval_ablation.py`).
Wave44 adds optional **queryset health policy metadata ingestion** so release reports can
distinguish quality drift from threshold-policy edits.
Wave46 adds explicit **queryset drift-class gating** for both the default bounded fixture and the
hybrid bounded fixture.
Wave48 adds optional **broader parsing-proof ingestion** so release reports can surface
deterministic parsing-impact signals (summary + diff) alongside retrieval/queryset artifacts.

## What It Gates

1. **Regression**: retrieval-only or RAGAS metrics, gated on thresholds
2. **SLO**: retrieval latency + zero-hit + error rate (1h + 24h windows)
3. **Cost budget**: average token/cost proxies derived from `rag_trace.cost_attribution`
4. **Leaderboard drift (optional)**: enforce min/max thresholds on top leaderboard rows
5. **Queryset policy drift (optional)**: ingest `queryset_health` snapshot metadata (`policy_hash`,
   `policy_source`, `trend.policy_changed`) and optionally fail/warn on policy changes
6. **Queryset drift-class thresholds (optional)**: fail when bounded diffs introduce new hard cases,
   degradation flags, or parse-risk tail documents
7. **Broader parsing-proof summary (optional)**: surface `hit_at_k_mean`, `mrr_mean`, and failed-case count
8. **Broader parsing-proof diff (optional)**: surface delta from the checked-in parsing-proof baseline

All outputs are PII-safe by construction (numbers, hashes, low-cardinality labels).

## LTR 自动学习闭环联动（Nightly/Canary/Rollback）

当你启用 LTR 的自动化训练闭环时，release gate 建议一并消费以下工件，确保“上线模型有据可查”：

- `artifacts/hard_negatives.nightly.manifest.json`
- `artifacts/ltr_nightly_cycle.manifest.json`
- `artifacts/ltr_online_rollback.report.json`

推荐发布前检查：

1. cycle manifest 中 candidate 训练 lineage 完整（cases/traces/hard-negatives 都有 hash）。
2. canary 激活策略满足 registry 边界（`apply_canary_activation` 的 ratio 校验通过）。
3. rollback daemon 最近窗口没有触发，或触发后已完成回滚并落盘报告。

这部分不是替代 regression/SLO/cost gate，而是补齐 LTR 的“训练-激活-回滚”可审计闭环。

## CI Integration

The GitHub Actions workflow runs:
- `retrieval-regression-gate` job (retrieval-only regression gate)
- `retrieval-only-bounded-gate` job to publish deterministic artifacts:
  - `artifacts/sample_retrieval_bench.json`
- `artifacts/sample_retrieval_bench.hybrid.json`
- `artifacts/sample_retrieval_bench.colbert.json`
- `artifacts/retrieval_profile.grounded_strict.contract.json`
- `artifacts/claim_verifier.contract.json`
- `artifacts/queryset_health.snapshot*.json`
- `artifacts/queryset_health.diff*.json`
- `artifacts/parsing_proof_broader_sample/summary.json`
- `artifacts/parsing_proof_broader_sample/report.json`
- `artifacts/parsing_proof_broader_sample/gate.json`
- `artifacts/parsing_proof_broader_sample/diff.json`
- `artifacts/parsing_proof_broader_sample/diff.md`
- Then `scripts/release_gate.py --skip-regression` with a small probe traffic to ensure SLO/cost summaries have data and to ingest the bounded query-set artifacts.

Budgets live in:
- `ci/release_gate_budgets.v1.json`

Optional leaderboard gate config (in budgets JSON):

```json
{
  "retrieval_leaderboard": {
    "path": "runs/retrieval_ablation/leaderboard.json",
    "policy": "fail",
    "top_n": 1,
    "thresholds": {
      "retrieval_mrr": { "min": 0.60 },
      "retrieval_hit_at_20": { "min": 0.90 }
    }
  }
}
```

`policy` supports:
- `fail`: violate threshold => process exits non-zero
- `warn`: print warning and continue (useful for gradual rollout)

Optional queryset-health policy drift config (in budgets JSON):

```json
{
  "queryset_health": {
    "path": "artifacts/queryset_health.snapshot.json",
    "policy": "warn"
  },
  "queryset_health_hybrid": {
    "path": "artifacts/queryset_health.snapshot.hybrid.json",
    "policy": "warn"
  },
  "queryset_health_diff": {
    "path": "artifacts/queryset_health.diff.json",
    "policy": "fail",
    "thresholds": {
      "hard_case_added_count": { "max": 0 },
      "degradation_flag_added_count": { "max": 0 },
      "parse_risk_tail_added_count": { "max": 0 }
    }
  },
  "queryset_health_diff_hybrid": {
    "path": "artifacts/queryset_health.diff.hybrid.json",
    "policy": "fail",
    "thresholds": {
      "hard_case_added_count": { "max": 0 },
      "degradation_flag_added_count": { "max": 0 },
      "parse_risk_tail_added_count": { "max": 0 }
    }
  },
  "parsing_proof": {
    "path": "artifacts/parsing_proof_broader_sample/summary.json",
    "policy": "warn",
    "thresholds": {
      "hit_at_k_mean": { "min": 1.0 },
      "mrr_mean": { "min": 1.0 },
      "failed_case_count": { "max": 0 }
    }
  },
  "parsing_proof_diff": {
    "path": "artifacts/parsing_proof_broader_sample/diff.json",
    "policy": "warn",
    "thresholds": {
      "hit_at_k_mean_delta": { "min": 0.0 },
      "mrr_mean_delta": { "min": 0.0 },
      "failed_case_added_count": { "max": 0 }
    }
  }
}
```

Semantics:
- `policy=warn`: include metadata in report and emit warning when `trend.policy_changed=true`
- `policy=fail`: treat `trend.policy_changed=true` as gate violation
- Drift-class thresholds are evaluated against:
  - `hard_case_added_count`
  - `degradation_flag_added_count`
  - `parse_risk_tail_added_count`
- Broader parsing-proof summary observed fields:
  - `cases_total`
  - `hit_at_k_mean`
  - `mrr_mean`
  - `failed_case_count`
- Broader parsing-proof diff observed fields:
  - `hit_at_k_mean_delta`
  - `mrr_mean_delta`
  - `failed_case_added_count`
- In CI we gate both the default bounded queryset diff and the hybrid bounded queryset diff.
  Broader parsing-proof remains `warn`-mode and informational at this stage.

## Local / Staging Usage

### 1) Run Retrieval Regression Gate (existing)

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --metrics "" \
  --thresholds ./thresholds.v2.json \
  --out-report-json ./artifacts/regression_gate.report.json \
  --out-report-md ./artifacts/regression_gate.report.md
```

The regression gate can now emit two CI-friendly artifacts:

- `--out-report-json`: machine-readable summary for downstream jobs/dashboards
- `--out-report-md`: human-readable Markdown summary for artifact review

The JSON/Markdown reports include:

- run id / dataset id / matched case count
- top-level summary metrics
- per-channel citation attribution where available (`vector` / `bm25` / `lexical` / `sparse`)
- threshold failures when the gate does not pass

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

With leaderboard drift gate (hard-fail mode):

```bash
python scripts/release_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --budgets ci/release_gate_budgets.v1.json \
  --retrieval-leaderboard runs/retrieval_ablation/leaderboard.json \
  --retrieval-leaderboard-policy fail \
  --skip-regression
```

With queryset health policy metadata (warn mode):

```bash
python scripts/release_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --budgets ci/release_gate_budgets.v1.json \
  --queryset-health-snapshot artifacts/queryset_health.snapshot.json \
  --queryset-health-snapshot-hybrid artifacts/queryset_health.snapshot.hybrid.json \
  --queryset-health-diff artifacts/queryset_health.diff.json \
  --queryset-health-diff-hybrid artifacts/queryset_health.diff.hybrid.json \
  --parsing-proof-summary artifacts/parsing_proof_broader_sample/summary.json \
  --parsing-proof-diff artifacts/parsing_proof_broader_sample/diff.json \
  --queryset-health-policy warn \
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
- CI probe traffic uses `--probe-retrieval-mode hybrid` so the SLO/cost sample is closer to the retrieval-regression runtime.
- Leaderboard gate prints metric-level threshold deltas in CI logs, e.g. `value`, `threshold`, `msg`.
- Queryset health metadata captured in report:
  - `policy_source` (`default` / `policy_json` / `cli_overrides` / `policy_json+cli_overrides`)
  - `policy_hash` (stable hash of normalized threshold policy)
  - `policy_changed` / `trend.policy_changed` (compared to previous queryset health snapshot)
  - `retrieval_mode`
  - `profile_hash`
- Queryset health diff observed fields captured in report:
  - `hard_case_added_count`
  - `degradation_flag_added_count`
  - `parse_risk_tail_added_count`
- Broader parsing-proof observed fields captured in report:
  - `hit_at_k_mean`
  - `mrr_mean`
  - `failed_case_count`
- Broader parsing-proof diff observed fields captured in report:
  - `hit_at_k_mean_delta`
  - `mrr_mean_delta`
  - `failed_case_added_count`
- Bounded-gate interpretation:
  - `retrieval_profile.grounded_strict.contract.json` proves the strict retrieval profile still enforces evidence-only semantics.
  - `claim_verifier.contract.json` proves claim-verifier diagnostics still emit stable `reason_code` and `contradiction_type` values.
  - `sample_retrieval_bench.hybrid.json` is the hybrid bounded quality baseline.
  - `sample_retrieval_bench.colbert.json` is a bounded regression signal for the ColBERT fallback path, not a replacement for end-to-end leaderboard evaluation.
