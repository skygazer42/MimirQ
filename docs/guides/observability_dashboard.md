# 监控面板（检索 / 重排 / 引用 Metrics）

## 目的

把“已有的指标日志能力”变成企业级可控/可验证：

- 通过 **设置页** 开关 `ENABLE_METRICS_LOG`
- 通过 **监控面板** 聚合展示检索/重排/引用指标（而不是只看单条日志）
- 默认 **不回传原始 query / chunk 文本**（只做数值/分布聚合）

## 开启方式

方式 1：前端设置页（推荐）

- `系统 → 设置 → 观测与调试 → RAG Metrics 日志` 打开

方式 2：.env

```bash
ENABLE_METRICS_LOG=true
METRICS_LOG_PATH=./logs/rag_metrics.jsonl
```

> 出于安全考虑：`METRICS_LOG_PATH` 仅允许设置为 `./logs` 下的 `.jsonl` 文件（避免写到任意路径）。

## 使用

- 前端页面：`/observability`（仅 owner/admin）
- API：`GET /api/v1/observability/rag-metrics/summary?window_minutes=60`

## 安全注意

- 指标日志可能包含业务文本（例如 trace 里会记录 question/query 等字段）  
  生产环境建议同时开启：

```bash
PII_REDACTION_ENABLED=true
```

