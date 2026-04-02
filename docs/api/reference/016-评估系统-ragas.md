# 评估系统 (RAGAS)

## 什么是 RAGAS？

RAGAS 是 RAG 系统的评估框架，用于衡量回答质量：

| 指标 | 说明 | 范围 |
|------|------|------|
| `faithfulness` | 忠实度：回答是否基于检索内容 | 0-1 |
| `answer_relevancy` | 相关性：回答是否切题 | 0-1 |
| `context_precision` | 上下文精度 | 0-1 |

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
