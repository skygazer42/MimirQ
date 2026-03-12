# Retrieval Release Notes Template

This guide defines a stable format for publishing retrieval-quality changes across releases.

Goal:

- Make hit-rate/ranking changes transparent to OSS users.
- Keep release notes machine-readable enough for future automation.
- Link quality claims to concrete benchmark and gate artifacts.

---

## 1) Copy/Paste Block for `CHANGELOG.md`

Use the section below in each release (or in `Unreleased` during development):

```markdown
### Retrieval Quality

#### Snapshot

| Metric | Baseline | Current | Delta |
| --- | ---: | ---: | ---: |
| hit@10 | 0.0000 | 0.0000 | +0.0000 |
| mrr@10 | 0.0000 | 0.0000 | +0.0000 |
| ndcg@10 | 0.0000 | 0.0000 | +0.0000 |
| p95 latency (ms) | 0.0 | 0.0 | +0.0 |

#### Artifacts

- Benchmark summary: `runs/.../leaderboard.json`
- Gate report: `runs/.../gate_report.json`
- Trace bundle / diff (if relevant): `runs/.../trace_bundle.json`
- Bounded hybrid summary: `artifacts/sample_retrieval_bench.hybrid.json`
- Bounded ColBERT fallback summary: `artifacts/sample_retrieval_bench.colbert.json`
- Claim verifier contract: `artifacts/claim_verifier.contract.json`
- Queryset diff reports: `artifacts/queryset_health.diff.json`, `artifacts/queryset_health.diff.hybrid.json`

#### Thresholds

- Retrieval gate thresholds file: `runs/.../thresholds.v2.json`
- Notes: any temporary waivers or strictness changes.
```

---

## 2) Minimum Evidence Checklist

Before publishing retrieval-quality notes:

1. Confirm benchmark artifacts are reproducible from committed scripts/config.
2. Confirm gate thresholds used for pass/fail are attached.
3. If quality regressed, explicitly state why release proceeds.
4. Include one sentence on ranking-impact root cause (retrieval/fusion/rerank/cache).
5. If hybrid or ColBERT behavior changed, include the bounded artifact outcome and whether rollout criteria still passed.

---

## 3) Recommended Artifact Naming

To keep links stable across CI and local runs:

- `runs/release/<version>/leaderboard.json`
- `runs/release/<version>/gate_report.json`
- `runs/release/<version>/thresholds.v2.json`
- `runs/release/<version>/trace_bundle.json` (optional)
- `runs/release/<version>/sample_retrieval_bench.hybrid.json`
- `runs/release/<version>/sample_retrieval_bench.colbert.json`
- `runs/release/<version>/claim_verifier.contract.json`

---

## 4) Anti-Patterns to Avoid

- Reporting only global averages without hit@k/mrr/ndcg.
- Claiming improvements without artifact links.
- Mixing datasets/slices in one snapshot table without explicit labels.
- Hiding regressions by silently changing thresholds in the same release note block.
- 把 hybrid bounded artifact 和 ColBERT fallback artifact 混为一个结论。二者反映的是不同链路。
