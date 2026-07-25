# 检索参数消融评测（Retrieval Ablation / Leaderboard / Diff）

当你已经有一套**可回归的 ground-truth 用例集**（RAGAS regression cases / Evidence Pack 转换而来），并且希望系统性地对比不同检索参数（`retrieval_profile` / top_k / threshold / fusion / multi-query / reranker 等）对检索指标的影响时，可以使用这个离线脚本做消融矩阵评测。

当前建议：
- `recall20/recall50/coverage80`：偏召回型 profile，用来观察 Recall/Hit 的上限
- `hybrid_ce`：当前显式 production baseline，用来观察“hybrid recall + rerank”相对默认路径的收益。名称为历史兼容保留；启用重排时优先使用部署配置的 `RERANKER_PROVIDER`，未配置有效 provider 时才回退本地 `cross_encoder`

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
      "retrieval_profile": "recall20",
      "enable_weight_rerank": true,
      "vector_weight": 0.6,
      "keyword_weight": 0.4
    }
  },
  "variants": [
    { "label": "k50", "rag_params": { "top_k": 50 } },
    {
      "label": "weighted_recall50",
      "rag_params": {
        "retrieval_profile": "recall50",
        "fusion_strategy": "weighted",
        "fusion_weights": { "vector": 0.7, "bm25": 0.3 }
      }
    },
    {
      "label": "hybrid_rerank",
      "rag_params": {
        "enable_reranker": true,
        "reranker_provider": "llm",
        "reranker_top_n": 20
      }
    },
    {
      "label": "hybrid_ce_baseline",
      "rag_params": {
        "retrieval_profile": "hybrid_ce"
      }
    }
  ],
  "grid": {
    "enable_multi_query": [false, true],
    "multi_query_count": [3]
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

## 当前支持的 `rag_params` key

脚本会把下列 runtime knobs 透传给 regression run API：

- `retrieval_profile`
- `hybrid_ce` 也作为合法 profile 透传
- `enable_query_alias_expansion`
- `query_alias_max_queries`
- `enable_multi_query`
- `multi_query_count`
- `multi_query_temperature`
- `multi_query_max_chars`
- `enable_query_rewrite`
- `query_rewrite_strategy`
- `query_rewrite_temperature`
- `query_rewrite_max_chars`
- `top_k`
- `score_threshold`
- `retrieval_mode`
- `alpha`
- `sparse_retrieval_enabled`
- `sparse_retrieval_provider`
- `fusion_strategy`
- `fusion_budgets`
- `fusion_min_scores`
- `fusion_weights`
- `enable_weight_rerank`
- `vector_weight`
- `keyword_weight`
- `mmr_lambda`
- `enable_reranker`
- `reranker_provider`
- `reranker_top_n`
- `prompt_template_id`
- `prompt_template_key`
- `prompt_ab_experiment_key`

说明：

- `fusion_budgets` / `fusion_min_scores` / `fusion_weights` 允许使用 `vector|bm25|lexical|sparse` 这些 channel key。
- `enable_query_rewrite` / `query_rewrite_*` 与 `sparse_retrieval_*` 现在都支持 per-run override，适合直接进 ablation matrix。
- 更底层的进程级开关（例如 sparse index persistence、query rewrite 的全局 rollout）仍然建议按环境快照管理。

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
- Nightly 默认组合已经包含一个受限的 `hybrid_rerank` 变体，适合作为“真实 runtime 路径”的基线烟雾测试。
- 如果你需要对比 KG/lexical/fusion 等更复杂的策略，建议先确认这些参数在回归 run API 中已支持（否则会被脚本提示为 ignored）。

## 从消融产物生成 Adaptive Router 策略（G4）

当你希望把离线评测信号转成线上路由覆盖规则，可以基于 benchmark 报告生成策略工件：

```bash
python scripts/generate_adaptive_router_policy.py \
  --benchmark-report ./ablation_out/sample_retrieval_bench.json \
  --out ./ablation_out/adaptive_router_policy.v1.json
```

输出 schema：`mimirq.adaptive_router_policy.v1`

建议流程：

1. 先在测试环境用 `adaptive_router_policy` 请求级注入验证规则命中。
2. 再切到 `RAG_ADAPTIVE_ROUTER_ENABLED=true` + `RAG_ADAPTIVE_ROUTER_POLICY_PATH=...`。
3. 如果线上指标恶化，优先关开关回滚，再排查具体 `matched_rule_ids`。
