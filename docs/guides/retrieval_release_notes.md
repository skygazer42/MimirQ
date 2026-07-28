# Retrieval Release Notes Template / 检索发布说明模板

Use this page as the canonical GitHub Release block for retrieval-facing changes.
Use the same structure for every public tag so the release history stays readable and comparable.

## Recommended layout / 推荐结构

### 1) Snapshot / 概览

| Metric | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| hit@10 | 0.0000 | 0.0000 | +0.0000 |
| mrr@10 | 0.0000 | 0.0000 | +0.0000 |
| ndcg@10 | 0.0000 | 0.0000 | +0.0000 |
| must_recall_pass_rate | 0.0000 | 0.0000 | +0.0000 |
| provenance_integrity_rate | 0.0000 | 0.0000 | +0.0000 |
| contextual_followup_used_rate | 0.0000 | 0.0000 | +0.0000 |
| p95 latency (ms) | 0.0 | 0.0 | +0.0 |

### 2) What changed / 变更点

- One sentence on the retrieval or ranking root cause.
- One sentence on the behavior change that users will feel.
- One sentence on rollout or compatibility notes.

### 3) Artifacts / 工件

- Benchmark summary: `runs/.../leaderboard.json`
- Gate report: `runs/.../gate_report.json`
- Trace bundle or diff, when relevant: `runs/.../trace_bundle.json`
- Bounded hybrid summary: `artifacts/sample_retrieval_bench.hybrid.json`
- Bounded ColBERT fallback summary: `artifacts/sample_retrieval_bench.colbert.json`
- Claim verifier contract: `artifacts/claim_verifier.contract.json`
- Queryset diff reports: `artifacts/queryset_health.diff.json`, `artifacts/queryset_health.diff.hybrid.json`
- Must-recall plus provenance gate: `artifacts/must_recall_provenance_gate.report.json`
- Parser benchmark diff: `artifacts/parser_benchmark.diff.json`
- Contextual follow-up diagnostics, if enabled: `artifacts/retrieval_trace.contextual_followup.json`
- Iterative pass diagnostics, if enabled: `artifacts/retrieval_trace.iterative_pass.json`

### 4) Thresholds / 门禁

- Retrieval gate thresholds file: `runs/.../thresholds.v2.json`
- Release gate budgets file: `ci/release_gate_budgets.v1.json`
- Notes on temporary waivers or strictness changes.

## Minimum evidence checklist / 最小证据清单

Before publishing retrieval-quality notes:

1. Confirm benchmark artifacts are reproducible from committed scripts and config.
2. Confirm the gate thresholds used for pass or fail are attached.
3. If quality regressed, state why the release still proceeds.
4. Include one sentence on the ranking-impact root cause: retrieval, fusion, rerank, or cache.
5. If hybrid or ColBERT behavior changed, include the bounded artifact result and rollout decision.
6. If must-recall or provenance claims are made, attach capsule or gate artifacts.
7. If contextual follow-up is enabled, include its used rate and average added citations.
8. If iterative pass is enabled, include hop distribution (`hops_attempted/hops_used`) and latency budget.

## Anti-patterns / 反模式

- Reporting only global averages without hit@k, mrr, or ndcg.
- Claiming improvements without artifact links.
- Mixing datasets or slices in one snapshot table without explicit labels.
- Hiding regressions by silently changing thresholds in the same release note block.
- Combining hybrid bounded artifacts and ColBERT fallback artifacts into one conclusion. They reflect different paths.
