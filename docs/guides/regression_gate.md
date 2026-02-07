# 离线评测回归（RAGAS / 用例集 / CI Gate）

## 目标

把“已有 RAGAS 回归能力”变成企业级可复现/可回归：

- 用例集可 **导入/导出**（跨环境复用）
- CI 可跑 **regression gate**，指标退化直接失败

## 用例集导入/导出

### UI

- `分析工具 → RAGAS 评测 → 回归测试 → 测试用例库`
  - `导出`：下载 JSON（不包含 id，便于跨环境导入）
  - `导入`：上传 JSON（支持覆盖更新：按 question + dataset_id 匹配）

### API

- 导出：`GET /api/v1/evaluations/ragas/regression/cases/export`
- 导入：`POST /api/v1/evaluations/ragas/regression/cases/import`

## CI Gate 脚本

脚本：`scripts/regression_gate.py`

示例：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --thresholds ./thresholds.json
```

`thresholds.json` 示例：

```json
{
  "faithfulness": 0.7,
  "response_relevancy": 0.7,
  "retrieval_recall": 0.3,
  "retrieval_hit_at_10": 0.6,
  "abstain_rate": 0.02
}
```

> 说明：回归 run 的默认 top_k/threshold 等参数会跟随系统设置（与 chat 默认一致），除非你在 run 请求里显式覆盖。
>
> 新增可选指标（run summary 里可见，也可写进 thresholds 里 gate）：
> - `retrieval_recall`: [0,1]，证据召回率（人工标注 evidence chunk_id 与检索 citations.chunk_id 的重合比例，越高越好）
> - `retrieval_hit_at_1/3/5/10`: [0,1]，命中率（top-k 里是否命中证据；汇总为命中占比，越高越好）
> - `retrieval_mrr`: [0,1]，MRR（证据第一次出现的平均倒数排名：`1/rank`，越高越好）
> - `retrieval_ndcg_at_10`: [0,1]，NDCG@10（证据在 Top10 的排序质量，越高越好）
> - `abstain_rate`: [0,1]，拒答率（`abstain_triggered` 的占比；可用于“严格可见证据模式”安全回归）
>
> 注意：`scripts/regression_gate.py` 目前只支持 **下限阈值**（metric >= threshold）。如果你想对 `abstain_rate` 做“上限”约束，需要改脚本或添加自定义指标。
