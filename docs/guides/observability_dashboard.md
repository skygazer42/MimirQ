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
- API（Query Analytics）：`GET /api/v1/observability/rag-metrics/query-analytics?window_minutes=60`
- API（Trace Bundle，incident 调试）：`GET /api/v1/observability/rag-metrics/trace-bundle?request_id=...`
- API（Config Snapshot，脱敏配置 + 指纹）：`GET /api/v1/observability/config/snapshot`

## Index Audit（索引一致性检查）

用于排查“入库成功但检索不到”的经典问题：Postgres 里的 chunk 与向量库中的向量是否一致。

- 前端入口：`知识库管理 → 检索测试 → Index Audit`（仅 owner/admin；需要选择数据集）
- API：`GET /api/v1/observability/index-audit?dataset_id=...`

返回字段（摘要 + 小样本，均为 PII-safe）：
- `active_documents / active_chunks`：当前数据集启用中的文档/切片数量（DB）
- `vector_id_missing`：DB 中缺失 `vector_id` 的 chunk 数量（常见于中断/失败的入库流程）
- `vector_ids_checked / vector_ids_missing_in_backend`：抽样检查的 DB `vector_id` 中，向量库不存在的数量
- `milvus_ids_sampled / milvus_orphan_ids_sample`：向量库抽样的 orphan 向量（DB 中已无对应 active chunk）

> 说明：该接口为 **best-effort + bounded**（默认只检查/抽样有限数量 id），不会在大数据集上做全量扫描。

## Index Drift（未完成索引操作）

当 chunk patch / disable / delete 在 vector/BM25 侧只完成了一部分时，系统会写入 durable index-drift item。

- API（列表）：`GET /api/v1/observability/index-drift?dataset_id=...&status=open`
- API（人工 resolve）：`POST /api/v1/observability/index-drift/{id}/resolve`
- CLI（重放）：`python scripts/replay_index_drift.py --tenant-id ... --dataset-id ... --execute`

关键字段：

- `operation`: `chunk.patch` / `chunk.disable` / `chunk.delete`
- `channel`: `vector` / `bm25`
- `strictness`: `off` / `warn` / `strict`
- `reason`: 失败原因摘要
- `reconcile_task_id`: 原始 reconcile / replay 任务 id（如果有）
- `replay_count`, `last_replayed_at`

使用建议：

- `status=open` 且 `strictness=strict`：通常代表调用方已经收到 `409`，需要先修复 drift 再重试业务动作。
- `status=open` 且 `strictness=warn`：请求已经成功返回，但检索面可能仍残留旧状态，应尽快 replay。
- 只有在 drift 已被别的运维动作修复时，才使用 resolve endpoint 直接结单。

## Chat 诊断（引用定位 / Claim Evidence）

除了聚合面板外，单次问答的“证据定位”也可以在 Chat UI 里完成：

- 在 assistant 消息卡片右下角，悬浮可见 `诊断` 图标（BarChart）
- 诊断面板会展示 `message_metadata` / `citations`，并在严格可见证据模式下展示 `claim_evidence`
- 引用点击会尽量使用 `evidence_start_char / evidence_end_char` 做 span 级定位高亮（best-effort）

## 安全注意

- 指标日志可能包含业务文本（例如 trace 里会记录 question/query 等字段）  
  生产环境建议同时开启：

```bash
PII_REDACTION_ENABLED=true
```
