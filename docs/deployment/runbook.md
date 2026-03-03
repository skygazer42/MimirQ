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
- Query Analytics（zero-hit/慢检索/错误）：`GET /api/v1/observability/rag-metrics/query-analytics`
- Trace Bundle（按 request_id 导出 PII-safe 诊断包）：`GET /api/v1/observability/rag-metrics/trace-bundle?request_id=...`
- Config Snapshot（脱敏配置快照 + 指纹）：`GET /api/v1/observability/config/snapshot`
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
- Dataset purge（删除 dataset 内 documents/chunks/KG 衍生物；bounded，默认 dry-run）：`POST /api/v1/datasets/{dataset_id}/purge`
- Regression runs purge（评估工件保留清理；bounded，默认 dry-run）：`POST /api/v1/evaluations/ragas/regression/runs/purge`
- Regression runs retention runner（适合 CronJob）：`python scripts/run_retention_jobs.py --regression-runs --dry-run`

后续将补齐：

- dataset/document 的合规 bundle 导出（含向量/KG/对象存储引用）
- retention job（定时执行 + 可观测 + 可审计；覆盖更多数据类型）

---

## 5) Incident Response（应急处置）

目标：先止血，再定位，再验证修复。

1. **确认影响面**
   - 是所有租户还是单租户？
   - 是单数据集还是所有数据集？
   - 是 ingest/index 还是 retrieval/rerank/LLM？
2. **收集最小证据（PII-safe 优先）**
   - request_id（前端会带 `X-Request-ID`，后端也会写入响应头/日志）
   - `/api/v1/observability/rag-metrics/summary`（聚合指标）
   - RAG trace / leaderboard / diff 报告（尽量用 hash / 指标，不要复制原始 query/文档）
   - 一键打包（PII-safe）：`python scripts/incident_bundle.py --base-url <api> --tenant-id <tid> --token <admin_token> --request-id <rid>`
3. **止血手段（按场景）**
   - **成本/滥用飙升**：启用/调严 rate-limit 与 tenant QPS quota；观察 `Retry-After` 与 429 频率。
   - **检索质量骤降**：优先排查配置变更（settings/env），用 `retrieval_config_hash` 对比“变更前后”的配置指纹。
   - **索引一致性异常**：跑 index-audit 端点；必要时暂停新 ingestion，避免越写越乱。
   - **对象存储/向量库不可用**：Readiness 503 时先恢复依赖，再考虑回放/补偿任务。

---

## 6) Rollback Playbook（回滚剧本）

### A. 配置回滚（最快）

优先回滚“可配置项”而非代码：

- 回滚环境变量（推荐生产方式）
- 或通过 Settings API（若启用；生产通常建议关闭写 `.env`）

回滚后立即做：

1. 用 `/api/v1/health/ready` 确认依赖就绪
2. 用一组固定回归用例跑一次 regression（或对比最近两次 run diff）
3. 观察 `/api/v1/observability/rag-metrics/summary` 是否恢复

### B. 文档版本回滚（读路径，不重算）

当问题来自切块/治理/pipeline 变更：

- 列出版本：`GET /api/v1/documents/{document_id}/versions`
- 激活旧版本（回滚）：`POST /api/v1/documents/{document_id}/versions/{pipeline_hash}/activate`

说明：
- 这是“读路径回滚”，不会重新解析/重新向量化
- 适合快速止血（恢复引用/召回）

### C. 发布回滚（代码层）

当问题来自后端/前端版本发布：

1. 回滚到上一版本镜像（Docker tag / Helm release）
2. 若涉及 DB migration：确保有备份与演练；优先做“向后兼容”变更，避免强依赖回滚
3. 回滚后跑健康检查 + 回归套件
