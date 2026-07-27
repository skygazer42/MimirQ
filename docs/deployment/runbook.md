# Operations Runbook（MimirQ）

本 runbook 面向运维/平台团队，目标是用最短路径定位问题层级：ingest → index → retrieval/rerank → LLM。

> 原则：**默认 PII-safe**。诊断优先使用计数/哈希/指标，避免直接打印用户 query / 文档原文。

<a id="rb-health"></a>
## 1) 健康检查

- 进程健康（轻量）：`GET /api/v1/health`
- 依赖就绪（强依赖）：`GET /api/v1/health/ready`

K8s readiness 建议用 `/api/v1/health/ready`。

---

<a id="rb-alerts"></a>
## 2) 常见告警与定位路径

<a id="rb-alert-map"></a>
### 2.0 告警 → 定位路径 → 止血手段（映射表）

本节提供一份“**告警 → 定位路径 → 止血手段**”的快速映射，便于 oncall 直接从 alert 跳到最短排障路径。

配套模板（默认阈值与本表一致）：

- PrometheusRule（K8s / Prometheus Operator）：`docs/ops/templates/prometheus-rule-mimirq.yaml`
- Grafana Dashboard（Ops Overview）：`docs/ops/templates/grafana-dashboard-mimirq.json`
- Helm（可选，一键安装）：`deploy/helm/mimirq`
  - `prometheus.prometheusRule.enabled=true`
  - `grafana.dashboard.enabled=true`（需要 Grafana sidecar 或手动导入）

> 注意：这些阈值是 **baseline 默认值**，不保证适配所有负载；生产请结合你的 SLO、实例数、峰值 QPS 做调参。

| Alert（PrometheusRule） | 默认阈值（模板） | 典型影响面 | 优先定位（最短路径） | 止血手段（先救火） | Runbook |
| --- | --- | --- | --- | --- | --- |
| `MimirQHighHttp5xxRate` | 5xx 比例 > 5%（5m），持续 10m | API 大面积失败 | 1) `GET /api/v1/health/ready`<br>2) 看依赖：Postgres / Redis / Vector / MinIO<br>3) 看网关/Ingress 5xx | 1) 恢复依赖（优先）<br>2) 临时降级：关掉高成本开关（如 rerank/部分检索增强）<br>3) 扩容 API 实例 | [A. Readiness 503](#rb-readiness-503) / [1) 健康检查](#rb-health) |
| `MimirQHighHttp429Ratio` | 429 比例 > 2%（10m）且总流量 > 1 rps，持续 15m | 客户端频繁 429、前端重试风暴、可用性下降 | 1) 看响应 `Retry-After` 与 `detail.scope`（区分 rate_limit / tenant_qps / quota）<br>2) 看是否与峰值流量/发布变更相关<br>3) 检查 Redis 分布式限流是否开启 | 1) 让客户端尊重 `Retry-After`（先止雪崩）<br>2) 临时放宽 `RATE_LIMIT_*` / `TENANT_QPS_QUOTA_*`（谨慎）<br>3) 扩容后端/依赖，避免长期靠放宽限流 | [5.1) 429 快速诊断](#rb-429) |
| `MimirQHighHttpLatencyP95` | HTTP p95 > 1s（5m），持续 10m | API 慢、超时、前端卡顿 | 1) Grafana 看 p95/p99 走势<br>2) 检查 CPU/内存/连接池<br>3) 看向量库/DB 慢查询 | 1) 扩容（API/向量库）<br>2) 临时降低 top_k / reranker_top_n<br>3) 走配置回滚（最快） | [5) IR](#rb-ir) / [6) 配置回滚](#rb-rollback) |
| `MimirQHighRagRetrievalLatencyP95` | 检索 p95 > 2s（5m），持续 10m | chat/RAG 慢、成本升高 | 1) 看 `rag_retrieval_elapsed_seconds`<br>2) 对比 deploy/config 指纹（config snapshot）<br>3) 检查向量库健康 | 1) 临时关闭 reranker 或降低 reranker_top_n<br>2) 降低 retrieval_profile/top_k（牺牲召回换稳定）<br>3) 回滚配置/版本 | [C. 检索质量下降](#rb-retrieval-quality) / [6) 配置回滚](#rb-rollback) |
| `MimirQHighRagRetrievalLatencyP99` | 检索 p99 > 6s（5m），持续 10m | 尾延迟恶化、SLO 破坏 | 1) 看 p99 是否只在峰值触发<br>2) 检查依赖抖动（向量库/DB/外部 API）<br>3) 采样 request_id 导出 trace bundle | 1) 启用限流/收紧 tenant QPS quota（保护后端）<br>2) 降级检索增强链路（multi-query/query rewrite）<br>3) 扩容向量库/缓存 | [5) IR](#rb-ir) |
| `MimirQHighRagErrorRate` | 错误率 > 2%（5m），持续 10m | 召回失败、答案降级/报错 | 1) `/api/v1/observability/rag-metrics/summary`<br>2) `/api/v1/observability/rag-metrics/query-analytics` 看 error kind<br>3) 检查依赖 ready | 1) 先恢复依赖（向量库/DB/外部 reranker）<br>2) 临时关闭失败组件（reranker / KG）<br>3) 回滚近期变更 | [C. 检索质量下降](#rb-retrieval-quality) / [3) 诊断端点](#rb-admin-endpoints) |
| `MimirQHighRagZeroHitRate` | zero-hit > 30%（10m），持续 20m | 大量“找不到证据” | 1) Query analytics 看 top zero-hit（hash）<br>2) 检查 ingestion/索引是否滞后<br>3) 跑 index-audit（dataset-scoped） | 1) 配置回滚（阈值/策略类变更最快）<br>2) 扩大候选池（top_k/overfetch）<br>3) 修复索引漂移/补偿 ingestion | [C. 检索质量下降](#rb-retrieval-quality) |
| `MimirQHighEvidenceRetrieveLatencyP95` | Evidence API p95 > 2s（5m），持续 10m | downstream 调用慢（检索-only） | 1) 看 `rag_evidence_retrieve_duration_seconds`<br>2) 排查向量库 / DB<br>3) 对比 retrieval config | 1) 限流/配额保护<br>2) 降低 top_k / profile<br>3) 扩容依赖 | [5) IR](#rb-ir) |
| `MimirQIngestionFailures` | `ingestion_runs_total{status="failed"}` 15m 内持续出现 | ingestion 失败、数据不新 | 1) 看 worker 日志（解析器/对象存储/embedding）<br>2) 检查队列/Redis（若启用）<br>3) 检查 MinIO/PVC 可写 | 1) 先止血：暂停大批量 ingest / 降并发<br>2) 修复依赖后重试/补偿<br>3) 临时关闭队列，改为 inline（仅紧急） | [B. ingestion 卡住/失败](#rb-ingestion) |
| `MimirQIngestionLatencyP95High` | ingestion p95 > 1h（15m），持续 30m | ingest backlog、索引滞后 | 1) 看 queue depth（若启用）<br>2) 看 parsing/embedding 外部依赖<br>3) 看 worker 并发与配额 | 1) 扩容 worker + 提升并发上限（谨慎）<br>2) 优先处理关键数据集（限流非关键）<br>3) 临时降级解析策略 | [B. ingestion 卡住/失败](#rb-ingestion) |
| `MimirQTaskQueueBrokerDown` | `task_queue_broker_up=0` 持续 5m | 队列不可用、异步 ingest 堵塞 | 1) `/api/v1/observability/task-queue/snapshot`<br>2) 检查 Redis 连接/网络策略<br>3) worker 启动日志是否重试 | 1) 恢复 Redis（优先）<br>2) 紧急：关闭队列（`TASK_QUEUE_ENABLED=false`）<br>3) 扩容/重启 worker | [A. Readiness 503](#rb-readiness-503) / [B. ingestion](#rb-ingestion) |
| `MimirQTaskQueueDepthHigh` | `task_queue_depth > 1000` 持续 15m | ingest 排队、延迟上升 | 1) 看 `task_queue_depth` 与 `task_queue_workers_active`<br>2) 检查 worker 并发、配额限制<br>3) 检查 slow external deps（embedding/parsers） | 1) 扩容 worker / 提升 max_jobs（谨慎）<br>2) 启用 backpressure：限制单租户/数据集并发<br>3) 降级高成本 pipeline | [B. ingestion](#rb-ingestion) |
| `MimirQTaskQueueNoWorkersButHasBacklog` | depth>0 且 workers_active<1 持续 10m | 队列堆积但无人消费 | 1) 确认 worker deployment 是否存活<br>2) 检查 worker heartbeat 是否写入 Redis<br>3) 检查 RBAC/网络策略 | 1) 立刻拉起 worker / 回滚 worker 发布<br>2) 临时限流 ingest 入口（避免越堆越多）<br>3) 恢复后观察 backlog 下降 | [B. ingestion](#rb-ingestion) |
| `MimirQAuthzGroupDenyRatioHigh` | deny 比例 > 20%（10m），持续 20m | 大量“没权限/被拒绝”，访问异常（常见于组同步/allowlist 配置问题） | 1) 看 `authz_group_permission_total{result}`：`deny_no_groups` vs `deny_no_match`<br>2) 检查 OIDC groups claim / group sync 配置<br>3) 使用 access-graph summary/export 做 tenant 级排查 | 1) 回滚最近的权限/组映射变更（最快）<br>2) 修复 groups claim 映射、触发 group 同步<br>3) 临时放宽受影响资源的 allowlist（风险评估后） | [5.2) ACL deny 快速诊断](#rb-authz-deny) |
| `MimirQAuthzGroupDenySpike` | 5m 内 deny > 200，持续 15m | 突发性拒绝飙升（配置/目录同步突变/大批量访问触发） | 1) 对齐发生时间点与发布/配置变更<br>2) 查看 deny 结果分类与资源维度（dataset/document + read/write）<br>3) 采样用户侧报错 request_id（避免复制 query） | 1) 先止血：回滚/冻结最近的权限变更<br>2) 临时启用更严格限流（避免级联）<br>3) 修复后做 access review diff（验证恢复） | [5.2) ACL deny 快速诊断](#rb-authz-deny) |

#### 调参建议（快速）

- **先对齐 SLO，再定阈值**：例如检索延迟 p95/p99 的阈值建议与业务 SLO 绑定（留足抖动余量）。
- **多实例/多副本**：模板中的 `sum(rate(...))` 是全局聚合；如果你希望定位到某个实例/路由，请在 Grafana 用 label 维度拆分。
- **告警噪声控制**：对“有失败就告警”的规则（如 ingestion failures）建议结合 `for`、`increase()` 或更高阈值，避免单点偶发触发。

### 2.1 示例：处理 “Queue backlog but no workers”

当触发 `MimirQTaskQueueNoWorkersButHasBacklog`（depth>0 且 workers_active<1）时，优先按下面顺序操作：

1. **确认 worker 是否存活**
   - K8s：检查 worker deployment/pod 是否存在、是否 CrashLoop
   - 关注 worker 启动日志中 Redis 连接重试/失败信息
2. **确认 broker/心跳与队列快照**
   - `GET /api/v1/health/ready`（依赖是否整体就绪）
   - `GET /api/v1/observability/task-queue/snapshot`（admin-only，PII-safe）
3. **止血（优先恢复消费能力）**
   - 扩容/恢复 worker（推荐）
   - 若 Redis 故障：先恢复 Redis
   - 紧急兜底：临时关闭队列（`TASK_QUEUE_ENABLED=false`）让关键路径回到 inline（仅用于短期止血，后续务必补偿/回放）

### 2.2 示例：处理 “Zero-hit rate spike”

当触发 `MimirQHighRagZeroHitRate`（zero-hit 持续升高）时，常见根因是“索引滞后/漂移”或“检索策略变更”：

1. **先看聚合面板与 query analytics**
   - `/api/v1/observability/rag-metrics/summary`
   - `/api/v1/observability/rag-metrics/query-analytics`（top zero-hit / slow / error，hash-based）
2. **对比配置指纹（最快发现变更）**
   - `/api/v1/observability/config/snapshot`（脱敏 config + fingerprint）
3. **排查索引一致性与数据新鲜度**
   - dataset-scoped：`/api/v1/observability/index-audit?dataset_id=...`
4. **止血手段**
   - 优先“配置回滚”（最快、风险低）
   - 其次再做“索引修复/补偿 ingestion”（需要时间）

<a id="rb-readiness-503"></a>
### A. Readiness 503（依赖或数据库 schema 不可用）

优先检查：

1. Postgres：`DATABASE_URL`
2. Redis：`REDIS_URL`（若启用了 `TASK_QUEUE_ENABLED=true`）
3. 向量库：`VECTOR_BACKEND` + Milvus/Chroma 连接信息
4. MinIO：`MINIO_ENABLED=true` 时检查 `MINIO_ENDPOINT` 等
5. 数据库 schema：用管理员身份读取 `GET /api/v1/health/details`；若 `database.status=schema_outdated`，先执行 `python scripts/alembic_cli.py upgrade head`，确认迁移成功后再放量

生产模式关闭应用内 `create_all` 与运行期迁移时，readiness 会把 `alembic_version` 与当前镜像的 Alembic head 比较。Postgres 仅能执行 `SELECT 1` 不代表应用 schema 兼容。

多实例检索建议同时启用 `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED=true`，并显式设置 `RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY`。该值会作为跨实例共享的向量分片后端预算；Redis 暂时不可用时系统会降级为每进程本地预算，因此容量规划仍需为降级窗口预留余量。

---

<a id="rb-ingestion"></a>
### B. 文档 ingestion 卡住 / 失败

1. 查看后端日志（api + worker）
2. 如果启用了队列：确认 worker 正在运行且能连上 Redis
3. 检查上传目录/对象存储：
   - `UPLOAD_DIR`（容器内通常是 `/data/uploads`）
   - PVC 是否可写
   - 若使用 MinIO：bucket / credential / endpoint

---

<a id="rb-retrieval-quality"></a>
### C. 检索质量突然下降

建议按顺序排查：

1. **配置变化**：settings / env 是否变更（尤其是 retrieval/rerank 相关开关）
2. **索引一致性**：使用 index-audit 端点（需要 admin）
3. **候选池大小**：观察 retrieval trace 中候选数量、是否被 ACL/filter 截断

---

<a id="rb-admin-endpoints"></a>
## 3) 管理/诊断端点（RBAC 受限）

以下端点通常只允许 owner/admin（部分允许 auditor）：

- Observability 概览：`GET /api/v1/observability/rag-metrics/summary`
- Query Analytics（zero-hit/慢检索/错误）：`GET /api/v1/observability/rag-metrics/query-analytics`
- Trace Bundle（按 request_id 导出 PII-safe 诊断包）：`GET /api/v1/observability/rag-metrics/trace-bundle?request_id=...`
- Config Snapshot（脱敏配置快照 + 指纹）：`GET /api/v1/observability/config/snapshot`
- Periodic Jobs Freshness（周期巡检新鲜度/滞后）：`GET /api/v1/observability/periodic-jobs/freshness`
- Index 一致性检查：`GET /api/v1/observability/index-audit?dataset_id=...`
- Task Queue Snapshot（队列观测快照）：`GET /api/v1/observability/task-queue/snapshot`
- 审计日志列表：`GET /api/v1/audit/logs`
- 审计日志导出（SIEM）：`GET /api/v1/audit/logs/export`
- 权限访问图谱导出（Groups + ACL，NDJSON/JSON 分页）：`GET /api/v1/audit/access-graph/export`
- 权限访问图谱汇总（PII-minimal 计数汇总）：`GET /api/v1/audit/access-graph/summary`
- 审计日志保留清理（admin-only）：`POST /api/v1/audit/logs/purge`

---

<a id="rb-prometheus-metrics"></a>
## 3.1) Prometheus Metrics（可选）

当 `PROMETHEUS_ENABLED=true` 时，会额外暴露 `GET /metrics`（Prometheus 抓取入口）。

> 建议：`/metrics` 通常不做 RBAC，但应通过网关 / 网络策略限制访问范围（仅 Prometheus 可抓取）。

### RAG SLI（PII-safe）

- `rag_zero_hit_total`：`citations_count=0` 的请求总量（用于 zero-hit 率）
- `rag_errors_total`：发生检索错误的请求总量（用于 error rate）
- `rag_citations_count`：引用数直方图（含 `_bucket/_sum/_count`）
- `rag_retrieval_elapsed_seconds`：检索耗时直方图（含 p95/p99 计算所需 buckets）
- `rag_rerank_elapsed_seconds`：重排耗时直方图（仅在有 rerank 数据时 observe）

Labels 策略（默认安全）：
- 指标包含 `tenant_id`/`dataset_id` label keys，但默认 value 会折叠为 `"all"` 以控制基数。
- 如确需按租户/数据集拆分，可显式开启：
  - `PROMETHEUS_RAG_LABEL_TENANT_ID=true`
  - `PROMETHEUS_RAG_LABEL_DATASET_ID=true`

### Ingestion（PII-safe）

- `ingestion_runs_total{status,kind}`：ingestion run created/completed/failed/cancelled 总量
- `ingestion_run_duration_seconds{status,kind}`：ingestion run 耗时直方图
- `ingestion_processing_stage_total{stage}`：当前处于 `processing` 状态的文档，按 stage 聚合的分布

以上指标不包含文件名/路径/URL 等敏感字段。

### AuthZ / ACL（Groups, PII-safe）

- `authz_group_permission_total{resource,action,result}`：组权限命中/拒绝计数（用于排查“组同步/组权限配置”类问题）

Labels（低基数、默认安全）：
- `resource`：`dataset` / `document`
- `action`：`read` / `write`
- `result`：
  - `allow`：通过 group allowlist 放行
  - `deny_no_groups`：当前账号未解析到任何 tenant groups（常见于 OIDC groups claim 未配置/未开启同步）
  - `deny_no_match`：有 groups 但未命中资源 allowlist

以上指标不包含 tenant_id / account_id / group_id 等敏感 label。

---

## 4) 数据生命周期（当前状态）

项目正在补齐“导出/删除/保留策略”。当前已具备：

- 审计日志 NDJSON 导出（SIEM 友好）
- 审计日志按 retention purge（bounded delete）
- 审计日志 retention runner（适合 CronJob）：`python scripts/run_retention_jobs.py --audit-logs --dry-run`
- Knowledge assets retention runner（按 archived/disabled 文档做 bounded purge，并委托 document delete lifecycle 清理 chunks/KG/vector/object assets）：`python scripts/run_retention_jobs.py --knowledge-assets --dry-run`
- Dataset 文档清单 NDJSON 导出（默认脱敏，支持 cursor + gzip）：`GET /api/v1/datasets/{dataset_id}/documents/export`
- Dataset bundle ZIP 导出（包含 dataset/config/docs 清单，默认脱敏）：`GET /api/v1/datasets/{dataset_id}/export`
- Dataset purge（删除 dataset 内 documents/chunks/KG 衍生物；bounded，默认 dry-run）：`POST /api/v1/datasets/{dataset_id}/purge`
- Regression runs purge（评估工件保留清理；bounded，默认 dry-run）：`POST /api/v1/evaluations/ragas/regression/runs/purge`
- Regression runs retention runner（适合 CronJob）：`python scripts/run_retention_jobs.py --regression-runs --dry-run`
- Semantic cache retention runner（清理过期或 Redis payload 已丢失的 Milvus 缓存行）：`python scripts/run_retention_jobs.py --semantic-cache --dry-run --max-scan 1000 --max-delete 100`
- DB maintenance runner（VACUUM/ANALYZE + retention；适合 CronJob，默认 dry-run）：`python scripts/run_db_maintenance_jobs.py --vacuum --analyze --audit-logs --dry-run`（详见：`docs/deployment/db_maintenance.md`）
- 备份/恢复指南（Postgres + MinIO + vector backend）：`docs/deployment/backup_restore.md`
- DR drill（恢复验证 checklist + automation）：`docs/deployment/dr_drill.md`
- Chaos tests（依赖故障演练：Redis/MinIO/Milvus）：`docs/deployment/chaos_tests.md`
- Index audit periodic runner（适合 CronJob；bounded）：`python scripts/run_periodic_audit_jobs.py --index-audit --dry-run`
- Evidence drift audit periodic runner（适合 CronJob；bounded）：`python scripts/run_periodic_audit_jobs.py --evidence-drift-audit --dry-run`
- Access review daily summary runner（适合 CronJob；bounded）：`python scripts/run_periodic_audit_jobs.py --access-review --dry-run`
- Evidence drift repair enqueue（适合队列；bounded）：`POST /api/v1/evidence/suites/{suite_id}/repair-reference-sources?async_mode=true`（需要 `TASK_QUEUE_ENABLED=true`；返回 202 + `X-Task-Id`）
- Runbook 内容治理 SOP（作者/审核/更新/废弃）：`docs/deployment/content_governance_sop.md`

知识资产 retention 运维建议：
- 先 dry-run：`python scripts/run_retention_jobs.py --knowledge-assets --tenant-id <uuid> --dry-run --retention-days 90 --max-delete 100`
- 再 execute：`python scripts/run_retention_jobs.py --knowledge-assets --tenant-id <uuid> --execute --retention-days 90 --max-delete 100`
- 可按 dataset 缩小范围：追加 `--dataset-id <uuid>`
- 可只清某一类生命周期状态：追加 `--lifecycle-state archived|disabled|either`
- 若结果里的 `conflicts` 或 `errors` 非 0，先排查该租户是否仍有扫描/队列任务、对象存储异常或向量库删除失败，再重试；不要直接放大 `max-delete`
- 若启用了 `TASK_QUEUE_ENABLED=true`，document delete lifecycle 会先 best-effort 终止关联 document 任务，再删除资产；因此 CronJob/脚本是推荐入口，不建议手工直接删底表

审计日志检索（用于 SIEM / 巡检）：
- Index audit daily action：`observability.index_audit.daily`
- Evidence drift audit daily action：`evidence.drift_audit.daily`
- Access review daily action：`compliance.access_review.daily`
- Evidence repair enqueue action：`evidence.reference_sources.repair.enqueue`
- Evidence repair job action：`evidence.reference_sources.repair.job`
- Knowledge asset retention action：`knowledge.assets.retention`

后续将补齐：

- dataset/document 的合规 bundle 导出（含向量/KG/对象存储引用）

---

<a id="rb-ir"></a>
## 5) Incident Response（应急处置）

目标：先止血，再定位，再验证修复。

Incident Response Cookbook（可执行命令集）：`docs/deployment/incident_response_cookbook.md`

1. **确认影响面**
   - 是所有租户还是单租户？
   - 是单数据集还是所有数据集？
   - 是 ingest/index 还是 retrieval/rerank/LLM？
2. **收集最小证据（PII-safe 优先）**
   - request_id（前端会带 `X-Request-ID`，后端也会写入响应头/日志）
   - `/api/v1/observability/rag-metrics/summary`（聚合指标）
   - RAG trace / leaderboard / diff 报告（尽量用 hash / 指标，不要复制原始 query/文档）
   - 一键打包（PII-safe；含 config snapshot / trace bundle / access-graph summary / periodic job freshness）：`python scripts/incident_bundle.py --base-url <api> --tenant-id <tid> --token <admin_token> --request-id <rid>`
3. **止血手段（按场景）**
   - **成本/滥用飙升**：启用/调严 rate-limit 与 tenant QPS quota；观察 `Retry-After` 与 429 频率。
   - **检索质量骤降**：优先排查配置变更（settings/env），用 `retrieval_config_hash` 对比“变更前后”的配置指纹。
   - **索引一致性异常**：跑 index-audit 端点；必要时暂停新 ingestion，避免越写越乱。
   - **对象存储/向量库不可用**：Readiness 503 时先恢复依赖，再考虑回放/补偿任务。

<a id="rb-429"></a>
### 5.1) 429（Rate Limit / Quota）快速诊断

当客户端/前端出现 **HTTP 429** 时，优先检查响应体与响应头：

- Header：`Retry-After`（秒）
- Body：`detail.retry_after_sec` / `detail.limit` / `detail.scope`

常见 `scope`（示例）：

- `rate_limit:api` / `rate_limit:chat`：全局 rate-limit middleware（保护后端）
- `tenant_qps:chat` / `tenant_qps:retrieval`：租户级 QPS 配额（建议结合峰值与实例数调参）
- `chat_tokens`：Chat 助手 token 配额（成本治理）
- `tenant_documents` / `tenant_storage`：上传配额（文档数 / 存储容量）

处置建议（先止血）：

1. **尊重 Retry-After**：让客户端按 `Retry-After` 退避重试（避免雪崩）。
2. **确认是哪一类限流**（看 `scope`）：
   - `rate_limit:*`：调 `RATE_LIMIT_*`，必要时启用 Redis 分布式限流（避免多副本下“各自放水/各自限流”）。
   - `tenant_qps:*`：调 `TENANT_QPS_QUOTA_*`，同时观察 p95/p99 与后端依赖瓶颈；必要时扩容。
   - `chat_tokens`：从“用量与成本”页或聚合指标确认是否异常；必要时提升 quota 或切换为 warn 模式。
3. **回看告警/趋势**：429 往往是“更大问题的先兆”（依赖抖动、队列堆积、成本爆炸）。

配置项汇总：`docs/deployment/quota_rate_limit.md`

<a id="rb-authz-deny"></a>
### 5.2) ACL / Group Deny 快速诊断（AuthZ）

当触发 `MimirQAuthzGroupDenyRatioHigh` / `MimirQAuthzGroupDenySpike` 时，优先按“先分类、再定位、再止血”的顺序：

1. **先分类（deny 原因）**：看 Prometheus 指标的 `result` 标签：
   - `deny_no_groups`：通常是“没有解析到 tenant groups”（OIDC groups claim 未配置/未启用/同步失败）
   - `deny_no_match`：通常是“有 groups 但未命中 allowlist”（权限配置/组映射错误）
2. **定位（最短路径）**
   - 目录/认证侧：对照 `docs/guides/oidc_groups_claim.md` 检查 groups claim 配置与映射策略
   - Tenant 权限面：使用 access-graph：
     - 汇总：`GET /api/v1/audit/access-graph/summary`（计数视角）
     - 导出：`GET /api/v1/audit/access-graph/export`（NDJSON/JSON；默认 PII-safe）
3. **止血（慎重）**
   - 最优先：回滚最近的组同步/权限映射/allowlist 变更（可配置项回滚最快）
   - 需要业务评估后才做：临时放宽受影响资源的 allowlist（避免扩大越权面）
   - 若同时伴随 429/依赖抖动：先用 rate-limit/quota 保护后端，避免告警风暴

---

<a id="rb-rollback"></a>
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

---

<a id="rb-access-review"></a>
## 7) Access Review（访问审查）工作流（cadence + diff + troubleshooting）

本节给 oncall/安全/平台团队一套 **可执行** 的访问审查流程，目标是：

- 发现“目录/组/allowlist”层面的异常变更（权限漂移）
- 发现权限配置导致的拒绝/越权风险（默认 fail-closed）
- 让审查过程 **可追溯**（audit logs + snapshots + diff）

> 原则：默认 **PII-safe**。优先使用计数/哈希/指标；除非合规需要，不要导出 raw user_id/group 名称。

### 7.1) 推荐节奏（Cadence）

**Daily（自动化）**

1. 运行 access review daily summary（适合 CronJob）：
   - `python scripts/run_periodic_audit_jobs.py --access-review --execute`
   - 写入审计日志 action：`compliance.access_review.daily`（resource_type=`access_review_summary`）
2. 监控新鲜度（staleness）：
   - `GET /api/v1/observability/periodic-jobs/freshness`（admin-only，PII-safe）

**Weekly（人工审查）**

- 导出一次 access graph snapshot（NDJSON）并与上周对比（diff），重点关注：
  - group membership churn 是否异常
  - dataset/document allowlist 是否被大量更改
  - dataset/document 的 access_mode/permission 分布是否出现突变

**Monthly / Quarterly（合规审计）**

- 在合规要求下，允许 `include_sensitive=true` 导出（可能包含 group name / external_id / user_id），但必须：
  - 存储在受控位置（最小权限）
  - 严格限定导出窗口与用途

### 7.2) 审查所用数据源（端点 / 工具）

- 汇总（计数视角，最常用）：`GET /api/v1/audit/access-graph/summary`
- 导出（快照，分页）：`GET /api/v1/audit/access-graph/export`
  - 推荐：`export_format=ndjson&gzip=true`（带 `X-Next-Cursor` 方便续传）
  - 默认：`include_sensitive=false`（只含 hashes，不含 raw ids）
- 快速过滤审计日志（UI）：`/audit` → 使用“快速预设”（Access Review / Index Audit / Evidence Drift / Access Graph）
- Diff 工具（PII-safe、有界输出）：`python scripts/access_graph_diff.py --a <snapshotA> --b <snapshotB>`
- 一键打包（PII-safe）：`python scripts/incident_bundle.py --request-id <rid> ...`
  - 当前 bundle 会包含：config snapshot / trace bundle / access-graph summary / periodic job freshness

### 7.3) 实操流程（Step-by-step）

#### Step 1：确认自动化是否健康（Freshness）

1. 调用 freshness 端点：
   - `GET /api/v1/observability/periodic-jobs/freshness`
2. 关注：
   - `stale=true` 的条目（说明 job 可能没有跑、或写 audit log 失败）
   - `age_seconds` 是否明显超过预期（默认 stale_after≈36h）
3. 如果 stale：
   - 检查 CronJob 是否启用与 schedule 是否正确（K8s 通常用 UTC）
   - 检查是否因 DB/权限导致 audit log 写入失败（查看 api/worker 日志）

#### Step 2：导出 access graph snapshot（默认 PII-safe）

建议每次导出生成一个带时间戳的文件名，存放到受控的审计工件位置。

推荐方式：

- Web UI：`/access-review` → “下载导出”
- 或直接导出（NDJSON）：
  - `GET /api/v1/audit/access-graph/export?export_format=ndjson&gzip=true&limit=10000`

> 注意：浏览器通常会自动解压 `Content-Encoding: gzip`，所以保存下来的文件未必是 `.gz`。

#### Step 3：做 diff（有界总结 + churn 线索）

拿到两次快照（例如 `access-graph.20260301.ndjson` 与 `access-graph.20260308.ndjson`）后：

```bash
python scripts/access_graph_diff.py --a access-graph.20260301.ndjson --b access-graph.20260308.ndjson
```

你会得到：

- kinds 级别的 `added/removed/changed` 统计（group/dataset/document + 各类 membership/allowlist）
- top churn（按 group_id / dataset_id / document_id 聚合的增删数量）

推荐审阅顺序：

1. 先看 **group_member_by_group_id**（组成员变动是否集中在某些组）
2. 再看 dataset/document 的 allowlist 相关 kinds（是否出现大面积增删）
3. 最后看 group/dataset/document 的 `changed_fields` 示例（是否权限模式发生变化）

#### Step 4：异常时的最短定位路径

如果你看到 **deny / 权限异常**，优先结合：

- Prometheus 指标：`authz_group_permission_total{resource,action,result}`
  - `deny_no_groups`：更像“没有解析到 groups”（OIDC groups claim / 同步链路问题）
  - `deny_no_match`：更像“allowlist 未命中”（权限配置/组映射错误）
- 以及本 runbook 的：[5.2) ACL / Group Deny 快速诊断](#rb-authz-deny)

如果你看到 **429/限流告警**，优先看：[5.1) 429 快速诊断](#rb-429) 并避免重试风暴。
