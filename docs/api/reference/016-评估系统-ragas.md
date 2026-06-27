# 评估系统 (RAGAS)

> **联调视角**：评估与回归可与「可对用户问答」验收对齐；见手册 [可对用户问答](https://skygazer42.github.io/MimirQ/handbook/docs/integration/tasks/knowledge-base-qa)（[集成总览](https://skygazer42.github.io/MimirQ/handbook/docs/integration/welcome)）。

## 什么是 RAGAS？

MimirQ 评测体系支持 **37 个指标**：10 个 LLM 评判类（RAGAS）+ 27 个确定性类（无需 LLM、可复现）。

### LLM 评判类（RAGAS，10 个）

| 指标 | 说明 |
|------|------|
| `faithfulness` | 忠实度：回答是否基于检索内容 |
| `response_relevancy` / `answer_relevancy` | 回答相关性 |
| `answer_similarity` | 与参考答案语义相似度 |
| `answer_correctness` | 答案正确性 |
| `context_recall` / `context_precision` | 上下文召回 / 精度 |
| `id_based_context_recall` / `id_based_context_precision` | 基于 chunk ID 的召回 / 精度 |
| `llm_context_precision_without_reference` | 无参考答案的上下文精度 |

### 确定性类（27 个，无需 LLM、可复现）

| 类别 | 指标 |
|------|------|
| 忠实 / 幻觉 | `faithfulness_det`、`atomic_faithfulness`、`hallucination_rate`、`self_knowledge_ratio`、`refusal_correctness` |
| 引用 | `citation_accuracy`、`citation_coverage`、`quote_verifiability` |
| 上下文利用 | `retrieval_effective_context_rate`、`retrieval_noise_rate`、`noise_sensitivity`、`chunk_attribution`、`chunk_utilization` |
| 检索 IR | `retrieval_recall`、`retrieval_mrr`、`retrieval_ndcg_at_10`、`retrieval_ndcg_at_20`、`retrieval_hit_at_{1,3,5,10,20}` |
| 元数据 | `expected_metadata_hit_rate`、`expected_metadata_recall` |
| 多跳 | `multihop_path_completeness`、`multihop_order_consistency`、`multihop_chain_hit_rate` |

> 指标定义见 `app/rag/evaluation/ragas.py`（`RAGAS_REGRESSION_METRICS` 与 `DETERMINISTIC_REGRESSION_METRICS`）。

:::warning 当前限制
回归对比基于指标均值，**暂无统计显著性检验**（t-test / Bootstrap 置信区间 / 效应量）。判断 A/B 差异是否真实时需自行验证，避免被噪声误导。
:::

## 创建评估任务

```bash
POST /api/v1/evaluations/ragas/runs
```

```json
{
  "conversation_id": "对话ID",
  "metrics": ["faithfulness", "answer_relevancy"],
  "max_turns": 10
}
```

## 查看评估结果

```bash
GET /api/v1/evaluations/ragas/runs/{run_id}
```

**响应示例：**
```json
{
  "id": "run-uuid",
  "status": "completed",
  "scores": {
    "faithfulness": 0.85,
    "answer_relevancy": 0.92
  }
}
```

## 回归测试

用于持续监控 RAG 质量：

```bash
# 创建测试用例
POST /api/v1/evaluations/ragas/regression/cases

# 运行回归测试
POST /api/v1/evaluations/ragas/regression/runs
```

## 回归 Leaderboard（按检索指标排序）

按回归 run 的 `summary` 指标排序，返回一个轻量 leaderboard，并附带 `retrieval_config_hash`（用于按检索配置分组/对比；PII-safe）。

```bash
GET /api/v1/evaluations/ragas/regression/runs/leaderboard?dataset_id={dataset_id}&metric_key=retrieval_mrr&limit=20
```

**常用 metric_key：**
- `retrieval_recall`
- `retrieval_hit_at_20`
- `retrieval_mrr`
- `retrieval_ndcg_at_20`
- `abstain_rate`

**响应示例：**
```json
{
  "metric_key": "retrieval_mrr",
  "items": [
    {
      "run_id": "run-uuid",
      "status": "completed",
      "created_at": "2024-01-01T00:00:00Z",
      "finished_at": "2024-01-01T00:01:00Z",
      "metric_key": "retrieval_mrr",
      "metric_value": 0.42,
      "retrieval_config_hash": "1a2b3c4d5e6f..."
    }
  ]
}
```

---
