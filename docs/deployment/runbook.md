# Operations Runbook（MimirQ）

本 runbook 面向运维/平台团队，目标是用最短路径定位问题层级：ingest → index → retrieval/rerank → LLM。

> 原则：**默认 PII-safe**。诊断优先使用计数/哈希/指标，避免直接打印用户 query / 文档原文。

---

## 1) 健康检查

- 进程健康（轻量）：`GET /api/v1/health`
- 依赖就绪（强依赖）：`GET /api/v1/health/ready`

K8s readiness 建议用 `/api/v1/health/ready`。

---

## 2) 常见告警与定位路径

### A. Readiness 503（依赖不可用）

优先检查：

1. Postgres：`DATABASE_URL`
2. Redis：`REDIS_URL`（若启用了 `TASK_QUEUE_ENABLED=true`）
3. 向量库：`VECTOR_BACKEND` + Milvus/Chroma 连接信息
4. MinIO：`MINIO_ENABLED=true` 时检查 `MINIO_ENDPOINT` 等

---

### B. 文档 ingestion 卡住 / 失败

1. 查看后端日志（api + worker）
2. 如果启用了队列：确认 worker 正在运行且能连上 Redis
3. 检查上传目录/对象存储：
   - `UPLOAD_DIR`（容器内通常是 `/data/uploads`）
   - PVC 是否可写
   - 若使用 MinIO：bucket / credential / endpoint

---

### C. 检索质量突然下降

建议按顺序排查：

1. **配置变化**：settings / env 是否变更（尤其是 retrieval/rerank 相关开关）
2. **索引一致性**：使用 index-audit 端点（需要 admin）
3. **候选池大小**：观察 retrieval trace 中候选数量、是否被 ACL/filter 截断

---

## 3) 管理/诊断端点（RBAC 受限）

以下端点通常只允许 owner/admin（部分允许 auditor）：

- Observability 概览：`GET /api/v1/observability/rag-metrics/summary`
- Index 一致性检查：`GET /api/v1/observability/index-audit?dataset_id=...`
- 审计日志列表：`GET /api/v1/audit/logs`
- 审计日志导出（SIEM）：`GET /api/v1/audit/logs/export`
- 审计日志保留清理（admin-only）：`POST /api/v1/audit/logs/purge`

---

## 4) 数据生命周期（当前状态）

项目正在补齐“导出/删除/保留策略”。当前已具备：

- 审计日志 NDJSON 导出（SIEM 友好）
- 审计日志按 retention purge（bounded delete）
- 审计日志 retention runner（适合 CronJob）：`python scripts/run_retention_jobs.py --audit-logs --dry-run`
- Dataset 文档清单 NDJSON 导出（默认脱敏，支持 cursor + gzip）：`GET /api/v1/datasets/{dataset_id}/documents/export`
- Dataset bundle ZIP 导出（包含 dataset/config/docs 清单，默认脱敏）：`GET /api/v1/datasets/{dataset_id}/export`

后续将补齐：

- dataset/document 的合规 bundle 导出（含向量/KG/对象存储引用）
- retention job（定时执行 + 可观测 + 可审计；覆盖更多数据类型）
