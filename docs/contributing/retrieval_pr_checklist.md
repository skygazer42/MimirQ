# Retrieval PR Checklist

Use this checklist for PRs that change retrieval, ranking, or recall-critical behavior.

## Scope + Repro

- [ ] 明确说明影响范围：召回、排序、融合、重排、或 tokenization。
- [ ] 在 PR 描述中给出可复现实验命令（本地可直接运行）。
- [ ] 标注使用的 retrieval profile / retrieval mode / top_k。

## Minimum Evidence

- [ ] 至少提供一项回归证据（`regression_gate.py` 结果或等价报告）。
- [ ] 对 ranking/fusion 变更，提供 ablation 或前后对比（推荐附 `leaderboard.json` / `leaderboard.md`）。
- [ ] 给出关键指标前后值（至少包含 `retrieval_hit_at_20`、`retrieval_mrr`）。

## Required Commands

```bash
# deterministic sample baseline
python scripts/run_sample_retrieval_benchmark.py \
  --fixture data/sample/retrieval_fixture_v1.json \
  --out runs/sample_bench.json

# retrieval gate (use your fixture/cases)
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases <cases.json> \
  --metrics "" \
  --thresholds ci/retrieval_thresholds.v2.json \
  --out-report-json runs/regression_gate.report.json \
  --out-report-md runs/regression_gate.report.md
```

## Artifact Expectations

- [ ] PR 附件中包含机器可读结果（JSON）和人可读摘要（Markdown）。
- [ ] 若门禁失败，提供失败指标与阈值差值（delta）说明，而不是只贴“失败”截图。
- [ ] 若调整阈值，说明原因、风险和回滚策略。

## Compatibility + Docs

- [ ] 运行 profile 兼容检查（如适用）：`python scripts/check_retrieval_profile_compat.py`。
- [ ] 如果改了 API 或调参方式，补充 `docs/guides/` 或 `docs/examples/`。
- [ ] 对用户可见行为变化，在 PR 描述或 GitHub Release 中说明。
