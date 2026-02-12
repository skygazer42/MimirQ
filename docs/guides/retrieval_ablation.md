# 检索参数消融评测（Retrieval Ablation / Leaderboard / Diff）

当你已经有一套**可回归的 ground-truth 用例集**（RAGAS regression cases / Evidence Pack 转换而来），并且希望系统性地对比不同检索参数（top_k / threshold / hybrid 权重等）对检索指标的影响时，可以使用这个离线脚本做消融矩阵评测。

脚本：`scripts/retrieval_ablation.py`

## 快速开始

1) 准备回归用例：`regression_cases.json`（可由 UI 导出，或由 Evidence Pack 转换生成）

2) 准备消融矩阵：`ablation_matrix.json`

示例（base + 显式 variants + grid）：

```json
{
  "schema": "mimirq.retrieval_ablation_matrix.v1",
  "base": {
    "label": "base",
    "rag_params": {
      "top_k": 20,
      "score_threshold": 0.0,
      "retrieval_mode": "hybrid",
      "enable_weight_rerank": true,
      "vector_weight": 0.6,
      "keyword_weight": 0.4
    }
  },
  "variants": [
    { "label": "k50", "rag_params": { "top_k": 50 } },
    { "label": "vector_only", "rag_params": { "retrieval_mode": "vector" } }
  ],
  "grid": {
    "score_threshold": [0.0, 0.1]
  }
}
```

3) 运行（retrieval-only，无需 RAGAS/LLM）：

```bash
python scripts/retrieval_ablation.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --matrix ./ablation_matrix.json \
  --out-dir ./ablation_out
```

## 运行逻辑（关键约定）

- **固定用例集**：脚本会按 `question + dataset_id` 匹配 case id，并在每个 variant run 里复用同一组 case_ids。
- **retrieval-only**：脚本创建回归 run 时强制 `metrics: []`，只跑检索与回归检索指标（Recall/Hit/MRR/NDCG/abstain）。
- **参数合并**：每个 variant 的 `rag_params` 会覆盖 base 的 `rag_params`（flat merge）。
- **unknown keys**：矩阵中不被回归 run API 支持的 `rag_params` key 会被忽略，并在日志里提示（避免“以为生效但其实没生效”）。
- **确定性顺序**：
  - 显式 `variants` 先跑（保持文件顺序）
  - `grid` 后跑（按 JSON key 顺序展开笛卡尔积，最后一个 key 变化最快）

## 输出物（CI 友好）

在 `--out-dir` 下会产出：

- `plan.resolved.json`：解析后的 base/variants（可复现）
- `runs/*.run.json`：每个 run 的 summary + rag_params（文件名包含 label + run_id 前 8 位）
- `diffs/*.diff.json`：与 base run 的 JSON diff（objective deltas）
- `diffs/*.diff.html`：与 base run 的 HTML diff（可直接作为 CI artifact 下载查看）
- `leaderboard.json`：可机读 leaderboard
- `leaderboard.md`：Markdown 表格（适合作为 PR artifact 快速浏览）

如需跳过 HTML artifacts（减少体积/请求），加 `--no-html`。

## 常见用法建议

- 先用较小矩阵跑通流程（例如只改 `top_k`），再逐步扩大 grid。
- 每次只改变 1-2 个维度，避免笛卡尔积爆炸。
- 如果你需要对比 KG/lexical/fusion 等更复杂的策略，建议先确认这些参数在回归 run API 中已支持（否则会被脚本提示为 ignored）。

